"""Passing-criteria research service — input is GENERAL programme information only:
institute, degree, major/branch, study mode (full-time / part-time / distance / online), duration, regulation or
academic year, affiliated-college yes/no. No candidate name, number or document is ever needed or accepted.

Only the institute's OWN website is an authentic source:
1. knowledge cache (institute + degree + mode + regulation) → instant, $0
2. official domain = UGC record website → university e-mail domain hint → else resolved by an OpenAI web search
   and accepted only if it is an academic domain (.ac.in / .edu / .edu.xx / .ac.xx) or matches the UGC record
3. OpenAI web_search locked to that domain → URL of the regulation document + clause heading + verbatim phrase
4. download it, locate the clause, highlight it, extract the verbatim text
5. verify the numbers reported are really in the document (otherwise the field is flagged, not trusted)
Evidence PDF: browser-framed page with the real URL, highlighted clause, verbatim quote, sources table and the
exact (general) query that was searched.
"""
import asyncio
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import pymupdf

from .. import config, llm, privacy
from ..evidence import browser, render
from ..extract.mail import FREE_MAIL, registrable_domain
from . import sources

KB = config.KNOWLEDGE / "passing.json"
DOCS = config.KNOWLEDGE / "docs"
DOCS.mkdir(parents=True, exist_ok=True)
PASS_PAT = re.compile(r"(?i)pass(ing)?\s+(requirements?|criteria|minimum|marks)|minimum\s+(of\s+)?\d{2}\s*%|"
                      r"declared\s+to\s+have\s+passed")
ACADEMIC_DOMAIN = re.compile(r"\.(edu|ac\.[a-z]{2}|edu\.[a-z]{2}|ernet\.in|gov\.in|nic\.in)$")
AGGREGATORS = re.compile(r"shiksha|collegedunia|careers360|getmyuni|collegedekho|wikipedia|indiatoday|jagranjosh|"
                         r"facebook|linkedin|youtube|scribd|studocu|coursehero|google")


@dataclass
class PassingQuery:
    institute: str                       # awarding university / institute (public name)
    degree: str                          # e.g. "B.E.", "Bachelor of Engineering", "MBA"
    major: str = ""                      # branch / specialisation, e.g. "Civil Engineering"
    mode: str = "Full-time"              # Full-time | Part-time | Distance | Online
    duration_years: int | None = None    # e.g. 4
    regulation: str = ""                 # regulation / scheme as printed, e.g. "2017 (CBCS)"
    admission_year: str = ""             # optional, e.g. "2021"
    passing_year: str = ""               # optional, e.g. "2024"
    affiliated_college: bool = False     # studied at an affiliated college (not the university campus)
    official_website: str = ""           # if already known (e.g. from the UGC record)
    domain_hints: list[str] = field(default_factory=list)   # e.g. the university's e-mail domain

    def public_text(self) -> str:
        return " | ".join(str(x) for x in (self.institute, self.degree, self.major, self.mode, self.duration_years,
                                           self.regulation, self.admission_year, self.passing_year,
                                           self.official_website, *self.domain_hints) if x)


def mode_bucket(mode: str) -> str:
    m = (mode or "").lower()
    if re.search(r"distance|online|correspondence|open", m):
        return "DISTANCE"
    if re.search(r"part", m):
        return "PART-TIME"
    return "REGULAR"


def _kb() -> dict:
    return json.loads(KB.read_text()) if KB.exists() else {}


def _kb_put(key, val):
    d = _kb()
    d[key] = val
    KB.write_text(json.dumps(d, indent=2))


def degree_key(short: str, title: str) -> str:
    s = re.sub(r"[^A-Z]", "", (short or "").upper())
    t = (title or "").upper()
    if s in ("BE", "BTECH") or ("BACHELOR" in t and ("ENGINEERING" in t or "TECHNOLOGY" in t)):
        return "BE-BTECH"
    if s in ("ME", "MTECH") or ("MASTER" in t and ("ENGINEERING" in t or "TECHNOLOGY" in t)):
        return "ME-MTECH"
    if s in ("MBA", "PGDM") or "BUSINESS ADMINISTRATION" in t and "MASTER" in t:
        return "MBA"
    return s or re.sub(r"[^A-Z]", "", t)[:12]


def official_domains(ugc_website: str, mail_domains: list[str]) -> list[str]:
    out = []
    if ugc_website:
        out.append(registrable_domain(ugc_website))
    for d in mail_domains:
        rd = registrable_domain(d)
        if rd and rd not in FREE_MAIL and ACADEMIC_DOMAIN.search(rd) and rd not in out:
            out.append(rd)
    return [d for d in out if d and "helloverify" not in d]


def resolve_official_domain(q: PassingQuery) -> tuple[list[str], dict]:
    """Public lookup of the institute's official website when neither the UGC record nor an e-mail domain gives it.
    Accepted only if it is an academic domain and not an aggregator / directory site."""
    if not llm.available():
        return [], {}
    prompt = (f'What is the official website of the Indian higher-education institution "{q.institute}"? '
              f'Return ONLY JSON: {{"website": "<official URL>", "official_name": "<name>"}}.')
    data, meta = llm.web_search_json(prompt, None, "passing:official-website")
    site = registrable_domain(data.get("website") or "")
    if site and ACADEMIC_DOMAIN.search(site) and not AGGREGATORS.search(site):
        return [site], meta
    return [], {**meta, "rejected_website": data.get("website")}


def _on_domain(url: str, domains: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in domains)


def _download(url: str) -> Path:
    name = hashlib.sha1(url.encode()).hexdigest()[:16]
    content, ctype = sources.fetch(url, 60)
    ext = ".pdf" if ("pdf" in ctype or content[:5] == b"%PDF-") else ".html"
    p = DOCS / (name + ext)
    p.write_bytes(content)
    return p


def _norm_ws(s):
    return re.sub(r"\s+", " ", s or "").strip()


def heading_needles(heading: str) -> list[str]:
    """'7. 157 Passing/Promotion Criteria and eligibility …' → full core, then 8/6/4-word prefixes
    (leading clause numbers and footnote markers removed)."""
    core = re.sub(r"^\s*[\d.]+\s*", "", heading or "")
    core = re.sub(r"^\d+\s*", "", core).strip()          # footnote marker
    words = core.split()
    out = [core] if core else []
    for n in (8, 6, 4):
        if len(words) > n:
            out.append(" ".join(words[:n]))
    return [o for o in out if len(o) >= 8]


OCR_DPI = 150
MAX_SCAN_PAGES = 16


def _ocr_page_lines(path: Path, doc, i: int, cache: dict) -> list[dict]:
    """OCR (OpenAI vision, app/ocr.py) of one page of a SCANNED public regulation PDF. Boxes are synthetic
    (row order only) and converted to PDF points. Results are cached next to the PDF (<hash>.ocr.json) so a
    document is only read once."""
    key = str(i)
    if key not in cache:
        from .. import ocr
        from PIL import Image
        pix = doc[i].get_pixmap(dpi=OCR_DPI)
        im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples) if pix.n == 3 else \
            Image.frombytes("RGBA", (pix.width, pix.height), pix.samples).convert("RGB")
        k = 72 / OCR_DPI
        res = ocr.ocr(im, page=i)
        if res["error"]:
            raise RuntimeError(res["error"])
        cache[key] = [{**l, "box": [c * k for c in l["box"]]} for l in res["lines"]]
        path.with_suffix(".ocr.json").write_text(json.dumps(cache), encoding="utf-8")
    return cache[key]


def _locate_scanned(path: Path, heading: str, phrase: str, page_hint: int) -> dict | None:
    """Clause location for image-only PDFs: OCR the most likely pages first (search hint ± 3), stop at a strong
    heading match, then highlight the clause lines on the page image."""
    from .. import ocr
    doc = pymupdf.open(str(path))
    side = path.with_suffix(".ocr.json")
    cache = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
    needles = [n.lower() for n in heading_needles(heading)]
    ph = _norm_ws(phrase).lower()[:50]
    n = doc.page_count
    hint = (page_hint - 1) if page_hint and 0 < page_hint <= n else 0
    order = sorted(range(n), key=lambda i: (abs(i - hint) > 3, abs(i - hint), i))
    # pages already OCR-ed (cache) are free; at most MAX_SCAN_PAGES new pages are read per lookup (~7 s each)
    fresh = [i for i in order if str(i) not in cache][:MAX_SCAN_PAGES]
    order = [i for i in order if str(i) in cache or i in fresh]
    best = None
    for i in order:
        lines = _ocr_page_lines(path, doc, i, cache)
        t = _norm_ws(" ".join(l["text"] for l in lines)).lower()
        score = 0
        found = next((k for k, nd in enumerate(needles) if nd in t), None)
        if found is not None:
            score += 6 - min(found, 3)
        if ph and ph in t:
            score += 4
        score += min(3, len(PASS_PAT.findall(t)))
        if score and (best is None or score > best[0]):
            best = (score, i)
        if score >= 8:  # heading + phrase/pass wording found — no need to read the rest
            break
    if not best:
        return None
    i = best[1]
    page = doc[i]
    lines = sorted(_ocr_page_lines(path, doc, i, cache), key=lambda l: (l["box"][1], l["box"][0]))
    start = next((k for k, l in enumerate(lines) if any(nd[:30] in l["text"].lower() for nd in needles)), None)
    if start is None and ph:
        start = next((k for k, l in enumerate(lines) if ph[:25] in l["text"].lower()), None)
    if start is None:
        start = next((k for k, l in enumerate(lines) if PASS_PAT.search(l["text"])), 0)
    num = re.match(r"^\s*(\d+)", heading or "")
    clause = [lines[start]]
    for l in lines[start + 1:start + 40]:
        if num and re.match(rf"^\s*{int(num.group(1)) + 1}\s*[.)]\s*[A-Z]", l["text"]):
            break  # next top-level clause
        clause.append(l)
    # OCR boxes are row positions, not pixels → no highlight rectangles; show a generous band of the page
    # around the clause's estimated position and quote the clause text verbatim underneath.
    margin = 0.12 * page.rect.height
    y0 = max(0, clause[0]["box"][1] - margin)
    y1 = min(page.rect.height, max(l["box"][3] for l in clause) + margin)
    png = path.with_name(path.stem + f"_p{i + 1}.png")
    page.get_pixmap(dpi=150, clip=pymupdf.Rect(0, y0, page.rect.width, y1)).save(str(png))
    doc_text = _norm_ws(" ".join(l["text"] for k in cache for l in cache[k]))
    return {"page": i + 1, "pages": n, "clause_text": _norm_ws(ocr.rows_text(clause)), "png": str(png),
            "doc_text": doc_text, "ocr": True}


def _locate_pdf(path: Path, heading: str, phrase: str, page_hint: int) -> dict | None:
    doc = pymupdf.open(str(path))
    if sum(len(p.get_text().strip()) for p in doc) < 50 * max(1, min(doc.page_count, 5)):
        return _locate_scanned(path, heading, phrase, page_hint)   # image-only (scanned) regulation
    needles = heading_needles(heading)
    best = None
    for i, page in enumerate(doc):
        t = _norm_ws(page.get_text()).lower()
        score = 0
        found = next((k for k, n in enumerate(needles) if n.lower() in t), None)
        if found is not None:
            score += 6 - min(found, 3)  # longer heading match = stronger
        if phrase and _norm_ws(phrase).lower()[:60] in t:
            score += 4
        score += min(3, len(PASS_PAT.findall(t)))
        if page_hint and i + 1 == page_hint:
            score += 1
        if score and (best is None or score > best[0]):
            best = (score, i)
    if not best:
        return None
    page = doc[best[1]]
    W, Hh = page.rect.width, page.rect.height
    hits, head_core = [], ""
    for n in needles:
        hits = page.search_for(n)
        if hits:
            head_core = n
            break
    phrase_hits = page.search_for(phrase) if phrase else []
    if hits:
        y_start = hits[0].y0 - 8
    elif phrase_hits:
        y_start = phrase_hits[0].y0 - 40
    else:
        m = [b for b in page.get_text("blocks") if PASS_PAT.search(b[4])]
        y_start = (m[0][1] - 8) if m else 60
    # clause ends at the next top-level numbered heading (e.g. "15." on its own / "15. SOMETHING")
    y_end = min(Hh - 30, y_start + 320)
    for b in page.get_text("blocks"):
        if b[1] > y_start + 40 and re.match(r"^\s*\d{1,2}\.\s*(\n|[A-Z][A-Z ]{4,})", b[4]):
            y_end = min(y_end, b[1] - 4)
            break
    region = pymupdf.Rect(30, y_start, W - 30, y_end)
    clause_text = _norm_ws(page.get_text(clip=region))
    if head_core:  # drop running headers/page numbers before the heading
        i = clause_text.lower().find(head_core.lower())
        num = re.match(r"^\s*([\d.]+)", heading or "")
        if i > 0:
            j = clause_text.rfind(num.group(1).rstrip("."), 0, i) if num else -1
            clause_text = clause_text[j if 0 <= j < i else i:]
    # highlight: the located phrase, else every line in the clause with a percentage / "pass"
    marks = []
    num = re.match(r"^\s*(\d+)", heading or "")
    if hits and num:  # highlight the whole first sub-clause (14.1 …) up to "14.2"
        sub2 = [r for r in page.search_for(f"{num.group(1)}.2") if r.y0 > hits[0].y1 and r.x0 < W * 0.3]
        y_sub2 = sub2[0].y0 if sub2 else None
        if y_sub2:
            for b in page.get_text("dict")["blocks"]:
                for ln in b.get("lines", []):
                    r = pymupdf.Rect(ln["bbox"])
                    if r.y0 >= hits[0].y1 - 1 and r.y1 <= y_sub2 + 1 and r.x0 >= hits[0].x0 - 6:
                        marks.append(r)
    if not marks and phrase_hits:
        marks = phrase_hits
    if not marks:
        for b in page.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                txt = "".join(s["text"] for s in ln["spans"])
                r = pymupdf.Rect(ln["bbox"])
                if region.contains(r) and re.search(r"\d{2}\s*%|passed|pass ", txt, re.I):
                    marks.append(r)
    for h in hits[:1] + marks:
        a = page.add_highlight_annot(h)
        a.update()
    clip = pymupdf.Rect(0, max(0, y_start - 70), W, min(Hh, y_end + 50))
    png = path.with_name(path.stem + f"_p{best[1] + 1}.png")
    page.get_pixmap(dpi=150, clip=clip, annots=True).save(str(png))
    return {"page": best[1] + 1, "pages": doc.page_count, "clause_text": clause_text, "png": str(png),
            "doc_text": _norm_ws(" ".join(p.get_text() for p in doc))}


async def _locate_html(url: str, heading: str, phrase: str, out_png: Path) -> dict | None:
    ctx, page = await browser.new_page(width=1366, height=860)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(800)
        res = await page.evaluate("""([heading, phrase]) => {
            const needles=[phrase, heading].filter(Boolean).map(s=>s.toLowerCase().replace(/\\s+/g,' ').slice(0,80));
            const els=[...document.querySelectorAll('p,li,td,div,h1,h2,h3,h4,span')].filter(e=>e.children.length<6);
            for (const n of needles){ const el=els.find(e=>e.innerText && e.innerText.toLowerCase().replace(/\\s+/g,' ').includes(n));
              if(el){ el.style.background='#fff176'; el.scrollIntoView({block:'center'});
                const box=el.closest('section,article,div')||el; return {text:(box.innerText||'').slice(0,1500)}; } }
            return null; }""", [heading, phrase])
        await page.wait_for_timeout(200)
        await page.screenshot(path=str(out_png))
        body = await page.evaluate("document.body.innerText")
        if not res:
            return None
        return {"page": 0, "pages": 0, "clause_text": _norm_ws(res["text"]), "png": str(out_png),
                "doc_text": _norm_ws(body)}
    finally:
        await ctx.close()


def _core_clause(text: str, heading: str) -> str:
    """Heading + first sub-clause (e.g. 14. … 14.1 …) — stop before 14.2."""
    num = re.match(r"^\s*(\d+)", heading or "")
    if num:
        m = re.search(rf"\b{num.group(1)}\.2\b", text)
        if m and m.start() > 40:
            return text[:m.start()].strip()
    return text


def _numbers_verified(summary: str, doc_text: str) -> bool:
    nums = set(re.findall(r"\d{2}\s*%", summary or ""))
    if not nums:
        return bool(doc_text)
    dt = doc_text.replace(" %", "%")
    return all(n.replace(" ", "") in dt for n in nums)


def _local_doc(info: dict) -> Path | None:
    """Cached regulation file. Stored as a bare file name in data/knowledge/docs (portable across machines);
    older entries hold an absolute path — only their file name is used."""
    name = Path(str(info.get("local_file") or "").replace("\\", "/")).name
    p = DOCS / name if name else None
    return p if p and p.exists() else None


def _cache_key(q: PassingQuery, reg_year: str | None) -> str:
    # legacy keys (regular mode) stay valid: "<institute>|<degree>|<regulation year>"
    base = f"{sources.norm(q.institute)}|{degree_key(q.degree, q.degree)}"
    b = mode_bucket(q.mode)
    return f"{base}|{reg_year or ''}" if b == "REGULAR" else f"{base}|{b}|{reg_year or ''}"


def search_prompt(q: PassingQuery, domains: list[str], reg_year: str | None) -> str:
    dur = f"{q.duration_years}-year " if q.duration_years else ""
    return f"""Find the official academic regulations document published by {q.institute} on its own website
({', '.join(domains)}) that states the PASSING requirement (minimum marks / grade to pass a course and the
programme) for this programme:
- Degree: {q.degree}{f' in {q.major}' if q.major and q.major.lower() not in q.degree.lower() else ''}
- Study mode: {q.mode or 'Full-time'} ({dur}programme)
- Regulation / scheme: {q.regulation or 'unknown'}{f' (admission year {q.admission_year})' if q.admission_year else ''}
- Year of completion: {q.passing_year or 'unknown'}
- Studied at {'an affiliated college' if q.affiliated_college else 'the university / its own campus'}
Prefer the regulation matching the regulation year, degree and study mode (and the affiliated-college version if
applicable). Return ONLY JSON with keys: url (direct link to the document/page), document_title, regulation,
clause_heading (exact heading as printed e.g. "14. PASSING REQUIREMENTS"),
locate_phrase (an exact 6-12 word phrase copied verbatim from the clause text),
passing_criteria (1-2 sentences with the exact percentages/marks/grades), page_number (PDF page if known else 0)."""


async def run(q: PassingQuery, workdir: Path, out_pdf: Path, log=lambda m: None) -> dict:
    t0 = time.time()
    workdir.mkdir(parents=True, exist_ok=True)
    privacy.assert_public(q.public_text(), "passing:input")      # this service never needs personal data
    domains = official_domains(q.official_website, q.domain_hints)
    reg_year = (re.search(r"(19|20)\d{2}", q.regulation or "") or re.search(r"(19|20)\d{2}", q.admission_year or "")
                or re.search(r"(19|20)\d{2}", q.passing_year or "") or [None])[0]
    key = _cache_key(q, reg_year)
    meta, cached, loose = {}, False, False
    kb = _kb()
    info = kb.get(key)
    if not info and not re.search(r"(19|20)\d{2}", q.regulation or ""):
        # regulation unknown (not readable on the transcript) → same institute + degree + mode, newest first
        prefix = key.rsplit("|", 1)[0] + "|"
        cands = sorted((v for k, v in kb.items() if k.startswith(prefix)), key=lambda v: v.get("created", ""),
                       reverse=True)
        info, loose = (cands[0], True) if cands else (None, False)
    if info and _local_doc(info):
        cached = True
        log(f"knowledge cache hit ({key}{' — regulation not confirmed, nearest entry used' if loose else ''}) "
            f"— no search needed")
    else:
        info = None
        if not llm.available():
            return {"found": False, "reason": "no cached regulation and OpenAI research is disabled",
                    "query": asdict(q), "seconds": round(time.time() - t0, 1)}
        if not domains:
            log(f"official website of {q.institute} unknown — looking it up")
            domains, m0 = await asyncio.to_thread(resolve_official_domain, q)
            meta = {**m0}
            if not domains:
                return {"found": False, "reason": "official institute website could not be established "
                                                  f"({m0.get('rejected_website') or 'no academic domain found'})",
                        "query": asdict(q), "meta": meta, "seconds": round(time.time() - t0, 1)}
        prompt = search_prompt(q, domains, reg_year)
        log(f"searching official domain(s) {', '.join(domains)} for {q.degree} {q.major} ({q.mode}) "
            f"regulation {q.regulation or reg_year or '?'}")
        found, m1 = await asyncio.to_thread(llm.web_search_json, prompt, domains, "passing:regulation-search")
        meta = {**m1, "usd": round(m1.get("usd", 0) + meta.get("usd", 0), 5)}
        url = (found.get("url") or "").strip()
        log(f"search answered in {m1.get('seconds')}s → {unquote(url)[:120]}")
        if not url or not _on_domain(url, domains):
            return {"found": False, "reason": f"search returned a non-official source {url!r}", "meta": meta,
                    "query": asdict(q), "seconds": round(time.time() - t0, 1)}
        local = await asyncio.to_thread(_download, url)
        info = {**found, "url": url, "local_file": local.name, "domains": domains, "mode": q.mode,
                "major_searched": q.major, "created": datetime.now().isoformat(timespec="seconds")}

    local = _local_doc(info)
    if local.suffix == ".pdf":
        loc = await asyncio.to_thread(_locate_pdf, local, info.get("clause_heading", ""),
                                      info.get("locate_phrase", ""), int(info.get("page_number") or 0))
    else:
        loc = await _locate_html(info["url"], info.get("clause_heading", ""), info.get("locate_phrase", ""),
                                 workdir / "passing_page.png")
    if not loc:
        return {"found": False, "reason": "clause not located in the official document", "url": info["url"],
                "meta": meta, "query": asdict(q), "seconds": round(time.time() - t0, 1)}

    verified = _numbers_verified(info.get("passing_criteria", ""), loc["clause_text"] or loc["doc_text"]) and not loose
    if not cached and verified:
        _kb_put(key, info)
    doms = info.get("domains", domains)
    title = unquote(Path(urlparse(info["url"]).path).name) or info.get("document_title", "")
    frame = render.browser_frame(info["url"], render.data_url(loc["png"]), "pdf" if loc["pages"] else "web",
                                 (info.get("document_title") or title)[:70],
                                 f"{loc['page']} / {loc['pages']}" if loc["pages"] else "",
                                 (heading_needles(info.get("clause_heading", "")) or [""])[-1][:40])
    programme = ", ".join(x for x in (f"{q.degree}{f' in {q.major}' if q.major else ''}", q.mode,
                                      f"{q.duration_years} years" if q.duration_years else "") if x)
    src = [{"name": "Official institute website (search restricted to)", "url": "https://" + doms[0] if doms else "",
            "found": bool(doms), "result": ", ".join(doms)},
           {"name": info.get("document_title") or "Regulation document", "url": info["url"], "found": True,
            "result": f"Clause '{info.get('clause_heading', '')}'" + (f" on page {loc['page']}" if loc["page"] else "")
                      + (" — numbers confirmed in the text" if verified else " — numbers NOT confirmed")}]
    html = render.evidence_html(
        [("Passing Criteria", info.get("passing_criteria", "")), ("University / Institute", q.institute),
         ("Programme searched", programme), ("Regulation", info.get("regulation") or info.get("document_title", "")),
         ("Link", info["url"])],
        [{"heading": info.get("clause_heading", "Passing requirements"), "frame_html": frame,
          "quote": _core_clause(loc["clause_text"], info.get("clause_heading", ""))[:1600],
          "caption": (f"Verbatim text of the clause from the official document (page {loc['page']})."
                      if loc["page"] else "Verbatim text from the official page.")
                     + (" Scanned page: the text was read by OCR, so the clause is quoted here instead of being"
                        " highlighted on the image." if loc.get("ocr") else "")}],
        f"Captured {datetime.now().strftime('%d-%m-%Y %H:%M:%S')} by HV Closure Engine from the official domain "
        f"({', '.join(doms)}). Highlight marks the passing clause. Searched with general programme information only "
        f"(no candidate data).", sources=src, title="Passing criteria")
    await browser.html_to_pdf(html, str(out_pdf), a4=True)
    return {"found": True, "verified": verified, "cached": cached, "loose": loose, "url": info["url"],
            "document_title": info.get("document_title", ""), "regulation": info.get("regulation", ""),
            "clause_heading": info.get("clause_heading", ""), "criteria": info.get("passing_criteria", ""),
            "clause_text": loc["clause_text"], "page": loc["page"], "pdf": str(out_pdf), "meta": meta,
            "domains": doms, "sources": src, "query": asdict(q), "seconds": round(time.time() - t0, 1)}
