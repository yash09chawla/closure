"""Accreditation check against the two authentic sources (UGC, AICTE) + evidence PDF.

No searching in a browser: UGC JSON and the AICTE PDF are matched locally (milliseconds).
The browser is used only to capture the UGC page screenshot as proof."""
import asyncio
import re
import time
from datetime import datetime
from pathlib import Path

import pymupdf
from rapidfuzz import fuzz

from .. import config
from ..evidence import browser, render
from ..evidence.render import e
from . import sources

TECH_RE = re.compile(r"\b(B\.?\s?E\b|B\.?\s?TECH|M\.?\s?E\b|M\.?\s?TECH|ENGINEERING|TECHNOLOGY|MBA|MCA|PHARM|"
                     r"ARCHITECTURE|B\.?\s?ARCH|POLYTECHNIC|HOTEL MANAGEMENT|PGDM|APPLIED ARTS)", re.I)
REGION_LABEL = {"Southern": ("Southern Region", "Southern (SR)"), "Northern": ("Northern Region", "Northern (NR)"),
                "Western": ("Western Region", "Western (WR)"), "Eastern": ("Eastern Region", "Eastern (ER)"),
                "Central": ("Central Region", "Central (CR)"), "North-West": ("North West Region", "North West (NWR)"),
                "South-West": ("South West Region", "South West (SWR)"),
                "South-Central": ("South Central Regions", "South Central (SCR)")}


def name_variants(name: str) -> list[str]:
    name = re.sub(r"\[.*?\]", " ", name or "")
    name = re.sub(r"\s+-\s+(INDIA|India)\b.*$", "", name)
    out = {name.strip()}
    out.add(re.split(r",", name)[0].strip())                    # "Anna University, Chennai" -> "Anna University"
    out.add(re.sub(r"\s+-\s+\d{6}$", "", name).strip())
    return [v for v in out if len(v) > 3]


def is_technical(*texts) -> bool:
    return any(TECH_RE.search(t or "") for t in texts)


def match_ugc(name: str) -> dict | None:
    best = None
    variants = [sources.norm(v) for v in name_variants(name)]
    for t, lst in sources.ugc_lists().items():
        for rec in lst:
            n = sources.norm(rec["uni_name"])
            score = 100 if n in variants else max(fuzz.ratio(n, v) for v in variants)
            if score >= 92 and (best is None or score > best["score"]):
                best = {"score": score, "type": t, "type_label": config.UGC_TYPES[t][0], "record": rec,
                        "page_url": config.UGC_PAGE.format(token=config.UGC_TYPES[t][1])}
    return best


def match_aicte(name: str, district_hint: str = "") -> dict | None:
    if not name:
        return None
    variants = [sources.norm(v) for v in name_variants(name)]
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


async def _ugc_shot(hit: dict, out_png: Path) -> None:
    ctx, page = await browser.new_page(width=1366, height=820)
    try:
        await page.goto(hit["page_url"], wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_selector("#tbodyuni tr td", timeout=35000)
        name = hit["record"]["uni_name"]
        await page.fill("#tbl_filter input", name)
        await page.wait_for_timeout(400)
        await page.evaluate("""(name) => {
            const rows=[...document.querySelectorAll('#tbodyuni tr')];
            const r=rows.find(r=>r.children[2] && r.children[2].innerText.trim().toLowerCase()===name.trim().toLowerCase());
            if(r){ r.querySelectorAll('td').forEach(td=>{td.style.background='#fff176';td.style.fontWeight='600'});}
            const f=document.querySelector('#tbl_filter'); if(f){ window.scrollTo(0, f.getBoundingClientRect().top + window.scrollY - 190); }
        }""", name)
        await page.wait_for_timeout(250)
        await page.screenshot(path=str(out_png))
    finally:
        await ctx.close()


def _aicte_cover_shot(out_png: Path) -> None:
    """Top of page 1 of the AICTE list — background for the 'searched, 0 results' proof."""
    doc = pymupdf.open(str(sources.aicte_pdf()))
    page = doc[0]
    clip = pymupdf.Rect(0, 0, page.rect.width, page.rect.height * 0.45)
    page.get_pixmap(dpi=150, clip=clip).save(str(out_png))


async def _ugc_search_shot(name: str, out_png: Path, type_id: int = 2) -> None:
    """UGC list page with the university name typed in its search box (shows 'No matching records found')."""
    url = config.UGC_PAGE.format(token=config.UGC_TYPES[type_id][1])
    ctx, page = await browser.new_page(width=1366, height=820)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_selector("#tbodyuni tr td", timeout=35000)
        await page.fill("#tbl_filter input", name)
        await page.wait_for_timeout(500)
        await page.evaluate("""() => { const f=document.querySelector('#tbl_filter');
            if(f){ window.scrollTo(0, f.getBoundingClientRect().top + window.scrollY - 190); } }""")
        await page.wait_for_timeout(250)
        await page.screenshot(path=str(out_png))
    finally:
        await ctx.close()


async def run(university: str, college: str, degree_text: str, workdir: Path, out_pdf: Path, log) -> dict:
    t0 = time.time()
    technical = is_technical(degree_text, college)
    district = ""
    m = re.search(r"\[(.*?)\]", college or "")
    if m:
        district = m.group(1)
    ugc, a_uni, a_col = await asyncio.gather(
        asyncio.to_thread(match_ugc, university),
        asyncio.to_thread(match_aicte, university),
        asyncio.to_thread(match_aicte, college, district),
    )
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

    # ---- evidence capture (in parallel) ----
    blocks, jobs = [], []
    pdf_title = "Groupwise-List of Institutions_compressed.pdf"
    n_pages = sources.aicte_page_count() if aicte_hit else 0
    aicte_blocks = []
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
    if ugc:
        ugc_png = workdir / "ugc.png"
        jobs.append(_ugc_shot(ugc, ugc_png))
    # "not found" proofs — the closure document records the negative search too
    search_name = name_variants(university)[0] if university else ""
    aicte_miss_png = ugc_miss_png = None
    if not aicte_hit and search_name:
        aicte_miss_png = workdir / "aicte_notfound.png"
        jobs.append(asyncio.to_thread(_aicte_cover_shot, aicte_miss_png))
    if not ugc and search_name:
        ugc_miss_png = workdir / "ugc_notfound.png"
        jobs.append(_ugc_search_shot(search_name, ugc_miss_png))
    results = await asyncio.gather(*jobs, return_exceptions=True)
    errors = [str(r) for r in results if isinstance(r, Exception)]
    if errors:
        log("evidence capture warning: " + "; ".join(errors)[:300])

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

    def miss_blocks():
        out = []
        if aicte_miss_png is not None:
            n_rows = len(sources.aicte_index())
            frame = (render.browser_frame(config.AICTE_LIST, render.data_url(aicte_miss_png), "pdf", pdf_title,
                                          f"1 / {sources.aicte_page_count()}", f"{search_name}   0/0")
                     if aicte_miss_png.exists() else "")
            out.append({"heading": "AICTE approved institutions 2025-26 — NOT FOUND", "url": config.AICTE_LIST,
                        "frame_html": frame + f'<div class="miss">"{e(search_name)}" was searched in all {n_rows:,} '
                                              f'rows of the AICTE 2025-26 list (university and affiliated-college '
                                              f'names, fuzzy match) — no matching institution.</div>'})
        if ugc_miss_png is not None:
            counts = ", ".join(f"{config.UGC_TYPES[t][0]} {len(l)}" for t, l in sources.ugc_lists().items())
            page_url = config.UGC_PAGE.format(token=config.UGC_TYPES[2][1])
            frame = render.browser_frame(page_url, render.data_url(ugc_miss_png)) if ugc_miss_png.exists() else ""
            out.append({"heading": "UGC — list of universities — NOT FOUND", "url": page_url,
                        "frame_html": frame + f'<div class="miss">"{e(search_name)}" was searched in all four UGC '
                                              f'lists ({e(counts)}) — no matching university.</div>'})
        return out

    ugc_ok = bool(ugc and ugc_png and ugc_png.exists())
    if body_short == "AICTE":
        blocks = aicte_blocks_html() + ([ugc_block()] if ugc_ok else [])
    elif body_short == "UGC":
        blocks = ([ugc_block()] if ugc_ok else []) + aicte_blocks_html()
    blocks = blocks + miss_blocks()

    display_name = (ugc["record"]["uni_name"] if ugc else (a_uni["row"]["name"].title() if a_uni else university))
    summary = f"{'Found' if ugc else 'Not found'} in UGC, {'Found' if aicte_hit else 'Not found'} in AICTE"
    if blocks:
        header = [("University/College/Institute name", display_name)]
        if a_col:
            header.append(("Affiliated college", a_col["row"]["name"].title()))
        header += [("Link", url or "—"), ("Accreditation Body", body_short or "NOT DISCLOSED"), ("Result", summary)]
        html = render.evidence_html(header, blocks,
                                    f"Captured {datetime.now().strftime('%d-%m-%Y %H:%M:%S')} by HV Closure Engine "
                                    f"from the official UGC / AICTE sources. Highlight marks the matched record; "
                                    f"red boxes record searches that returned no match.")
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
        "summary": summary,
        "pdf": str(out_pdf) if blocks else "",
        "seconds": round(time.time() - t0, 1),
        "warnings": errors,
    }
