"""Passing criteria research — only the university's own domain is an authentic source.

1. Knowledge cache (university + programme + regulation) → instant, $0
2. else OpenAI web_search locked to the official domain → URL of the regulation document
3. download it, locate the clause, highlight it, extract the verbatim text
4. verify the numbers the model reported are really in the document (otherwise flag)"""
import asyncio
import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import pymupdf

from .. import config, llm
from ..evidence import browser, render
from ..extract.mail import FREE_MAIL, registrable_domain
from . import sources

KB = config.KNOWLEDGE / "passing.json"
DOCS = config.KNOWLEDGE / "docs"
DOCS.mkdir(parents=True, exist_ok=True)
PASS_PAT = re.compile(r"(?i)pass(ing)?\s+(requirements?|criteria|minimum|marks)|minimum\s+(of\s+)?\d{2}\s*%|"
                      r"declared\s+to\s+have\s+passed")


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
    return s or re.sub(r"[^A-Z]", "", t)[:12]


def official_domains(ugc_website: str, mail_domains: list[str]) -> list[str]:
    out = []
    if ugc_website:
        out.append(registrable_domain(ugc_website))
    for d in mail_domains:
        rd = registrable_domain(d)
        if rd and rd not in FREE_MAIL and re.search(r"\.(edu|ac\.[a-z]{2}|edu\.[a-z]{2})$", rd) and rd not in out:
            out.append(rd)
    return [d for d in out if d and "helloverify" not in d]


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


def _locate_pdf(path: Path, heading: str, phrase: str, page_hint: int) -> dict | None:
    doc = pymupdf.open(str(path))
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


async def run(university: str, ugc_website: str, mail_domains: list[str], degree_short: str, degree_title: str,
              regulation: str, year: str, affiliated: bool, workdir: Path, out_pdf: Path, log) -> dict:
    t0 = time.time()
    domains = official_domains(ugc_website, mail_domains)
    reg_year = (re.search(r"(19|20)\d{2}", regulation or "") or re.search(r"(19|20)\d{2}", year or "") or [None])[0]
    key = f"{sources.norm(university)}|{degree_key(degree_short, degree_title)}|{reg_year or ''}"
    meta, cached, loose = {}, False, False
    kb = _kb()
    info = kb.get(key)
    if not info and not re.search(r"(19|20)\d{2}", regulation or ""):
        # regulation unknown (e.g. offline OCR could not read it) → same university + programme, newest first
        prefix = key.rsplit("|", 1)[0] + "|"
        cands = sorted((v for k, v in kb.items() if k.startswith(prefix)), key=lambda v: v.get("created", ""), reverse=True)
        info, loose = (cands[0], True) if cands else (None, False)
    if info and Path(info.get("local_file", "")).exists():
        cached = True
        log(f"knowledge cache hit ({key}{' — regulation not confirmed, nearest entry used' if loose else ''}) — no search needed")
    else:
        if not domains:
            return {"found": False, "reason": "official university domain unknown", "seconds": round(time.time() - t0, 1)}
        if not llm.available():
            return {"found": False, "reason": "no cached regulation and no LLM key for search",
                    "seconds": round(time.time() - t0, 1)}
        log(f"searching official domain(s) {', '.join(domains)} for {degree_short or degree_title} "
            f"regulation {regulation or reg_year or ''}")
        prompt = f"""Find the official academic regulations document published by {university} on its own website
({', '.join(domains)}) that states the PASSING requirement (minimum marks to pass a course) for this programme.
Programme: {degree_title} ({degree_short}). Candidate's regulation/scheme: {regulation or 'unknown'}.
Year of passing: {year}. Studied at {'an affiliated college' if affiliated else 'the university'}.
Prefer the regulation matching the candidate's regulation year and programme (and affiliated-college version if applicable).
Return ONLY JSON with keys: url (direct link to the document/page), document_title, regulation,
clause_heading (exact heading as printed e.g. "14. PASSING REQUIREMENTS"),
locate_phrase (an exact 6-12 word phrase copied verbatim from the clause text),
passing_criteria (1-2 sentences with the exact percentages/marks), page_number (PDF page if known else 0)."""
        found, meta = await asyncio.to_thread(llm.web_search_json, prompt, domains)
        url = (found.get("url") or "").strip()
        log(f"search answered in {meta.get('seconds')}s → {unquote(url)[:120]}")
        if not url or not _on_domain(url, domains):
            return {"found": False, "reason": f"search returned non-official source {url!r}", "meta": meta,
                    "seconds": round(time.time() - t0, 1)}
        local = await asyncio.to_thread(_download, url)
        info = {**found, "url": url, "local_file": str(local), "domains": domains,
                "created": datetime.now().isoformat(timespec="seconds")}

    local = Path(info["local_file"])
    if local.suffix == ".pdf":
        loc = await asyncio.to_thread(_locate_pdf, local, info.get("clause_heading", ""),
                                      info.get("locate_phrase", ""), int(info.get("page_number") or 0))
    else:
        loc = await _locate_html(info["url"], info.get("clause_heading", ""), info.get("locate_phrase", ""),
                                 workdir / "passing_page.png")
    if not loc:
        return {"found": False, "reason": "clause not located in the official document", "url": info["url"],
                "meta": meta, "seconds": round(time.time() - t0, 1)}

    verified = _numbers_verified(info.get("passing_criteria", ""), loc["clause_text"] or loc["doc_text"]) and not loose
    if not cached and verified:
        _kb_put(key, info)
    title = unquote(Path(urlparse(info["url"]).path).name) or info.get("document_title", "")
    frame = render.browser_frame(info["url"], render.data_url(loc["png"]), "pdf" if loc["pages"] else "web",
                                 (info.get("document_title") or title)[:70],
                                 f"{loc['page']} / {loc['pages']}" if loc["pages"] else "",
                                 (heading_needles(info.get("clause_heading", "")) or [""])[-1][:40])
    html = render.evidence_html(
        [("Passing Criteria", info.get("passing_criteria", "")), ("University", university),
         ("Regulation", info.get("regulation") or info.get("document_title", "")), ("Link", info["url"])],
        [{"heading": info.get("clause_heading", "Passing requirements"), "frame_html": frame,
          "quote": _core_clause(loc["clause_text"], info.get("clause_heading", ""))[:1600],
          "caption": f"Verbatim text of the clause from the official document (page {loc['page']})."
          if loc["page"] else "Verbatim text from the official page."}],
        f"Captured {datetime.now().strftime('%d-%m-%Y %H:%M:%S')} by HV Closure Engine from the official domain "
        f"({', '.join(info.get('domains', domains))}). Highlight marks the passing clause.")
    await browser.html_to_pdf(html, str(out_pdf), a4=True)
    return {"found": True, "verified": verified, "cached": cached, "loose": loose, "url": info["url"],
            "document_title": info.get("document_title", ""), "regulation": info.get("regulation", ""),
            "clause_heading": info.get("clause_heading", ""), "criteria": info.get("passing_criteria", ""),
            "clause_text": loc["clause_text"], "page": loc["page"], "pdf": str(out_pdf), "meta": meta,
            "domains": info.get("domains", domains), "seconds": round(time.time() - t0, 1)}
