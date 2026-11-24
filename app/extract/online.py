"""Online-database verification: screenshots of a university's own portal (result / grade card /
admission status pages) used as the verification revert instead of an e-mail.

Everything here is LOCAL (Tesseract + rules) — portal screenshots contain candidate data and are never sent
to an external service.

Per screenshot we read: the URL in the browser address bar (or the PDF text layer above the screenshot),
the page type (result vs admission), label/value pairs (enrolment no, name, programme, admission year,
status-as-on date, regional/study centre, mode of study …) and the course/status table."""
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pymupdf
from PIL import Image, ImageOps
from rapidfuzz import fuzz, process

from .mail import registrable_domain

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
MONTH_NAMES = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER",
               "NOVEMBER", "DECEMBER"]

# ---------------------------------------------------------------- classification
URL_RE = re.compile(r"(?i)\b((?:https?://)?(?:[a-z0-9-]+\.)+(?:ac\.in|edu\.in|gov\.in|nic\.in|res\.in|org\.in|co\.in|"
                    r"edu|ac\.[a-z]{2}|in|com|org|net)(?::\d+)?/[^\s\"'<>|]*)")
PORTAL_RULES = [r"status\s+as\s+on", r"all\s+rights\s+reserved", r"powered\s+by", r"\bsign[\s-]?off\b|\blog\s?out\b",
                r"enrol+ment\s*no|roll\s*no|seat\s*no", r"grade\s*card|result|marks?\s*sheet|admission",
                r"\bwelcome\b", r"for\s+information\s+only|indicative\s+only|disclaimer"]


def portal_score(text: str, filename: str = "") -> int:
    t = text or ""
    s = sum(1 for p in PORTAL_RULES if re.search(p, t, re.I))
    head = re.sub(r"(?i)\.acin\b", ".ac.in", "\n".join(l for l in t.splitlines() if l.strip())[:600])
    m = URL_RE.search(head)          # browser address bar at the top of the screenshot / URL typed above it
    if m and not re.search(r"(?i)mail|outlook|office|live\.com|helloverify", m.group(1)):
        s += 3
        if re.search(r"(?i)online|portal|screenshot|start\s*date|admission|grade\s*card|result|revert", filename or ""):
            s += 1
        if re.search(r"(?i)\breply\b|\bforward\b|^\s*(to|cc)\b", t, re.M):   # looks like a webmail screenshot
            s -= 2
    return s


# ---------------------------------------------------------------- OCR
def _tesseract_tsv(path: Path, psm: int = 6) -> list[dict]:
    try:
        r = subprocess.run(["tesseract", str(path), "-", "--psm", str(psm), "tsv"], capture_output=True, text=True,
                           timeout=90)
    except Exception:
        return []
    words = []
    for ln in r.stdout.splitlines()[1:]:
        p = ln.split("\t")
        if len(p) < 12 or not p[11].strip():
            continue
        try:
            words.append({"block": int(p[2]), "par": int(p[3]), "line": int(p[4]), "x": int(p[6]), "y": int(p[7]),
                          "w": int(p[8]), "h": int(p[9]), "conf": float(p[10]), "text": p[11]})
        except ValueError:
            continue
    return words


def _lines(words: list[dict]) -> list[dict]:
    groups = {}
    for w in words:
        groups.setdefault((w["block"], w["par"], w["line"]), []).append(w)
    out = []
    for ws in groups.values():
        ws.sort(key=lambda w: w["x"])
        out.append({"words": ws, "y": min(w["y"] for w in ws), "text": " ".join(w["text"] for w in ws)})
    out.sort(key=lambda l: (l["y"], l["words"][0]["x"]))
    return out


def _enhance(src: Path, dst: Path, target_w: int = 2600) -> float:
    """Darkest channel (coloured text on coloured bands becomes dark-on-light) + autocontrast + upscale."""
    im = Image.open(src).convert("RGB")
    g = Image.fromarray(np.asarray(im).min(axis=2))
    g = ImageOps.autocontrast(g, cutoff=1)
    k = min(3.0, max(1.0, target_w / max(1, g.width)))
    if k > 1:
        g = g.resize((int(g.width * k), int(g.height * k)), Image.LANCZOS)
    g.save(dst)
    return k


def _recrop_label(img_path: Path, words: list[dict], label_re: str, stop_re: str, out: Path) -> str:
    """Values in small/coloured table cells (often wrapped onto two lines) are missed by the full-page pass.
    Crop the band around the label up to the next label on the same line, upscale and read again."""
    lab = next((w for w in words if re.fullmatch(label_re, w["text"], re.I)), None)
    x0 = lab["x"] - 10 if lab else None
    if not lab:
        # label itself not read: take the gap after the enrolment/roll number on the same line
        num = next((w for w in words if re.fullmatch(r"[A-Z]{0,4}\d{6,14}", w["text"]) and any(
            re.match(r"(?i)enrol|roll|reg", o["text"]) and abs(o["y"] - w["y"]) < w["h"] and o["x"] < w["x"]
            for o in words)), None)
        if not num:
            return ""
        lab, x0 = num, num["x"] + num["w"] + 6
    same = [w for w in words if abs(w["y"] - lab["y"]) < lab["h"] * 1.2 and w["x"] > lab["x"] + lab["w"]
            and re.match(stop_re, w["text"], re.I)]
    im = Image.open(img_path)
    x1 = min(w["x"] for w in same) - 8 if same else im.width
    box = (max(0, x0), max(0, int(lab["y"] - lab["h"] * 1.3)), x1, min(im.height, int(lab["y"] + lab["h"] * 2.4)))
    if box[2] - box[0] < 40:
        return ""
    c = im.crop(box)
    c.resize((c.width * 2, c.height * 2), Image.LANCZOS).save(out)
    txt = " ".join(l["text"] for l in _lines(_tesseract_tsv(out, 6)))
    txt = re.sub(label_re.replace("\\b", "") + r"\s*[:.]?", " ", txt, flags=re.I)
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z .]", " ", txt)).strip()


def portal_images(doc: dict, workdir: Path) -> list[Path]:
    """Native-resolution screenshots: embedded images of a PDF (ops paste screenshots into Word/PDF), else the file."""
    p = Path(doc["path"])
    if p.suffix.lower() != ".pdf":
        return [Path(x) for x in doc.get("pages") or [p]]
    out = []
    pdf = pymupdf.open(str(p))
    for pi, page in enumerate(pdf):
        for ii, img in enumerate(page.get_images(full=True)):
            try:
                x = pdf.extract_image(img[0])
            except Exception:
                continue
            if x["width"] < 500 or x["height"] < 250:     # logos / icons
                continue
            f = workdir / f"{p.stem}_shot{pi + 1}_{ii + 1}.{x['ext']}"
            f.write_bytes(x["image"])
            out.append(f)
    return out or [Path(x) for x in doc.get("pages", [])]


def _address_bar(img: Path, workdir: Path) -> str:
    """OCR only the top strip (browser address bar) at 3x — the full-page pass often drops a letter of the host."""
    im = Image.open(img).convert("RGB")
    strip = im.crop((0, 0, im.width, max(30, min(int(im.height * 0.09), 90))))
    g = ImageOps.autocontrast(Image.fromarray(np.asarray(strip).min(axis=2)))
    g = g.resize((g.width * 3, g.height * 3), Image.LANCZOS)
    out = workdir / f"{img.stem}_addr.png"
    g.save(out)
    return " ".join(l["text"] for l in _lines(_tesseract_tsv(out, 6)))


def ocr_screenshot(img: Path, workdir: Path) -> dict:
    enh = workdir / f"{img.stem}_enh.png"
    _enhance(img, enh)
    addr = _address_bar(img, workdir)
    words = _tesseract_tsv(enh, 6)
    lines = _lines(words)
    text = "\n".join(l["text"] for l in lines)
    name_cell = ""
    if re.search(r"(?im)\bnam[eo]\s*[:.]?\s*$|\bnam[eo]\s*[:.]\s*\S{0,6}\s+(prog|$)", text) or \
            not re.search(r"(?i)\bname\s*[:.]?\s*[A-Z]{3,}\s+[A-Z]{3,}", text):
        name_cell = _recrop_label(enh, words, r"nam[eo]:?", r"prog|course|enrol|roll", workdir / f"{img.stem}_name.png")
    return {"image": str(img), "text": text, "name_cell": name_cell, "address_bar": addr}


# ---------------------------------------------------------------- parsing
def _fix_ligatures(s: str) -> str:
    return (s or "").replace("hƩps", "https").replace("Ʃ", "tt").replace("Ɵ", "ti").replace("ﬁ", "fi").replace("ﬂ", "fl")


def find_url(*texts: str) -> str:
    """First plausible URL; texts in order of trust (PDF text layer, address-bar OCR, full-page OCR)."""
    for src in texts:
        src = re.sub(r"(?i)\.acin\b", ".ac.in", _fix_ligatures(src or ""))
        for m in URL_RE.finditer(src):
            u = m.group(1).rstrip(".,;)]}")
            if not u.lower().startswith("http"):
                u = "https://" + u
            host = urlparse(u).hostname or ""
            if "." in host and not host.endswith(("helloverify.com", "google.com")):
                return u
    return ""


def norm_month_year(s: str) -> str:
    """'Jan-2005' / 'dan-2005' (OCR) / 'June 2011' / '06/2011' → '01-2005'."""
    s = (s or "").strip()
    m = re.search(r"([A-Za-z]{3,9})\W{0,3}((?:19|20)\d{2})", s)
    if m:
        tok = m.group(1).upper()
        hit = process.extractOne(tok, MONTH_NAMES if len(tok) > 3 else MONTHS, scorer=fuzz.ratio)
        if hit and hit[1] >= 60:
            idx = (MONTH_NAMES if len(tok) > 3 else MONTHS).index(hit[0])
            return f"{idx + 1:02d}-{m.group(2)}"
    m = re.search(r"\b(0?[1-9]|1[0-2])\s*[-/.]\s*((?:19|20)\d{2})\b", s)
    if m:
        return f"{int(m.group(1)):02d}-{m.group(2)}"
    return ""


def norm_date(s: str) -> str:
    """'23-Nov-2026' / '20-11-2026' / '23/11/2026' → '23-11-2026'."""
    s = (s or "").strip()
    m = re.search(r"\b(\d{1,2})\s*[-/. ]\s*([A-Za-z]{3,9})\s*[-/. ]\s*((?:19|20)\d{2})", s)
    if m:
        mon = norm_month_year(f"{m.group(2)} {m.group(3)}")
        if mon:
            return f"{int(m.group(1)):02d}-{mon}"
    m = re.search(r"\b(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*((?:19|20)\d{2})\b", s)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{int(m.group(1)):02d}-{int(m.group(2)):02d}-{m.group(3)}"
    return ""


NAME_CHARS = r"[A-Z][A-Z .]{2,60}?"
LABELS = [
    ("enrollment_no", r"enrol+ment\s*(?:no|number)\s*\.?\s*[:.\-]?\s*([A-Z]{0,4}[\-/]?\d[\dA-Z/\-]{4,18})"),
    ("roll_no", r"(?:roll|seat|registration|register|reg\.?)\s*(?:no|number)\s*\.?\s*[:.\-]?\s*([A-Z]{0,4}\d[\dA-Z/\-]{3,18})"),
    ("programme", r"prog(?:ram|ramme)?\s*(?:code|name)?\s*[:.\-]\s*([A-Z][A-Za-z0-9()./&\- ]{1,50}?)(?=\s{2,}|\s+(?:status|enrol|name)\b|$)"),
    ("name", rf"(?<![a-z])(?:candidate'?s?\s+|student'?s?\s+)?name(?:\s+of\s+the\s+(?:candidate|student))?\s*[:.\-]\s*({NAME_CHARS})(?=\s{{2,}}|\s+prog|\s+enrol|\s+roll|$)"),
    ("welcome_name", rf"\bwelcome\s+({NAME_CHARS})\s*$"),
    ("admission_year", r"(?:admission|admitted)\s*(?:year|date|session|in)\s*[:.\-]?\s*([A-Za-z]{3,9}\W{0,3}(?:19|20)\d{2}|(?:19|20)\d{2})"),
    ("valid_upto", r"valid\s*up\s*to\s*[:.\-]?\s*([A-Za-z]{3,9}\W{0,3}(?:19|20)\d{2}|(?:19|20)\d{2})"),
    ("status_as_on", r"status\s*as\s*on\s*[:.\-]?\s*(\d{1,2}\s*[-/. ]\s*[A-Za-z0-9]{2,9}\s*[-/. ]\s*(?:19|20)\d{2})"),
    ("current_date", r"current\s*date\s*[:.\-]?\s*(\d{1,2}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*(?:19|20)\d{2})"),
    ("father_name", rf"father.{{0,25}}?name\s*[:.\-]?\s*({NAME_CHARS})(?=\s{{2,}}|\s+[A-Z][a-z]|\s+\d|$)"),
    ("dob", r"(?:date\s*of\s*birth|d\.?o\.?b\.?)\s*[:.\-]?\s*(\d{1,2}\s*[-/.]\s*\w{2,9}\s*[-/.]\s*(?:19|20)\d{2})"),
    ("regional_centre", r"regional\s*cent(?:re|er)\s*(?:code)?\s*[:.\-]?\s*(\d{1,3}\s*[:\-]\s*[A-Z][A-Z ]{2,30}|[A-Z][A-Z ]{3,30})"),
    ("study_centre", r"study\s*cent(?:re|er)\s*(?:code)?\s*[:.\-]?\s*([0-9A-Z]{2,10})"),
    ("year_of_passing", r"(?:month\s*(?:&|and)?\s*)?year\s*of\s*(?:passing|completion)\s*[:.\-]?\s*([A-Za-z]{0,9}\W{0,3}(?:19|20)\d{2})"),
    ("result", r"\b(?:final\s+)?result\s*[:.\-]\s*([A-Za-z][A-Za-z ]{2,30})"),
    ("division", r"\b(?:division|class\s*awarded|classification)\s*[:.\-]\s*([A-Za-z][A-Za-z ]{2,30})"),
    ("cgpa", r"\b(?:cgpa|ogpa|cpi|percentage)\s*[:.\-]?\s*(\d{1,2}(?:\.\d{1,2})?\s*%?)"),
    ("mode_of_study", r"(?:mode\s*of\s*(?:study|learning|education|course)|study\s*mode|course\s*mode)\s*[:.\-]?\s*([A-Za-z][A-Za-z /\-]{2,30})"),
]
COURSE_RE = re.compile(r"(?i)^\W{0,3}([0-9S§]{3}[A-Z]?|[A-Z]{2,6}[- ]?\d{1,4}[A-Z]?)\b.*?\b(NOT\s+COMPLETED|COMPLETED|"
                       r"INCOMPLETE|PASS(?:ED)?|FAIL(?:ED)?|ABSENT)\b")
UNI_RE = re.compile(r"((?:\b[A-Z]{2,}\b[ .,&]+){1,8}UNIVERSITY(?:\s+OF\s+[A-Z]{3,}(?:\s+[A-Z]{3,}){0,3})?)")


def _clean_name(s: str) -> str:
    s = re.sub(r"[^A-Za-z .]", " ", s or "")
    s = re.sub(r"\b[a-z]\w*\b", " ", s)                  # OCR junk is usually lower/mixed case
    return re.sub(r"\s+", " ", s).strip(" .").upper()


def parse_text(text: str) -> dict:
    f = {}
    for ln in text.splitlines():
        for key, pat in LABELS:
            if key in f:
                continue
            m = re.search(pat, ln, re.I if key not in ("name", "welcome_name", "father_name") else 0) or \
                (re.search(pat, ln, re.I) if key in ("name", "welcome_name", "father_name") else None)
            if m:
                f[key] = m.group(1).strip(" .:-")
    for k in ("name", "welcome_name", "father_name"):
        if k in f:
            f[k] = _clean_name(f[k])
            if len(f[k].split()) < 2:
                f.pop(k)
    for k in ("admission_year", "valid_upto", "year_of_passing"):
        if k in f:
            f[k + "_mm_yyyy"] = norm_month_year(f[k]) or (f"01-{f[k]}" if re.fullmatch(r"(19|20)\d{2}", f[k]) else "")
    for k in ("status_as_on", "current_date", "dob"):
        if k in f:
            f[k + "_dd_mm_yyyy"] = norm_date(f[k])
    unis = [re.sub(r"\s+", " ", m.group(1)).strip(" .,&") for m in UNI_RE.finditer(text)]
    if unis:
        f["university"] = max(set(unis), key=unis.count).title().replace(" Of ", " of ")
    return f


def parse_courses(text: str) -> dict:
    rows = {}
    for ln in text.splitlines():
        m = COURSE_RE.search(ln)
        if m:
            code = m.group(1).upper().replace("§", "5").replace("S", "5") if re.match(r"[S§]\d", m.group(1)) else m.group(1).upper()
            rows[code] = re.sub(r"\s+", " ", m.group(2).upper())
    bad = sorted(c for c, s in rows.items() if re.search(r"NOT|INCOMPLETE|FAIL|ABSENT", s))
    return {"total": len(rows), "completed": len(rows) - len(bad), "not_completed": bad,
            "statuses": sorted(set(rows.values()))}


def record_type(text: str, fields: dict) -> str:
    t = (text or "").lower()
    if re.search(r"grade\s*card|marks?\s*sheet|result|transcript|term\s*end", t) or parse_courses(text)["total"] >= 3:
        return "result"
    if re.search(r"admission|registration\s*details|enrol+ment\s*status", t) or fields.get("admission_year"):
        return "admission"
    return "record"


TYPE_LABEL = {"result": "Online Revert", "admission": "Start Date", "record": "Online Record"}


VISION_KEYS = ["url", "enrollment_no", "roll_no", "name", "programme", "university", "admission_year", "valid_upto",
               "status_as_on", "year_of_passing", "result", "division", "cgpa", "mode_of_study", "regional_centre",
               "study_centre", "father_name", "dob"]
VISION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": VISION_KEYS + ["page_type", "address_bar_visible", "courses"],
    "properties": {**{k: {"type": "string"} for k in VISION_KEYS},
                   "page_type": {"type": "string", "enum": ["result", "admission", "record"]},
                   "address_bar_visible": {"type": "array", "items": {"type": "boolean"}},
                   "courses": {"type": "array", "items": {
                       "type": "object", "additionalProperties": False, "required": ["code", "status"],
                       "properties": {"code": {"type": "string"}, "status": {"type": "string"}}}}},
}
VISION_PROMPT = """These images are screenshots of ONE page of a university's official online portal (result / grade card /
admission or registration status), possibly scrolled in several parts that overlap. Copy values exactly as shown;
use "" when a value is not visible. Never guess.
- url: the full URL in the browser address bar (or typed above the screenshot); "" if not visible
- page_type: result (grade card, marks, result, course completion) | admission (admission/registration details) | record
- enrollment_no / roll_no: as printed; name: student name; programme: programme name/code as printed
- admission_year, valid_upto, status_as_on ("Status as on …" date), year_of_passing: exactly as printed
- mode_of_study: only if the portal states it (e.g. Distance, Regular, Online); regional_centre, study_centre as printed
- courses: every row of the course/subject table ONCE (screenshots overlap — do not repeat a course code),
  code + status column as printed (e.g. COMPLETED, NOT COMPLETED, PASS)
- address_bar_visible: one boolean per image, true if that image shows a browser address bar
"""


def _vision_portal(images: list[Path], hint: str) -> tuple[dict, dict]:
    from .. import llm
    return llm.extract_json(VISION_PROMPT + (f"\nText layer next to the screenshots: {hint[:400]}" if hint.strip() else ""),
                            images=[str(p) for p in images[:6]], schema=VISION_SCHEMA)


def read_portal(doc: dict, workdir: Path) -> dict:
    from .. import config, llm
    images = portal_images(doc, workdir)
    pdf_text = ""
    if Path(doc["path"]).suffix.lower() == ".pdf":
        try:
            pdf_text = "\n".join(p.get_text() for p in pymupdf.open(doc["path"]))
        except Exception:
            pass
    if config.CANDIDATE_LLM and llm.available():
        try:
            return _read_portal_vision(doc, images, pdf_text)
        except Exception as e:                      # fall back to local OCR
            res = _read_portal_ocr(doc, workdir, images, pdf_text)
            res["vision_error"] = str(e)[:200]
            return res
    return _read_portal_ocr(doc, workdir, images, pdf_text)


def _read_portal_vision(doc: dict, images: list[Path], pdf_text: str) -> dict:
    v, meta = _vision_portal(images, _fix_ligatures(pdf_text))
    fields = {k: re.sub(r"\s+", " ", v.get(k, "")).strip() for k in VISION_KEYS if k != "url" and v.get(k, "").strip()}
    for k in ("name", "father_name"):
        if k in fields:
            fields[k] = _clean_name(fields[k].upper())
    for k in ("admission_year", "valid_upto", "year_of_passing"):
        if k in fields:
            fields[k + "_mm_yyyy"] = norm_month_year(fields[k]) or (f"01-{fields[k]}" if re.fullmatch(r"(19|20)\d{2}", fields[k]) else "")
    for k in ("status_as_on", "dob"):
        if k in fields:
            fields[k + "_dd_mm_yyyy"] = norm_date(fields[k])
    if fields.get("university"):
        fields["university"] = fields["university"].title().replace(" Of ", " of ")
    rows = {}
    for c in v.get("courses", []):
        if c.get("code", "").strip():
            rows[c["code"].strip().upper()] = re.sub(r"\s+", " ", c.get("status", "").upper()).strip()
    bad = sorted(k for k, s in rows.items() if re.search(r"NOT|INCOMPLETE|FAIL|ABSENT", s))
    courses = {"total": len(rows), "completed": len(rows) - len(bad), "not_completed": bad,
               "statuses": sorted(set(rows.values()))}
    url = find_url(pdf_text, v.get("url", ""))
    host = (urlparse(url).hostname or "").lower()
    rtype = v.get("page_type") or "record"
    bars = list(v.get("address_bar_visible") or [])[:len(images)]
    bars += [bool(url)] * (len(images) - len(bars))
    # synthetic text so the mode-of-study clues and course merge in combine() work the same way
    text = "\n".join([f"{k.replace('_', ' ')}: {fields[k]}" for k in fields] + [f"{c} {s}" for c, s in rows.items()])
    return {"doc": doc["name"], "path": doc["path"], "images": [str(p) for p in images], "bars": bars, "url": url,
            "host": host, "domain": registrable_domain(host) if host else "", "type": rtype,
            "label": TYPE_LABEL.get(rtype, "Online Record"), "fields": fields, "courses": courses, "text": text,
            "method": "vision-llm", "meta": meta}


def _read_portal_ocr(doc: dict, workdir: Path, images: list[Path], pdf_text: str) -> dict:
    shots = [ocr_screenshot(p, workdir) for p in images]
    text = "\n".join(s["text"] for s in shots)
    url = find_url(pdf_text, "\n".join(s["address_bar"] for s in shots), text)
    fields = parse_text(text)
    for s in shots:
        nc = _clean_name(s["name_cell"])
        if len(nc.split()) >= 2 and "name" not in fields:
            fields["name"] = nc
            fields["_name_from_cell"] = "1"
    courses = parse_courses(text)
    rtype = record_type(text, fields)
    host = (urlparse(url).hostname or "").lower()
    bars = [bool(URL_RE.search(re.sub(r"(?i)\.acin\b", ".ac.in", s["address_bar"]))) for s in shots]
    return {"doc": doc["name"], "path": doc["path"], "images": [s["image"] for s in shots], "bars": bars, "url": url,
            "host": host, "domain": registrable_domain(host) if host else "", "type": rtype,
            "label": TYPE_LABEL[rtype], "fields": fields, "courses": courses, "text": text, "method": "local-ocr",
            "meta": {}}


# ---------------------------------------------------------------- combine
DISTANCE_RE = re.compile(r"(?i)\b(open\s+university|distance|correspondence|online\s+(?:mode|learning|programme)|"
                         r"odl\b|study\s*cent(?:re|er)|regional\s*cent(?:re|er)|learner\s*support)")
MODE_EXPLICIT = [(r"(?i)distance|correspondence|odl|open\s+and\s+distance", "Distance / Online"),
                 (r"(?i)\bonline\b", "Distance / Online"), (r"(?i)part[\s-]*time", "Part Time"),
                 (r"(?i)full[\s-]*time|regular", "Full Time - On Campus")]


def _best_name(portals: list[dict]) -> tuple[str, str]:
    cands = []
    for p in portals:
        f = p["fields"]
        if f.get("welcome_name"):
            cands.append((f["welcome_name"], p["doc"], 3))
        if f.get("name"):
            cands.append((f["name"], p["doc"], 1 if f.get("_name_from_cell") else 2))
    if not cands:
        return "", ""
    # a name confirmed by another screenshot wins; otherwise the cleanest source
    def support(c):
        return sum(1 for o in cands if o is not c and fuzz.token_sort_ratio(o[0], c[0]) >= 85)
    best = max(cands, key=lambda c: (support(c), c[2]))
    return best[0], best[1]


def combine(portals: list[dict]) -> dict:
    """Merge all screenshots into one revert-shaped fact set (same keys the e-mail revert parser produces)."""
    if not portals:
        return {"fields": {}, "sources": {}, "domains": [], "found": False, "portals": []}
    first = lambda key, types=None: next(((p["fields"][key], p) for p in portals
                                          if p["fields"].get(key) and (not types or p["type"] in types)), ("", None))
    out, src = {}, {}

    def put(k, v, p, note=""):
        if v:
            out[k] = v
            src[k] = {"doc": p["doc"] if p else "", "url": p["url"] if p else "", "note": note}

    enr, p = first("enrollment_no")
    if not enr:
        enr, p = first("roll_no")
    put("registration_no", enr, p)
    name, ndoc = _best_name(portals)
    put("name", name, next((x for x in portals if x["doc"] == ndoc), None))
    prog, p = first("programme")
    put("programme", prog, p)
    uni, p = first("university")
    put("university", uni, p)
    adm, p = first("admission_year")
    put("admission", adm, p)
    put("start_mm_yyyy", p["fields"].get("admission_year_mm_yyyy", "") if p else "", p, "Admission Year on the portal")
    vu, p = first("valid_upto")
    put("valid_upto", vu, p)
    yop, p = first("year_of_passing")
    put("year_of_passing", yop, p)
    put("end_mm_yyyy", p["fields"].get("year_of_passing_mm_yyyy", "") if p else "", p, "Year of passing on the portal")
    for k in ("father_name", "dob", "regional_centre", "study_centre", "result", "division", "cgpa"):
        v, p = first(k)
        put(k, v, p)
    # verification date: date the result portal shows its status for (else any portal)
    res = [x for x in portals if x["type"] == "result"] + [x for x in portals if x["type"] != "result"]
    for x in res:
        d = x["fields"].get("status_as_on_dd_mm_yyyy") or x["fields"].get("current_date_dd_mm_yyyy")
        if d:
            put("verified_date", d, x, "'Status as on' date shown by the portal")
            break
    # course table (screenshots overlap → de-duplicated by course code inside parse_courses of the joined text)
    rtext = "\n".join(x["text"] for x in portals if x["type"] == "result")
    courses = parse_courses(rtext) if rtext else {"total": 0, "completed": 0, "not_completed": [], "statuses": []}
    out["_courses"] = courses
    # status
    found = bool(out.get("registration_no") and (out.get("name") or out.get("programme")))
    result_txt = out.get("result", "")
    if courses["total"] and not courses["not_completed"]:
        status = f"Record found — all {courses['total']} courses COMPLETED"
    elif courses["not_completed"]:
        status = f"Record found — {len(courses['not_completed'])} of {courses['total']} courses NOT completed"
    elif re.search(r"(?i)pass", result_txt):
        status = f"Record found — result {result_txt}"
    elif found:
        status = "Record found on university portal"
    else:
        status = ""
    out["status"] = status
    out["_found"] = found
    out["_complete"] = bool((courses["total"] and not courses["not_completed"]) or re.search(r"(?i)pass", result_txt))
    # mode of study
    alltext = "\n".join(x["text"] for x in portals) + " " + out.get("university", "")
    mode, how = "", ""
    explicit = next((x["fields"]["mode_of_study"] for x in portals if x["fields"].get("mode_of_study")), "")
    if explicit:
        mode = next((v for pat, v in MODE_EXPLICIT if re.search(pat, explicit)), "")
        how = f"portal states mode: {explicit}"
    if not mode:
        clues = sorted({m.group(1).strip().title() for m in DISTANCE_RE.finditer(alltext)})
        if clues:
            mode, how = "Distance / Online", "inferred from portal: " + ", ".join(clues)
    out["mode_of_study"] = mode
    out["_mode_how"] = how
    out["_mode_explicit"] = bool(explicit and mode)
    domains = []
    for x in portals:
        if x["domain"] and x["domain"] not in domains:
            domains.append(x["domain"])
    out["_title"] = "Online verification — " + ", ".join(x["host"] for x in portals if x["host"])
    return {"fields": out, "sources": src, "domains": domains, "found": found,
            "portals": [{k: v for k, v in x.items() if k != "text"} for x in portals]}
