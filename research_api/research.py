"""HV Research API: accreditation and passing-criteria research in one self-contained module.

It does not depend on the `app/` package, so it can be lifted into any service and exposed as HTTP endpoints.

    Function (async)              Sync wrapper                     Suggested endpoint
    ----------------------------  -------------------------------  ---------------------------------------
    check_accreditation(req)      check_accreditation_sync(req)    POST /research/accreditation
    find_passing_criteria(req)    find_passing_criteria_sync(req)  POST /research/passing-criteria
    research(req)                 research_sync(req)               POST /research   (both, chained)
    health()                      -                                GET  /research/health

Sources (only authentic ones are accepted):
  * Accreditation: UGC university lists (JSON behind ugc.gov.in) and the AICTE 2025-26 approved-institutions PDF.
    Both are downloaded once, cached locally and matched with fuzzy name matching. No OpenAI cost.
  * Passing criteria: the knowledge cache first, at no cost. Otherwise an OpenAI `web_search` call restricted
    to the university's OWN domain finds the regulation document. The document is downloaded, the clause is
    located and its verbatim text extracted, and every percentage the model reported is checked against the
    document text (`verified`).

Configuration (environment variables; a `.env` in this folder or in its parent folder is loaded if
python-dotenv is installed):
    OPENAI_API_KEY        required for passing-criteria search (a cache hit needs no key)
    HV_SEARCH_MODEL       default gpt-5.4-mini
    HV_DISABLE_LLM=1      never call OpenAI (cache only)
    HV_RESEARCH_DATA      cache directory, default <this folder>/data

CLI:
    python research.py accreditation    payload.json
    python research.py passing-criteria payload.json
    python research.py research         payload.json
    python research.py serve [--port 8100]          # starts the FastAPI app from create_app()
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import html as html_lib
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import unquote, urlparse

import httpx
import pymupdf
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

# ════════════════════════════════════════════════════════════════════════════════════════════════════════════
# Configuration
# ════════════════════════════════════════════════════════════════════════════════════════════════════════════
HERE = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv

    load_dotenv(HERE / ".env")
    load_dotenv(HERE.parent / ".env")
except ImportError:
    pass

VERSION = "1.0.0"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
SEARCH_MODEL = os.getenv("HV_SEARCH_MODEL", "gpt-5.4-mini")
USE_LLM = bool(OPENAI_API_KEY) and os.getenv("HV_DISABLE_LLM", "") != "1"

DATA = Path(os.getenv("HV_RESEARCH_DATA", HERE / "data"))
SOURCES = DATA / "sources"
KNOWLEDGE = DATA / "knowledge"
DOCS = KNOWLEDGE / "docs"
KB_FILE = KNOWLEDGE / "passing.json"
for _p in (SOURCES, DOCS):
    _p.mkdir(parents=True, exist_ok=True)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
UGC_TYPES = {  # unitypeID -> (label, public page token)
    1: ("Central University", "ddmCMsxJZgXH2S/m0uMOKQ=="),
    2: ("State University", "LZ1FUMk6U2JWGNLvhWfVSA=="),
    3: ("State Private University", "0wBmFB1Rb4JGVzq9UP/iOg=="),
    4: ("Deemed to be University", "UCL6fMspL2LJS89kv++N3A=="),
}
UGC_PAGE = "https://www.ugc.gov.in/universitydetails/university?type={token}"
UGC_API = "https://www.ugc.gov.in/universitydetails/Getuniversity_details?unitypeID={t}"
AICTE_LIST = ("https://aicte.gov.in/sites/default/files/approval/2025-26/"
              "Groupwise-List%20of%20Institutions_compressed.pdf")
AICTE_YEAR = "2026"  # approval session 2025-26
SOURCE_MAX_AGE_DAYS = 7

# USD per 1M tokens (input, output). Approximate list prices, used only for cost reporting.
PRICES = {"gpt-4.1-mini": (0.40, 1.60), "gpt-5.4-mini": (0.75, 4.50), "gpt-4o-mini": (0.15, 0.60)}
WEB_SEARCH_CALL_USD = 0.01
FREE_MAIL = ("gmail.com", "yahoo.com", "yahoo.co.in", "hotmail.com", "outlook.com", "live.com", "rediffmail.com",
             "icloud.com", "aol.com", "protonmail.com", "ymail.com")


# ════════════════════════════════════════════════════════════════════════════════════════════════════════════
# API contract: request and response models
# ════════════════════════════════════════════════════════════════════════════════════════════════════════════
class Evidence(BaseModel):
    """A highlighted image of the source record. Returned only when the request sets include_evidence=true."""
    kind: Literal["aicte_row", "passing_clause"]
    title: str
    source_url: str
    page: int = 0
    mime: str = "image/png"
    data_base64: str


class LLMUsage(BaseModel):
    model: str
    seconds: float
    usd: float
    input_tokens: int = 0
    output_tokens: int = 0
    searches: int = 0


# ---------- accreditation ----------
class AccreditationRequest(BaseModel):
    university: str = Field(..., min_length=2, description="University name as printed, e.g. 'Anna University, Chennai'")
    college: str = Field("", description="Affiliated college, optionally with a district hint: 'XYZ College [Salem]'")
    degree: str = Field("", description="Degree text, e.g. 'B.E. Mechanical Engineering'. Used to decide AICTE vs UGC")
    include_evidence: bool = Field(False, description="Return highlighted AICTE row images (base64 PNG)")

    model_config = {"json_schema_extra": {"examples": [
        {"university": "Anna University, Chennai", "college": "", "degree": "B.E. Mechanical Engineering"}]}}


class UGCMatch(BaseModel):
    name: str
    type: str
    status: str = ""
    website: str = ""
    address: str = ""
    state: str = ""
    page_url: str
    score: float


class AICTEMatch(BaseModel):
    sr: str
    aicte_id: str
    name: str
    region: str = ""
    state: str = ""
    district: str = ""
    city: str = ""
    group: str = ""
    page: int
    score: float
    list_url: str


class AccreditationResponse(BaseModel):
    status: Literal["Accredited", "Non-Accredited"]
    body: str = Field(..., description="Full name of the accreditation body, or 'NOT DISCLOSED'")
    body_short: Literal["UGC", "AICTE", ""] = ""
    url: str = Field("", description="Official list the record was found in")
    year: str = ""
    country: str = ""
    technical: bool = Field(..., description="Degree/college looks technical (engineering, MBA, MCA...), so AICTE is preferred")
    canonical_university: str = Field(..., description="Name as written in the official list. Feed this to passing-criteria")
    summary: str
    ugc: Optional[UGCMatch] = None
    aicte_university: Optional[AICTEMatch] = None
    aicte_college: Optional[AICTEMatch] = None
    evidence: list[Evidence] = []
    warnings: list[str] = []
    seconds: float


# ---------- passing criteria ----------
class PassingCriteriaRequest(BaseModel):
    university: str = Field(..., min_length=2, description="Prefer AccreditationResponse.canonical_university")
    degree_title: str = Field(..., min_length=1, description="e.g. 'Bachelor of Engineering'")
    degree_short: str = Field("", description="e.g. 'B.E.'")
    regulation: str = Field("", description="Regulation/scheme printed on the transcript, e.g. 'R2017'")
    year_of_passing: str = Field("", description="e.g. '2021' or 'May 2021'")
    affiliated: bool = Field(False, description="Candidate studied at an affiliated college")
    official_domains: list[str] = Field([], description="Known official domains, e.g. ['annauniv.edu']")
    university_website: str = Field("", description="Website from the UGC list (AccreditationResponse.ugc.website)")
    mail_domains: list[str] = Field([], description="Domains of university e-mails (only .edu / .ac.xx are trusted)")
    use_cache: bool = Field(True, description="Use the knowledge cache before searching")
    include_evidence: bool = Field(False, description="Return the highlighted clause image (base64 PNG, PDF sources only)")

    model_config = {"json_schema_extra": {"examples": [
        {"university": "Anna University", "degree_title": "Bachelor of Engineering", "degree_short": "B.E.",
         "regulation": "2017", "year_of_passing": "2021", "affiliated": True,
         "university_website": "https://www.annauniv.edu"}]}}


class PassingCriteriaResponse(BaseModel):
    found: bool
    verified: bool = Field(False, description="Every percentage in `criteria` occurs in the official document")
    cached: bool = False
    loose_match: bool = Field(False, description="Regulation year unknown, so the newest cached entry was used")
    reason: str = Field("", description="Why nothing was found (when found=false)")
    url: str = ""
    document_title: str = ""
    regulation: str = ""
    clause_heading: str = ""
    criteria: str = Field("", description="1-2 sentence passing requirement with the exact percentages")
    clause_text: str = Field("", description="Verbatim clause text extracted from the document")
    page: int = 0
    pages: int = 0
    domains: list[str] = []
    evidence: list[Evidence] = []
    llm: Optional[LLMUsage] = None
    seconds: float


# ---------- combined ----------
class ResearchRequest(BaseModel):
    university: str = Field(..., min_length=2)
    college: str = ""
    degree_title: str = Field(..., min_length=1)
    degree_short: str = ""
    regulation: str = ""
    year_of_passing: str = ""
    affiliated: Optional[bool] = Field(None, description="Defaults to true when `college` is given")
    official_domains: list[str] = []
    mail_domains: list[str] = []
    use_cache: bool = True
    include_evidence: bool = False

    model_config = {"json_schema_extra": {"examples": [
        {"university": "Anna University, Chennai", "college": "", "degree_title": "Bachelor of Engineering",
         "degree_short": "B.E.", "regulation": "2017", "year_of_passing": "2021", "affiliated": True}]}}


class ResearchResponse(BaseModel):
    accreditation: AccreditationResponse
    passing: PassingCriteriaResponse
    total_usd: float
    seconds: float


class HealthResponse(BaseModel):
    version: str
    llm_enabled: bool
    search_model: str
    ugc_cached: bool
    aicte_cached: bool
    knowledge_entries: int
    data_dir: str


# ════════════════════════════════════════════════════════════════════════════════════════════════════════════
# Shared helpers
# ════════════════════════════════════════════════════════════════════════════════════════════════════════════
_lock = threading.Lock()
_kb_lock = threading.Lock()
_mem: dict = {}
_client = None


def _fresh(p: Path) -> bool:
    return p.exists() and (time.time() - p.stat().st_mtime) < SOURCE_MAX_AGE_DAYS * 86400


def fetch(url: str, timeout=60, headers: dict | None = None) -> tuple[bytes, str]:
    """GET with fallbacks: strict TLS, then relaxed TLS (some .ac.in certificates are broken), then curl."""
    h = {"User-Agent": UA, **(headers or {})}
    last = None
    for verify in (True, False):
        try:
            with httpx.Client(headers=h, follow_redirects=True, timeout=timeout, verify=verify) as c:
                r = c.get(url)
                r.raise_for_status()
                return r.content, r.headers.get("content-type", "")
        except httpx.HTTPStatusError:
            raise
        except Exception as e:  # TLS / timeout: try the next strategy
            last = e
    r = subprocess.run(["curl", "-sSL", "-m", str(timeout), "-A", UA, url], capture_output=True)
    if r.returncode == 0 and r.stdout:
        return r.stdout, ""
    raise RuntimeError(f"download failed for {url}: {last}")


def norm(name: str) -> str:
    s = (name or "").upper().replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    s = re.sub(r"\b(THE)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def registrable_domain(host: str) -> str:
    host = (host or "").lower().strip().strip(".")
    host = re.sub(r"^https?://", "", host).split("/")[0].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    if "@" in host:
        host = host.split("@")[-1]
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("ac", "edu", "co", "gov", "org", "net", "res", "nic") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _png_b64(path_or_bytes) -> str:
    data = path_or_bytes if isinstance(path_or_bytes, bytes) else Path(path_or_bytes).read_bytes()
    return base64.b64encode(data).decode()


# ════════════════════════════════════════════════════════════════════════════════════════════════════════════
# Official accreditation sources (downloaded once, refreshed weekly)
# ════════════════════════════════════════════════════════════════════════════════════════════════════════════
def ugc_lists() -> dict[int, list[dict]]:
    with _lock:
        if "ugc" in _mem:
            return _mem["ugc"]
        out = {}
        for t in UGC_TYPES:
            p = SOURCES / f"ugc_{t}.json"
            if not _fresh(p):
                try:
                    raw, _ = fetch(UGC_API.format(t=t), 40, {"X-Requested-With": "XMLHttpRequest"})
                    data = json.loads(raw)
                    if data.get("List"):
                        p.write_text(json.dumps(data["List"]), encoding="utf-8")
                except Exception:
                    pass  # stale cache (if any) is used
            out[t] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
        _mem["ugc"] = out
        return out


# AICTE column x0 boundaries (verified on the 2025-26 PDF)
_AICTE_COLS = [("sr", 0, 45), ("aicte_id", 45, 110), ("name", 110, 275), ("region", 275, 328),
               ("state", 328, 390), ("district", 390, 458), ("city", 458, 525), ("group", 525, 9999)]


def aicte_pdf() -> Path:
    p = SOURCES / "aicte_groupwise_2025_26.pdf"
    if not _fresh(p) or p.stat().st_size < 100000:
        try:
            data, _ = fetch(AICTE_LIST, 120)
            p.write_bytes(data)
        except Exception:
            if not p.exists():
                raise
    return p


def aicte_index() -> list[dict]:
    with _lock:
        if "aicte" in _mem:
            return _mem["aicte"]
        pdf = aicte_pdf()
        idx_p = SOURCES / "aicte_index.json"
        if idx_p.exists() and idx_p.stat().st_mtime >= pdf.stat().st_mtime:
            rows = json.loads(idx_p.read_text(encoding="utf-8"))
        else:
            rows = []
            doc = pymupdf.open(str(pdf))
            for pno, page in enumerate(doc):
                words = page.get_text("words")
                # Row anchors are the Sr.No cells. Every other word joins the vertically nearest anchor.
                anchors = sorted(((w[1] + w[3]) / 2, w) for w in words if w[0] < 45 and w[4].isdigit())
                if not anchors:
                    continue
                groups = {id(a[1]): [a[1]] for a in anchors}
                ys = [a[0] for a in anchors]
                for w in words:
                    if w[0] < 45 and w[4].isdigit():
                        continue
                    ym = (w[1] + w[3]) / 2
                    if ym < ys[0] - 14 or ym > ys[-1] + 14:
                        continue
                    i = min(range(len(ys)), key=lambda k: abs(ys[k] - ym))
                    groups[id(anchors[i][1])].append(w)
                for ws in groups.values():
                    cells = {k: [] for k, _, _ in _AICTE_COLS}
                    for w in ws:
                        for k, lo, hi in _AICTE_COLS:
                            if lo <= w[0] < hi:
                                cells[k].append(w[4])
                                break
                    sr = " ".join(cells["sr"])
                    if not sr.isdigit() or not cells["name"]:
                        continue
                    bbox = [min(w[0] for w in ws), min(w[1] for w in ws), max(w[2] for w in ws), max(w[3] for w in ws)]
                    row = {k: " ".join(v) for k, v in cells.items()}
                    row.update(page=pno + 1, bbox=bbox, norm=norm(row["name"]))
                    rows.append(row)
            idx_p.write_text(json.dumps(rows), encoding="utf-8")
        _mem["aicte"] = rows
        return rows


def warm_sources() -> None:
    """Pre-load UGC + AICTE (call once at service start, e.g. in a background thread)."""
    for fn in (ugc_lists, aicte_index):
        try:
            fn()
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════════════════════════════════════════════════
# Accreditation
# ════════════════════════════════════════════════════════════════════════════════════════════════════════════
_TECH_RE = re.compile(r"\b(B\.?\s?E\b|B\.?\s?TECH|M\.?\s?E\b|M\.?\s?TECH|ENGINEERING|TECHNOLOGY|MBA|MCA|PHARM|"
                      r"ARCHITECTURE|B\.?\s?ARCH|POLYTECHNIC|HOTEL MANAGEMENT|PGDM|APPLIED ARTS)", re.I)


def name_variants(name: str) -> list[str]:
    name = re.sub(r"\[.*?\]", " ", name or "")
    name = re.sub(r"\s+-\s+(INDIA|India)\b.*$", "", name)
    out = {name.strip(), re.split(r",", name)[0].strip(), re.sub(r"\s+-\s+\d{6}$", "", name).strip()}
    return sorted((v for v in out if len(v) > 3), key=len, reverse=True)


def is_technical(*texts: str) -> bool:
    return any(_TECH_RE.search(t or "") for t in texts)


def match_ugc(name: str) -> dict | None:
    variants = [norm(v) for v in name_variants(name)]
    if not variants:
        return None
    best = None
    for t, lst in ugc_lists().items():
        for rec in lst:
            n = norm(rec.get("uni_name", ""))
            score = 100 if n in variants else max(fuzz.ratio(n, v) for v in variants)
            if score >= 92 and (best is None or score > best["score"]):
                best = {"score": score, "type": t, "record": rec}
    return best


def match_aicte(name: str, district_hint: str = "") -> dict | None:
    variants = [norm(v) for v in name_variants(name)]
    if not variants:
        return None
    best = None
    for row in aicte_index():
        score = 100 if row["norm"] in variants else max(fuzz.ratio(row["norm"], v) for v in variants)
        if score < 93:
            continue
        if district_hint and district_hint.upper() in (row["district"] + " " + row["city"]).upper():
            score += 5
        if best is None or score > best["score"]:
            best = {"score": score, "row": row}
    return best


def _aicte_row_png(row: dict) -> bytes:
    doc = pymupdf.open(str(aicte_pdf()))
    page = doc[row["page"] - 1]
    x0, y0, x1, y1 = row["bbox"]
    annot = page.add_rect_annot(pymupdf.Rect(x0 - 2, y0 - 2, x1 + 2, y1 + 2))
    annot.set_colors(stroke=(0.85, 0.1, 0.1), fill=(1.0, 0.92, 0.2))
    annot.set_border(width=1.2)
    annot.set_opacity(0.5)
    annot.update()
    top = max(0, y0 - 230)
    clip = pymupdf.Rect(0, top, page.rect.width, min(page.rect.height, top + 470))
    return page.get_pixmap(dpi=150, clip=clip, annots=True).tobytes("png")


def _ugc_model(hit: dict) -> UGCMatch:
    rec = hit["record"]
    return UGCMatch(name=rec.get("uni_name", ""), type=UGC_TYPES[hit["type"]][0], status=str(rec.get("status") or ""),
                    website=str(rec.get("url") or ""),
                    address=_ws(f"{rec.get('address') or ''} {rec.get('Zip') or ''}"),
                    state=_ws(rec.get("state") or ""), page_url=UGC_PAGE.format(token=UGC_TYPES[hit["type"]][1]),
                    score=hit["score"])


def _aicte_model(hit: dict) -> AICTEMatch:
    r = hit["row"]
    return AICTEMatch(sr=r["sr"], aicte_id=r["aicte_id"], name=r["name"], region=r["region"], state=r["state"],
                      district=r["district"], city=r["city"], group=r["group"], page=r["page"], score=hit["score"],
                      list_url=f"{AICTE_LIST}#page={r['page']}")


async def check_accreditation(req: AccreditationRequest) -> AccreditationResponse:
    """Is the university/college recognised by UGC or AICTE? Local matching only, no LLM."""
    t0 = time.time()
    technical = is_technical(req.degree, req.college)
    m = re.search(r"\[(.*?)\]", req.college or "")
    district = m.group(1) if m else ""
    warnings: list[str] = []

    async def safe(fn, *a):
        try:
            return await asyncio.to_thread(fn, *a)
        except Exception as e:
            warnings.append(f"{fn.__name__}: {e}")
            return None

    ugc, a_uni, a_col = await asyncio.gather(
        safe(match_ugc, req.university),
        safe(match_aicte, req.university),
        safe(match_aicte, req.college, district) if req.college else asyncio.sleep(0, None),
    )
    aicte_hit = bool(a_uni or a_col)
    year = str(datetime.now().year)
    if technical and aicte_hit:
        body, short, url, year = "All India Council for Technical Education", "AICTE", AICTE_LIST, AICTE_YEAR
    elif ugc:
        body, short, url = "University Grants Commission", "UGC", UGC_PAGE.format(token=UGC_TYPES[ugc["type"]][1])
    elif aicte_hit:
        body, short, url, year = "All India Council for Technical Education", "AICTE", AICTE_LIST, AICTE_YEAR
    else:
        body, short, url, year = "", "", "", ""

    evidence: list[Evidence] = []
    if req.include_evidence:
        for label, hit in (("University", a_uni), ("Affiliated college", a_col)):
            if hit:
                try:
                    png = await asyncio.to_thread(_aicte_row_png, hit["row"])
                    evidence.append(Evidence(kind="aicte_row", title=f"AICTE approved institutions 2025-26: {label}",
                                             source_url=f"{AICTE_LIST}#page={hit['row']['page']}",
                                             page=hit["row"]["page"], data_base64=_png_b64(png)))
                except Exception as e:
                    warnings.append(f"evidence: {e}")

    canonical = (ugc["record"]["uni_name"] if ugc else (a_uni["row"]["name"].title() if a_uni else req.university))
    return AccreditationResponse(
        status="Accredited" if body else "Non-Accredited", body=body or "NOT DISCLOSED", body_short=short, url=url,
        year=year, country="India" if body else "", technical=technical, canonical_university=canonical,
        summary=f"{'Found' if ugc else 'Not found'} in UGC, {'Found' if aicte_hit else 'Not found'} in AICTE",
        ugc=_ugc_model(ugc) if ugc else None, aicte_university=_aicte_model(a_uni) if a_uni else None,
        aicte_college=_aicte_model(a_col) if a_col else None, evidence=evidence, warnings=warnings,
        seconds=round(time.time() - t0, 2))


# ════════════════════════════════════════════════════════════════════════════════════════════════════════════
# OpenAI: web search restricted to the official domain(s)
# ════════════════════════════════════════════════════════════════════════════════════════════════════════════
def _openai():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=OPENAI_API_KEY, timeout=120)
    return _client


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


def web_search_json(prompt: str, allowed_domains: list[str], model: str | None = None) -> tuple[dict, LLMUsage]:
    model = model or SEARCH_MODEL
    t = time.time()
    r = _openai().responses.create(
        model=model,
        tools=[{"type": "web_search", "filters": {"allowed_domains": allowed_domains}}],
        reasoning={"effort": "low"},
        input=prompt,
    )
    n_search = sum(1 for o in r.output if getattr(o, "type", "") == "web_search_call")
    pi, po = PRICES.get(model, (1.0, 4.0))
    it = getattr(r.usage, "input_tokens", 0) or 0
    ot = getattr(r.usage, "output_tokens", 0) or 0
    usd = round(it / 1e6 * pi + ot / 1e6 * po + n_search * WEB_SEARCH_CALL_USD, 5)
    return _parse_json(r.output_text), LLMUsage(model=model, seconds=round(time.time() - t, 1), usd=usd,
                                                input_tokens=it, output_tokens=ot, searches=n_search)


# ════════════════════════════════════════════════════════════════════════════════════════════════════════════
# Passing criteria
# ════════════════════════════════════════════════════════════════════════════════════════════════════════════
_PASS_PAT = re.compile(r"(?i)pass(ing)?\s+(requirements?|criteria|minimum|marks)|minimum\s+(of\s+)?\d{2}\s*%|"
                       r"declared\s+to\s+have\s+passed")


def _kb() -> dict:
    with _kb_lock:
        return json.loads(KB_FILE.read_text(encoding="utf-8")) if KB_FILE.exists() else {}


def _kb_put(key: str, val: dict) -> None:
    with _kb_lock:
        d = json.loads(KB_FILE.read_text(encoding="utf-8")) if KB_FILE.exists() else {}
        d[key] = val
        KB_FILE.write_text(json.dumps(d, indent=2), encoding="utf-8")


def _local_doc(info: dict) -> Path | None:
    """Cached document path. Entries store only the file name, so the cache survives moving machines."""
    name = Path(info.get("local_file", "")).name
    p = DOCS / name if name else None
    return p if p and p.exists() else None


def degree_key(short: str, title: str) -> str:
    s = re.sub(r"[^A-Z]", "", (short or "").upper())
    t = (title or "").upper()
    if s in ("BE", "BTECH") or ("BACHELOR" in t and ("ENGINEERING" in t or "TECHNOLOGY" in t)):
        return "BE-BTECH"
    if s in ("ME", "MTECH") or ("MASTER" in t and ("ENGINEERING" in t or "TECHNOLOGY" in t)):
        return "ME-MTECH"
    return s or re.sub(r"[^A-Z]", "", t)[:12]


def official_domains(explicit: list[str], website: str, mail_domains: list[str]) -> list[str]:
    """Explicit domains and the UGC website are trusted as given. Mail domains only if .edu / .ac.xx / .edu.xx."""
    out: list[str] = []
    for d in list(explicit) + ([website] if website else []):
        rd = registrable_domain(d)
        if rd and rd not in out:
            out.append(rd)
    for d in mail_domains:
        rd = registrable_domain(d)
        if rd and rd not in FREE_MAIL and re.search(r"\.(edu|ac\.[a-z]{2}|edu\.[a-z]{2})$", rd) and rd not in out:
            out.append(rd)
    return [d for d in out if "." in d and "helloverify" not in d]


def _on_domain(url: str, domains: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in domains)


def _download(url: str) -> Path:
    content, ctype = fetch(url, 60)
    ext = ".pdf" if ("pdf" in ctype or content[:5] == b"%PDF-") else ".html"
    p = DOCS / (hashlib.sha1(url.encode()).hexdigest()[:16] + ext)
    p.write_bytes(content)
    return p


def heading_needles(heading: str) -> list[str]:
    """'14. PASSING REQUIREMENTS ...' gives the full core heading, then its 8/6/4-word prefixes."""
    core = re.sub(r"^\s*[\d.]+\s*", "", heading or "")
    core = re.sub(r"^\d+\s*", "", core).strip()  # footnote marker
    words = core.split()
    out = [core] if core else []
    for n in (8, 6, 4):
        if len(words) > n:
            out.append(" ".join(words[:n]))
    return [o for o in out if len(o) >= 8]


def _core_clause(text: str, heading: str) -> str:
    """Heading and the first sub-clause (14. ... 14.1 ...), stopping before 14.2."""
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
    dt = (doc_text or "").replace(" %", "%")
    return all(n.replace(" ", "") in dt for n in nums)


def _locate_pdf(path: Path, heading: str, phrase: str, page_hint: int, want_png: bool) -> dict | None:
    doc = pymupdf.open(str(path))
    needles = heading_needles(heading)
    best = None
    for i, page in enumerate(doc):
        t = _ws(page.get_text()).lower()
        score = 0
        found = next((k for k, n in enumerate(needles) if n.lower() in t), None)
        if found is not None:
            score += 6 - min(found, 3)  # a longer heading match scores higher
        if phrase and _ws(phrase).lower()[:60] in t:
            score += 4
        score += min(3, len(_PASS_PAT.findall(t)))
        if page_hint and i + 1 == page_hint:
            score += 1
        if score and (best is None or score > best[0]):
            best = (score, i)
    if not best:
        return None
    page = doc[best[1]]
    W, H = page.rect.width, page.rect.height
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
        m = [b for b in page.get_text("blocks") if _PASS_PAT.search(b[4])]
        y_start = (m[0][1] - 8) if m else 60
    # the clause ends at the next top-level numbered heading ("15." alone or "15. SOMETHING")
    y_end = min(H - 30, y_start + 320)
    for b in page.get_text("blocks"):
        if b[1] > y_start + 40 and re.match(r"^\s*\d{1,2}\.\s*(\n|[A-Z][A-Z ]{4,})", b[4]):
            y_end = min(y_end, b[1] - 4)
            break
    region = pymupdf.Rect(30, y_start, W - 30, y_end)
    clause_text = _ws(page.get_text(clip=region))
    if head_core:  # drop running headers / page numbers printed before the heading
        i = clause_text.lower().find(head_core.lower())
        num = re.match(r"^\s*([\d.]+)", heading or "")
        if i > 0:
            j = clause_text.rfind(num.group(1).rstrip("."), 0, i) if num else -1
            clause_text = clause_text[j if 0 <= j < i else i:]
    png = b""
    if want_png:
        marks = []
        num = re.match(r"^\s*(\d+)", heading or "")
        if hits and num:  # highlight the whole first sub-clause (14.1 ...) up to "14.2"
            sub2 = [r for r in page.search_for(f"{num.group(1)}.2") if r.y0 > hits[0].y1 and r.x0 < W * 0.3]
            if sub2:
                for b in page.get_text("dict")["blocks"]:
                    for ln in b.get("lines", []):
                        r = pymupdf.Rect(ln["bbox"])
                        if r.y0 >= hits[0].y1 - 1 and r.y1 <= sub2[0].y0 + 1 and r.x0 >= hits[0].x0 - 6:
                            marks.append(r)
        if not marks:
            marks = phrase_hits
        if not marks:
            for b in page.get_text("dict")["blocks"]:
                for ln in b.get("lines", []):
                    txt = "".join(s["text"] for s in ln["spans"])
                    r = pymupdf.Rect(ln["bbox"])
                    if region.contains(r) and re.search(r"\d{2}\s*%|passed|pass ", txt, re.I):
                        marks.append(r)
        for h in hits[:1] + list(marks):
            page.add_highlight_annot(h).update()
        clip = pymupdf.Rect(0, max(0, y_start - 70), W, min(H, y_end + 50))
        png = page.get_pixmap(dpi=150, clip=clip, annots=True).tobytes("png")
    return {"page": best[1] + 1, "pages": doc.page_count, "clause_text": clause_text, "png": png,
            "doc_text": _ws(" ".join(p.get_text() for p in doc))}


def _html_to_text(raw: bytes) -> str:
    s = raw.decode("utf-8", "ignore")
    s = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</(p|li|tr|div|h\d)>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    return html_lib.unescape(s)


def _locate_html(path: Path, heading: str, phrase: str) -> dict | None:
    """Text-only location in an HTML page (no browser): the paragraph around the phrase or heading."""
    text = _ws(_html_to_text(path.read_bytes()))
    low = text.lower()
    for n in [phrase] + heading_needles(heading):
        n = _ws(n).lower()[:80]
        if n and (i := low.find(n)) >= 0:
            start = max(0, low.rfind(". ", 0, max(0, i - 200)) + 1) if i > 200 else 0
            return {"page": 0, "pages": 0, "clause_text": text[start:i + 1400].strip(), "png": b"", "doc_text": text}
    return None


def _not_found(t0, reason, **kw) -> PassingCriteriaResponse:
    return PassingCriteriaResponse(found=False, reason=reason, seconds=round(time.time() - t0, 2), **kw)


async def find_passing_criteria(req: PassingCriteriaRequest) -> PassingCriteriaResponse:
    """Find the official passing requirement for a programme. Uses the knowledge cache or an OpenAI domain-locked search."""
    t0 = time.time()
    domains = official_domains(req.official_domains, req.university_website, req.mail_domains)
    reg_year = (re.search(r"(19|20)\d{2}", req.regulation or "")
                or re.search(r"(19|20)\d{2}", req.year_of_passing or "") or [None])[0]
    key = f"{norm(req.university)}|{degree_key(req.degree_short, req.degree_title)}|{reg_year or ''}"
    usage: LLMUsage | None = None
    cached = loose = False
    info = None

    if req.use_cache:
        kb = _kb()
        info = kb.get(key)
        if not info and not re.search(r"(19|20)\d{2}", req.regulation or ""):
            # regulation unknown: take the newest entry for the same university and programme
            prefix = key.rsplit("|", 1)[0] + "|"
            cands = sorted((v for k, v in kb.items() if k.startswith(prefix)),
                           key=lambda v: v.get("created", ""), reverse=True)
            info, loose = (cands[0], True) if cands else (None, False)
        if info and _local_doc(info):
            cached = True
        else:
            info, loose = None, False

    if not cached:
        if not domains:
            return _not_found(t0, "official university domain unknown: pass official_domains or university_website")
        if not USE_LLM:
            return _not_found(t0, "no cached regulation and OpenAI search is disabled (OPENAI_API_KEY missing)",
                              domains=domains)
        prompt = f"""Find the official academic regulations document published by {req.university} on its own website
({', '.join(domains)}) that states the PASSING requirement (minimum marks to pass a course) for this programme.
Programme: {req.degree_title} ({req.degree_short}). Candidate's regulation/scheme: {req.regulation or 'unknown'}.
Year of passing: {req.year_of_passing or 'unknown'}. Studied at {'an affiliated college' if req.affiliated else 'the university'}.
Prefer the regulation matching the candidate's regulation year and programme (and affiliated-college version if applicable).
Return ONLY JSON with keys: url (direct link to the document/page), document_title, regulation,
clause_heading (exact heading as printed e.g. "14. PASSING REQUIREMENTS"),
locate_phrase (an exact 6-12 word phrase copied verbatim from the clause text),
passing_criteria (1-2 sentences with the exact percentages/marks), page_number (PDF page if known else 0)."""
        try:
            found, usage = await asyncio.to_thread(web_search_json, prompt, domains)
        except Exception as e:
            return _not_found(t0, f"OpenAI search failed: {e}", domains=domains)
        url = str(found.get("url") or "").strip()
        if not url or not _on_domain(url, domains):
            return _not_found(t0, f"search returned a non-official source {url!r}", url=url, domains=domains,
                              llm=usage)
        try:
            local = await asyncio.to_thread(_download, url)
        except Exception as e:
            return _not_found(t0, f"official document could not be downloaded: {e}", url=url, domains=domains,
                              llm=usage)
        info = {**found, "url": url, "local_file": local.name, "domains": domains,
                "created": datetime.now().isoformat(timespec="seconds")}

    local = _local_doc(info)
    heading, phrase = info.get("clause_heading", "") or "", info.get("locate_phrase", "") or ""
    try:
        page_hint = int(info.get("page_number") or 0)
    except (TypeError, ValueError):
        page_hint = 0
    try:
        if local.suffix == ".pdf":
            loc = await asyncio.to_thread(_locate_pdf, local, heading, phrase, page_hint, req.include_evidence)
        else:
            loc = await asyncio.to_thread(_locate_html, local, heading, phrase)
    except Exception as e:
        loc, err = None, str(e)
    else:
        err = ""
    if not loc:
        return _not_found(t0, "clause not located in the official document" + (f": {err}" if err else ""),
                          url=info["url"], domains=info.get("domains", domains), llm=usage)

    verified = _numbers_verified(info.get("passing_criteria", ""), loc["clause_text"] or loc["doc_text"]) and not loose
    if not cached and verified:
        _kb_put(key, info)  # only verified results enter the knowledge cache

    evidence = []
    if req.include_evidence and loc["png"]:
        evidence.append(Evidence(kind="passing_clause", title=heading or "Passing requirements",
                                 source_url=info["url"], page=loc["page"], data_base64=_png_b64(loc["png"])))
    return PassingCriteriaResponse(
        found=True, verified=verified, cached=cached, loose_match=loose, url=info["url"],
        document_title=info.get("document_title", "") or unquote(Path(urlparse(info["url"]).path).name),
        regulation=str(info.get("regulation", "") or ""), clause_heading=heading,
        criteria=str(info.get("passing_criteria", "") or ""),
        clause_text=_core_clause(loc["clause_text"], heading)[:2000], page=loc["page"], pages=loc["pages"],
        domains=info.get("domains", domains), evidence=evidence, llm=usage, seconds=round(time.time() - t0, 2))


# ════════════════════════════════════════════════════════════════════════════════════════════════════════════
# Combined: accreditation, then passing criteria (it needs the canonical name and the UGC website)
# ════════════════════════════════════════════════════════════════════════════════════════════════════════════
async def research(req: ResearchRequest) -> ResearchResponse:
    t0 = time.time()
    acc = await check_accreditation(AccreditationRequest(
        university=req.university, college=req.college, degree=f"{req.degree_short} {req.degree_title}".strip(),
        include_evidence=req.include_evidence))
    uni = acc.canonical_university or req.university.split(",")[0]
    passing = await find_passing_criteria(PassingCriteriaRequest(
        university=uni, degree_title=req.degree_title, degree_short=req.degree_short, regulation=req.regulation,
        year_of_passing=req.year_of_passing,
        affiliated=req.affiliated if req.affiliated is not None else bool(req.college),
        official_domains=req.official_domains, university_website=acc.ugc.website if acc.ugc else "",
        mail_domains=req.mail_domains, use_cache=req.use_cache, include_evidence=req.include_evidence))
    return ResearchResponse(accreditation=acc, passing=passing, total_usd=passing.llm.usd if passing.llm else 0.0,
                            seconds=round(time.time() - t0, 2))


def health() -> HealthResponse:
    return HealthResponse(version=VERSION, llm_enabled=USE_LLM, search_model=SEARCH_MODEL,
                          ugc_cached=all((SOURCES / f"ugc_{t}.json").exists() for t in UGC_TYPES),
                          aicte_cached=(SOURCES / "aicte_index.json").exists(), knowledge_entries=len(_kb()),
                          data_dir=str(DATA))


# ---------- sync wrappers (scripts, Celery workers, Flask, etc.) ----------
def check_accreditation_sync(req: AccreditationRequest | dict) -> AccreditationResponse:
    return asyncio.run(check_accreditation(AccreditationRequest.model_validate(req)))


def find_passing_criteria_sync(req: PassingCriteriaRequest | dict) -> PassingCriteriaResponse:
    return asyncio.run(find_passing_criteria(PassingCriteriaRequest.model_validate(req)))


def research_sync(req: ResearchRequest | dict) -> ResearchResponse:
    return asyncio.run(research(ResearchRequest.model_validate(req)))


# ════════════════════════════════════════════════════════════════════════════════════════════════════════════
# HTTP exposure (optional; FastAPI is imported only when this is called)
# ════════════════════════════════════════════════════════════════════════════════════════════════════════════
def create_router(prefix: str = "/research"):
    """APIRouter to mount in an existing FastAPI app: app.include_router(create_router())."""
    from fastapi import APIRouter

    router = APIRouter(prefix=prefix, tags=["research"])
    router.add_api_route("/health", health, methods=["GET"], response_model=HealthResponse)
    router.add_api_route("/accreditation", check_accreditation, methods=["POST"], response_model=AccreditationResponse)
    router.add_api_route("/passing-criteria", find_passing_criteria, methods=["POST"],
                         response_model=PassingCriteriaResponse)
    router.add_api_route("", research, methods=["POST"], response_model=ResearchResponse)
    return router


def create_app():
    """Standalone FastAPI app. Run with: uvicorn research:app --app-dir research_api --port 8100"""
    from contextlib import asynccontextmanager

    from fastapi import FastAPI

    @asynccontextmanager
    async def lifespan(_):
        threading.Thread(target=warm_sources, daemon=True).start()
        yield

    api = FastAPI(title="HV Research API", version=VERSION, lifespan=lifespan)
    api.include_router(create_router())
    return api


def __getattr__(name):  # lazy `app` so `uvicorn research:app` works without importing FastAPI for library use
    if name == "app":
        return create_app()
    raise AttributeError(name)


# ════════════════════════════════════════════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════════════════════════════════════════════
def _main(argv: list[str]) -> int:
    cmds = {"accreditation": check_accreditation_sync, "passing-criteria": find_passing_criteria_sync,
            "research": research_sync}
    if len(argv) >= 1 and argv[0] == "serve":
        import uvicorn
        port = int(argv[argv.index("--port") + 1]) if "--port" in argv else 8100
        uvicorn.run(create_app(), host="127.0.0.1", port=port)
        return 0
    if len(argv) != 2 or argv[0] not in cmds:
        print(__doc__)
        return 2
    payload = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    print(cmds[argv[0]](payload).model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
