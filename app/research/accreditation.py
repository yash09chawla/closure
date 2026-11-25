"""Accreditation research service — input is PUBLIC information only (institution name, optional affiliated
college, programme type, state). No candidate data is ever needed or accepted.

Authority = the official lists themselves:
  * UGC  — the four university lists behind ugc.gov.in/universitydetails (Central / State / State Private /
           Deemed), fetched from UGC's own JSON endpoint and cached locally
  * AICTE — the 2025-26 Group-wise list of approved institutions (official PDF, 13.6k rows indexed locally)
Matching is local (milliseconds). OpenAI is used only when the name does not match directly, to resolve the
institution's OFFICIAL name / former names / abbreviation from public sources; the resolved names are then
matched again against the official lists, so a search result can never "accredit" anything by itself.

Evidence PDF: browser-framed screenshots of the official pages (address bar shows the real URL), the matched row
highlighted, a "Sources consulted" table listing every official URL checked and its result. When nothing is
found the PDF still shows the UGC searches returning no records, so the closure can proceed as Non-Accredited.
"""
import asyncio
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import pymupdf
from rapidfuzz import fuzz

from .. import config, llm, privacy
from ..evidence import browser, render
from . import sources

TECH_RE = re.compile(r"\b(B\.?\s?E\b|B\.?\s?TECH|M\.?\s?E\b|M\.?\s?TECH|ENGINEERING|TECHNOLOGY|MBA|MCA|PHARM|"
                     r"ARCHITECTURE|B\.?\s?ARCH|POLYTECHNIC|HOTEL MANAGEMENT|PGDM|APPLIED ARTS)", re.I)
REGION_LABEL = {"Southern": ("Southern Region", "Southern (SR)"), "Northern": ("Northern Region", "Northern (NR)"),
                "Western": ("Western Region", "Western (WR)"), "Eastern": ("Eastern Region", "Eastern (ER)"),
                "Central": ("Central Region", "Central (CR)"), "North-West": ("North West Region", "North West (NWR)"),
                "South-West": ("South West Region", "South West (SWR)"),
                "South-Central": ("South Central Regions", "South Central (SCR)")}
# common abbreviations used in initiation data / reverts (offline; extended by the OpenAI name resolver)
ALIASES = {
    "VTU": "Visvesvaraya Technological University", "AKTU": "Dr. A.P.J. Abdul Kalam Technical University",
    "IGNOU": "Indira Gandhi National Open University", "GTU": "Gujarat Technological University",
    "RGPV": "Rajiv Gandhi Proudyogiki Vishwavidyalaya", "SPPU": "Savitribai Phule Pune University",
    "MAKAUT": "Maulana Abul Kalam Azad University of Technology", "BPUT": "Biju Patnaik University of Technology",
    "RTU": "Rajasthan Technical University", "KTU": "APJ Abdul Kalam Technological University",
    "JNTUH": "Jawaharlal Nehru Technological University Hyderabad",
    "JNTUK": "Jawaharlal Nehru Technological University Kakinada",
    "JNTUA": "Jawaharlal Nehru Technological University Anantapur",
    "PRIST": "Ponnaiyah Ramajayam Institute of Science and Technology",
}


@dataclass
class AccreditationQuery:
    university: str                     # awarding university / institution (public name)
    college: str = ""                   # affiliated college, if any (public name)
    programme: str = ""                 # e.g. "B.E. Civil Engineering" — decides UGC vs AICTE as the body
    state: str = ""                     # optional disambiguation
    extra_names: list[str] = field(default_factory=list)

    def public_text(self) -> str:
        return " | ".join(x for x in (self.university, self.college, self.programme, self.state) if x)


def name_variants(name: str) -> list[str]:
    name = re.sub(r"\[.*?\]", " ", name or "")
    name = re.sub(r"\s+-\s+(INDIA|India)\b.*$", "", name)
    out = {name.strip()}
    out.add(re.split(r",", name)[0].strip())                     # "Anna University, Chennai" -> "Anna University"
    out.add(re.sub(r"\s+-\s+\d{6}$", "", name).strip())
    out.add(re.sub(r"\s*\((?:deemed[^)]*|[A-Z]{2,8})\)\s*", " ", name, flags=re.I).strip())  # "(Deemed University)", "(PRIST)"
    out.add(re.sub(r"\(\s*deemed\s+(?:to\s+be\s+)?university\s*\)", "University", name, flags=re.I).strip())
    key = re.sub(r"[^A-Z]", "", name.upper())
    if key in ALIASES:
        out.add(ALIASES[key])
    for ab in re.findall(r"\(([A-Z]{2,8})\)", name):
        if ab in ALIASES:
            out.add(ALIASES[ab])
    return [re.sub(r"\s+", " ", v) for v in out if len(v) > 3]


def is_technical(*texts) -> bool:
    return any(TECH_RE.search(t or "") for t in texts)


def match_ugc(names: list[str]) -> dict | None:
    best = None
    variants = list(dict.fromkeys(sources.norm(v) for n in names for v in name_variants(n)))
    if not variants:
        return None
    for t, lst in sources.ugc_lists().items():
        for rec in lst:
            n = sources.norm(rec["uni_name"])
            score = 100 if n in variants else max(fuzz.ratio(n, v) for v in variants)
            if score >= 92 and (best is None or score > best["score"]):
                best = {"score": score, "type": t, "type_label": config.UGC_TYPES[t][0], "record": rec,
                        "page_url": config.UGC_PAGE.format(token=config.UGC_TYPES[t][1])}
    return best


def match_aicte(names: list[str], district_hint: str = "") -> dict | None:
    variants = list(dict.fromkeys(sources.norm(v) for n in names if n for v in name_variants(n)))
    if not variants:
        return None
    best = None
    for row in sources.aicte_index():
        score = 100 if row["norm"] in variants else max(fuzz.ratio(row["norm"], v) for v in variants)
        if score < 93:
            continue
        if district_hint and district_hint.upper() in (row["district"] + " " + row["city"]).upper():
            score += 5
        if best is None or score > best["score"]:
            best = {"score": score, "row": row}
    return best


def resolve_official_names(q: AccreditationQuery) -> tuple[list[str], str, dict]:
    """OpenAI (public name only) → official name, former names, abbreviations, website. ([], '', {}) if off."""
    if not llm.available():
        return [], "", {}
    prompt = f"""An Indian higher-education institution is referred to as "{q.university}"
{f'(affiliated college: "{q.college}")' if q.college else ''}{f' in {q.state}' if q.state else ''}.
Using official/public sources, identify it. Return ONLY JSON with keys:
official_name (exactly as listed by UGC or AICTE), other_names (list of former names, abbreviations and
common variants), website (official website URL), category (one of: Central University, State University,
State Private University, Deemed to be University, AICTE-approved institution, Not an Indian institution, Unknown)."""
    data, meta = llm.web_search_json(prompt, None, "accreditation:name-resolution")
    names = [data.get("official_name", "")] + list(data.get("other_names") or [])
    return [n for n in names if isinstance(n, str) and len(n) > 3], data.get("website", "") or "", meta


def _aicte_shot(row: dict, out_png: Path) -> None:
    doc = pymupdf.open(str(sources.aicte_pdf()))
    page = doc[row["page"] - 1]
    x0, y0, x1, y1 = row["bbox"]
    r = pymupdf.Rect(x0 - 2, y0 - 2, x1 + 2, y1 + 2)
    annot = page.add_rect_annot(r)
    annot.set_colors(stroke=(0.85, 0.1, 0.1), fill=(1.0, 0.92, 0.2))
    annot.set_border(width=1.2)
    annot.set_opacity(0.5)
    annot.update()
    top = max(0, y0 - 230)
    clip = pymupdf.Rect(0, top, page.rect.width, min(page.rect.height, top + 470))
    page.get_pixmap(dpi=170, clip=clip, annots=True).save(str(out_png))


def _notice_shot(region: str, group: str, out_png: Path) -> bool:
    doc = pymupdf.open(str(sources.aicte_notice_pdf()))
    if doc.page_count < 2:
        return False
    page = doc[1]
    gnum = re.sub(r"\D", "", group or "")
    hits = page.search_for(f"Group - {gnum}") if gnum else []
    for q in REGION_LABEL.get(region, ()):
        hits += page.search_for(q)
    for h in hits:
        a = page.add_highlight_annot(h)
        a.update()
    clip = pymupdf.Rect(0, 0, page.rect.width, page.rect.height * 0.62)
    page.get_pixmap(dpi=150, clip=clip, annots=True).save(str(out_png))
    return bool(hits)


async def _ugc_capture(page_url: str, search: str, out_png: Path, highlight: str = "") -> None:
    """Open the official UGC list page, type the name into its own search box, highlight the matching row
    (if any) and screenshot what the browser shows."""
    ctx, page = await browser.new_page(width=1366, height=820)
    try:
        await page.goto(page_url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_selector("#tbodyuni tr td", timeout=35000)
        await page.fill("#tbl_filter input", search)
        await page.wait_for_timeout(500)
        await page.evaluate("""(name) => {
            if (name) {
              const rows=[...document.querySelectorAll('#tbodyuni tr')];
              const r=rows.find(r=>r.children[2] && r.children[2].innerText.trim().toLowerCase()===name.trim().toLowerCase());
              if(r){ r.querySelectorAll('td').forEach(td=>{td.style.background='#fff176';td.style.fontWeight='600'});}
            }
            const f=document.querySelector('#tbl_filter'); if(f){ window.scrollTo(0, f.getBoundingClientRect().top + window.scrollY - 190); }
        }""", highlight)
        await page.wait_for_timeout(250)
        await page.screenshot(path=str(out_png))
    finally:
        await ctx.close()


def _search_term(name: str) -> str:
    """Distinctive part of the name for the UGC search box ("Anna University, Chennai" → "Anna University")."""
    v = name_variants(name)
    return min(v, key=len) if v else name


async def run(q: AccreditationQuery, workdir: Path, out_pdf: Path, log=lambda m: None) -> dict:
    t0 = time.time()
    workdir.mkdir(parents=True, exist_ok=True)
    privacy.assert_public(q.public_text(), "accreditation:input")  # this service never needs personal data
    technical = is_technical(q.programme, q.college)
    district = (re.search(r"\[(.*?)\]", q.college or "") or [None, ""])[1]
    names = [q.university] + list(q.extra_names)
    ugc, a_uni, a_col = await asyncio.gather(asyncio.to_thread(match_ugc, names),
                                             asyncio.to_thread(match_aicte, names),
                                             asyncio.to_thread(match_aicte, [q.college], district))
    resolved, website, meta = [], "", {}
    if not (ugc or a_uni or a_col) and llm.available():
        log(f"no direct match for '{q.university}' — resolving the official name from public sources")
        try:
            resolved, website, meta = await asyncio.to_thread(resolve_official_names, q)
            log(f"resolved names: {', '.join(resolved[:4]) or '—'}")
            if resolved:
                ugc, a_uni = await asyncio.gather(asyncio.to_thread(match_ugc, resolved),
                                                  asyncio.to_thread(match_aicte, resolved))
        except privacy.PrivacyViolation:
            raise
        except Exception as e:  # research is best effort; the result is flagged, never invented
            log(f"name resolution failed: {e}")
    log(f"UGC: {'found as ' + ugc['type_label'] + ' — ' + ugc['record']['uni_name'] if ugc else 'not listed'}; "
        f"AICTE: university {'row ' + a_uni['row']['sr'] if a_uni else 'not listed'}, "
        f"college {'row ' + a_col['row']['sr'] if a_col else 'not listed'}")

    aicte_hit = bool(a_uni or a_col)
    if technical and aicte_hit:
        body, body_short, url, year = ("All India Council for Technical Education", "AICTE", config.AICTE_LIST,
                                       config.AICTE_YEAR)
    elif ugc:
        body, body_short, url, year = "University Grants Commission", "UGC", ugc["page_url"], str(datetime.now().year)
    elif aicte_hit:
        body, body_short, url, year = ("All India Council for Technical Education", "AICTE", config.AICTE_LIST,
                                       config.AICTE_YEAR)
    else:
        body = body_short = url = year = ""

    # ---------------- evidence capture (in parallel) ----------------
    jobs, aicte_blocks = [], []
    pdf_title = "Groupwise-List of Institutions_compressed.pdf"
    n_pages = sources.aicte_page_count() if aicte_hit else 0
    for label, hit in (("University", a_uni), ("Affiliated college", a_col)):
        if hit:
            png = workdir / f"aicte_{hit['row']['sr']}.png"
            jobs.append(asyncio.to_thread(_aicte_shot, hit["row"], png))
            r = hit["row"]
            aicte_blocks.append({"png": png, "heading": f"AICTE approved institutions 2025-26 — {label}",
                                 "url": f"{config.AICTE_LIST}#page={r['page']}",
                                 "page_info": f"{r['page']} / {n_pages}", "find": r["name"].title(),
                                 "caption": f"Row {r['sr']} · AICTE Permanent Id {r['aicte_id']} · {r['name']} · "
                                            f"{r['region']} / {r['state']} / {r['district']} · {r['group']}"})
    notice_png = None
    first = (a_uni or a_col or {}).get("row")
    if first:
        notice_png = workdir / "aicte_notice.png"
        jobs.append(asyncio.to_thread(_notice_shot, first["region"], first["group"], notice_png))
    ugc_png = None
    miss_pngs = []
    if ugc:
        ugc_png = workdir / "ugc.png"
        jobs.append(_ugc_capture(ugc["page_url"], ugc["record"]["uni_name"], ugc_png, ugc["record"]["uni_name"]))
    elif not aicte_hit:
        # not found anywhere → screenshot every UGC list searched for the name, showing "no matching records"
        term = _search_term(q.university)
        for t, (label, token) in config.UGC_TYPES.items():
            png = workdir / f"ugc_search_{t}.png"
            page_url = config.UGC_PAGE.format(token=token)
            miss_pngs.append((label, page_url, png))
            jobs.append(_ugc_capture(page_url, term, png))
    results = await asyncio.gather(*jobs, return_exceptions=True)
    errors = [str(r) for r in results if isinstance(r, Exception)]
    if errors:
        log("evidence capture warning: " + "; ".join(errors)[:300])

    blocks = []

    def ugc_block():
        rec = ugc["record"]
        return {"heading": f"UGC — List of {ugc['type_label'].replace('University', 'Universities')}", "url": ugc["page_url"],
                "frame_html": render.browser_frame(ugc["page_url"], render.data_url(ugc_png)),
                "caption": f"{rec['uni_name']} · {rec.get('address', '').strip()} {rec.get('Zip', '')} · "
                           f"{rec.get('state', '').strip()} · Status {rec.get('status', '')} · "
                           f"Website {rec.get('url', '')}"}

    def aicte_blocks_html():
        out = []
        for b in aicte_blocks:
            if b["png"].exists():
                out.append({"heading": b["heading"], "url": b["url"], "caption": b["caption"],
                            "frame_html": render.browser_frame(config.AICTE_LIST, render.data_url(b["png"]), "pdf",
                                                               pdf_title, b["page_info"], b["find"])})
        if notice_png and notice_png.exists():
            out.append({"heading": "AICTE Public Notice 2025-26 — approval process group", "url": config.AICTE_NOTICE,
                        "caption": f"{first['group']} covers the {first['region']} region",
                        "frame_html": render.browser_frame(config.AICTE_NOTICE, render.data_url(notice_png), "pdf",
                                                           "Public Notice 2025-26.pdf", "2 / 2")})
        return out

    ugc_ok = bool(ugc and ugc_png and ugc_png.exists())
    if body_short == "AICTE":
        blocks = aicte_blocks_html() + ([ugc_block()] if ugc_ok else [])
    elif body_short == "UGC":
        blocks = ([ugc_block()] if ugc_ok else []) + aicte_blocks_html()
    else:
        for label, page_url, png in miss_pngs:
            if png.exists():
                blocks.append({"heading": f"UGC — List of {label.replace('University', 'Universities')} — search "
                                          f"\"{_search_term(q.university)}\"", "url": page_url,
                               "frame_html": render.browser_frame(page_url, render.data_url(png)),
                               "caption": "Search on the official UGC list — no matching record."})
        blocks.append({"heading": "AICTE approved institutions 2025-26", "url": config.AICTE_LIST,
                       "note": f"All {len(sources.aicte_index()):,} rows of the official AICTE 2025-26 list were "
                               f"searched for \"{q.university}\"" + (f" and \"{q.college}\"" if q.college else "") +
                               " (exact and fuzzy match ≥ 93 %) — no matching institution."})

    # every official source checked, with its result
    src = []
    for t, (label, token) in config.UGC_TYPES.items():
        hit_here = bool(ugc and ugc["type"] == t)
        src.append({"name": f"UGC — {label} list", "url": config.UGC_PAGE.format(token=token), "found": hit_here,
                    "result": f"Listed: {ugc['record']['uni_name']}" if hit_here else "Not listed"})
    src.append({"name": "AICTE — Approved institutions 2025-26", "url": config.AICTE_LIST, "found": aicte_hit,
                "result": "; ".join(f"{lbl}: row {h['row']['sr']} (p.{h['row']['page']})"
                                    for lbl, h in (("university", a_uni), ("college", a_col)) if h) or "Not listed"})
    if first:
        src.append({"name": "AICTE — Public Notice 2025-26", "url": config.AICTE_NOTICE, "found": True,
                    "result": f"{first['group']} / {first['region']} region"})

    display_name = (ugc["record"]["uni_name"] if ugc else (a_uni["row"]["name"].title() if a_uni else q.university))
    header = [("University/College/Institute name", display_name)]
    if a_col:
        header.append(("Affiliated college", a_col["row"]["name"].title()))
    header += [("Link", url or config.UGC_PAGE.format(token=config.UGC_TYPES[2][1])),
               ("Accreditation Body", body_short or "NOT DISCLOSED"),
               ("Result", f"Accredited — {body}" if body else "Not found in the official UGC / AICTE lists")]
    html = render.evidence_html(
        header, blocks,
        f"Captured {datetime.now().strftime('%d-%m-%Y %H:%M:%S')} by HV Closure Engine from the official "
        f"{body_short or 'UGC / AICTE'} sources. Highlight marks the matched record. Searched with public "
        f"institution information only.", sources=src, title="Accreditation verification")
    await browser.html_to_pdf(html, str(out_pdf), a4=True)

    return {
        "status": "Accredited" if body else "Non-Accredited",
        "body": body or "NOT DISCLOSED", "body_short": body_short, "url": url, "year": year,
        "country": "India" if body else "", "technical": technical,
        "ugc": ({"name": ugc["record"]["uni_name"], "type": ugc["type_label"], "status": ugc["record"].get("status"),
                 "website": ugc["record"].get("url"), "score": ugc["score"]} if ugc else None),
        "aicte_university": a_uni["row"] if a_uni else None,
        "aicte_college": a_col["row"] if a_col else None,
        "canonical_university": display_name,
        "resolved_names": resolved, "resolved_website": website,
        "sources": src, "query": asdict(q),
        "pdf": str(out_pdf) if out_pdf.exists() else "",
        "meta": meta, "seconds": round(time.time() - t0, 1), "warnings": errors,
    }
