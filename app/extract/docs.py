"""Ingest uploaded files → flat list of documents with text + classification.

Kinds: degree | transcript | diploma | verification_report | mail | mail_screenshot | other
"""
import re
import unicodedata
from pathlib import Path

import pymupdf
from PIL import Image

from .. import ocr as ocrmod
from . import mail as mailmod

IMG_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
OCR_DPI = 200          # scanned PDF pages are rendered at this resolution for OCR
MAX_PDF_PAGES = 6


def norm_text(t: str) -> str:
    return unicodedata.normalize("NFKC", t or "")


def _norm_lines(lines: list[dict]) -> list[dict]:
    for l in lines:
        l["text"] = norm_text(l["text"])
    return lines


def _page_lines(res: dict) -> list[dict]:
    return _norm_lines(res["lines"])


def ocr_image(path: Path, page: int = 0, cache_dir: Path | None = None) -> tuple[str, list[dict]]:
    """OCR one image (OpenAI vision, app/ocr.py). Returns (reading-order text, positioned lines)."""
    lines = _page_lines(ocrmod.ocr(path, page=page, cache_dir=cache_dir))
    return ocrmod.rows_text(lines), lines


def pdf_text_and_pages(path: Path, workdir: Path) -> tuple[list[str], bool, list]:
    """Returns (rendered page image paths, has_text_layer, parts). `parts` has one entry per page: the text-layer
    lines, or a Future of the OCR result for pages without a usable text layer (scans, screenshots printed to PDF).
    OCR futures are resolved by `ingest` so all pages of a case are read in parallel."""
    doc = pymupdf.open(str(path))
    pages, parts, layer_pages = [], [], 0
    for i, p in enumerate(doc):
        if i >= MAX_PDF_PAGES:
            break
        out = workdir / f"{path.stem}_p{i + 1}.png"
        p.get_pixmap(dpi=OCR_DPI).save(str(out))
        pages.append(str(out))
        pl = _norm_lines(ocrmod.pdf_page_lines(p, i))
        n_chars = len("".join(l["text"] for l in pl).strip())
        page_area = abs(p.rect.width * p.rect.height) or 1
        img_area = sum(abs((b["bbox"][2] - b["bbox"][0]) * (b["bbox"][3] - b["bbox"][1]))
                       for b in p.get_image_info() if b.get("bbox"))
        # browser "print to PDF" of a screenshot / scanned page: only a URL header is real text → OCR the page
        if n_chars >= 200 or (n_chars >= 40 and img_area < 0.3 * page_area):
            layer_pages += 1
            # text-layer coordinates are in PDF points; scale to the rendered image so all lines share units
            k = OCR_DPI / 72
            for l in pl:
                l["box"] = [c * k for c in l["box"]]
            parts.append(pl)
        else:
            parts.append(ocrmod.submit(out, page=i, cache_dir=workdir))
    return pages, layer_pages > 0 and layer_pages == len(pages), parts


def normalise_image(path: Path, workdir: Path) -> Path:
    if path.suffix.lower() in (".jpg", ".jpeg", ".png"):
        return path
    out = workdir / (path.stem + ".png")
    Image.open(path).convert("RGB").save(out)
    return out


RULES = {
    "verification_report": [r"genuineness verification", r"verification report", r"verified date", r"status\s*genuine",
                            r"verifier details", r"app(lication)? no", r"\bis\s+genuine\b|\bgenuine\s+and\b",
                            r"found\s+correct|as per (our|the) (office )?records", r"with reference to",
                            r"(academic|educational|certificate|degree)\s+(record\s+)?verification|verification of",
                            r"dear\s+sir|sir\s*/\s*madam", r"bona\s*fide|has completed|qualified for the degree"],
    "mail_screenshot": [r"\breply all\b", r"\bforward\b", r"\breply\b", r"^\s*cc\b", r"^\s*to\b"],
    "transcript": [r"statement of (grades|marks)", r"grade point", r"cgpa|cumulative grade", r"semester|\bsem\b",
                   r"transcript", r"course (code|title)", r"marks? (sheet|statement)", r"credits?"],
    "degree": [r"hereby", r"syndicate", r"admitted to the", r"degree of", r"conferred", r"given under the seal",
               r"vice.?chancellor", r"convocation"],
    "diploma": [r"\bdiploma\b", r"technical education", r"board of"],
}
NAME_HINTS = {"degree": r"degree|certificate|ecert|provisional", "transcript": r"mark|transcript|grade|tcer|semester",
              "diploma": r"diploma", "verification_report": r"revert|verif|genuine|coe_", "mail_screenshot": r"mail|revert"}


def classify(text: str, filename: str) -> tuple[str, dict]:
    t = text.lower()
    scores = {}
    for kind, pats in RULES.items():
        scores[kind] = sum(1 for p in pats if re.search(p, t, re.M))
    fn = filename.lower()
    for kind, p in NAME_HINTS.items():
        if re.search(p, fn):
            scores[kind] = scores.get(kind, 0) + 1
    # tie-breakers grounded in the document semantics
    if scores["diploma"] >= 2 and "degree of" not in t:
        scores["diploma"] += 2
    if scores["verification_report"] >= 3:
        scores["verification_report"] += 3
    # a letter addressed to us that confirms a degree is a revert, not the degree itself
    if re.search(r"helloverify|hello verify", t) and scores["verification_report"] >= 2 and "degree" in scores:
        scores["degree"] = min(scores["degree"], scores["verification_report"] - 1)
    if scores["mail_screenshot"] >= 3:
        scores["mail_screenshot"] += 2
    kind = max(scores, key=scores.get)
    if scores[kind] < 2:
        kind = "other"
    return kind, scores


def ingest(files: list[Path], workdir: Path) -> tuple[list[dict], list[dict]]:
    """Returns (documents, mails). Mails are effective (non-wrapper) mails with role initiation/revert."""
    docs, mails = [], []
    counter = [0]

    def add_doc(path: Path, origin: str, parent: str | None = None):
        counter[0] += 1
        did = f"d{counter[0]}"
        ext = path.suffix.lower()
        rec = {"id": did, "name": path.name, "path": str(path), "ext": ext, "origin": origin, "parent": parent,
               "text": "", "pages": [], "text_layer": False, "lines": []}
        if ext == ".pdf":
            rec["pages"], rec["text_layer"], rec["_parts"] = pdf_text_and_pages(path, workdir)
        elif ext in IMG_EXT:
            p = normalise_image(path, workdir)
            rec["pages"] = [str(p)]
            rec["_parts"] = [ocrmod.submit(p, page=0, cache_dir=workdir)]
        docs.append(rec)
        return rec

    for f in files:
        f = Path(f)
        if f.suffix.lower() in (".msg", ".eml"):
            root = mailmod.parse_file(f, workdir / f"mail_{f.stem[:40]}")
            for m in mailmod.effective_mails(root):
                counter[0] += 1
                m["id"] = f"m{counter[0]}"
                m["role"] = mailmod.role_of(m)
                m["file"] = f.name
                m["attachment_docs"] = []
                mails.append(m)
                for a in m["attachments"]:
                    rec = add_doc(Path(a["path"]), origin=f"attachment of mail '{m['subject'][:60]}'", parent=m["id"])
                    m["attachment_docs"].append(rec["id"])
        else:
            add_doc(f, origin="upload")

    # resolve OCR (pages were submitted in parallel above), then classify
    for rec in docs:
        texts, lines, usd, errors = [], [], 0.0, []
        for part in rec.pop("_parts", []):
            if isinstance(part, list):
                pl = part
            else:
                res = part.result()
                usd += res["usd"]
                if res["error"]:
                    errors.append(res["error"])
                pl = _page_lines(res)
            lines += pl
            texts.append(ocrmod.rows_text(pl))
        rec["text"], rec["lines"] = "\n".join(texts), lines
        rec["ocr_usd"], rec["ocr_errors"] = round(usd, 5), errors
        rec["ocr_score"] = ocrmod.mean_score(rec["lines"])
        rec["kind"], rec["scores"] = classify(rec["text"], rec["name"])
    return docs, mails
