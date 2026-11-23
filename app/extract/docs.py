"""Ingest uploaded files → flat list of documents with text + classification.

Kinds: degree | transcript | diploma | verification_report | mail | mail_screenshot | other
"""
import re
import subprocess
import unicodedata
from pathlib import Path

import pymupdf
from PIL import Image

from . import mail as mailmod

IMG_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp", ".heic"}


def norm_text(t: str) -> str:
    return unicodedata.normalize("NFKC", t or "")


def ocr_image(path: Path) -> str:
    try:
        r = subprocess.run(["tesseract", str(path), "-", "--psm", "3"], capture_output=True, text=True, timeout=60)
        return norm_text(r.stdout)
    except Exception:
        return ""


def pdf_text_and_pages(path: Path, workdir: Path, render: bool = True) -> tuple[str, list[str], bool]:
    """Returns (text, rendered page image paths, has_text_layer)."""
    doc = pymupdf.open(str(path))
    text = norm_text("\n".join(p.get_text() for p in doc))
    has_text = len(text.strip()) > 60
    pages = []
    if render or not has_text:
        for i, p in enumerate(doc):
            if i >= 4:
                break
            out = workdir / f"{path.stem}_p{i + 1}.png"
            p.get_pixmap(dpi=150).save(str(out))
            pages.append(str(out))
    if not has_text:
        text = "\n".join(ocr_image(Path(pg)) for pg in pages)
    return text, pages, has_text


def normalise_image(path: Path, workdir: Path) -> Path:
    if path.suffix.lower() in (".jpg", ".jpeg", ".png"):
        return path
    out = workdir / (path.stem + ".png")
    Image.open(path).convert("RGB").save(out)
    return out


RULES = {
    "verification_report": [r"genuineness verification", r"verification report", r"verified date", r"status\s*genuine",
                            r"verifier details", r"app(lication)? no"],
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
               "text": "", "pages": [], "text_layer": False}
        if ext == ".pdf":
            rec["text"], rec["pages"], rec["text_layer"] = pdf_text_and_pages(path, workdir)
        elif ext in IMG_EXT:
            p = normalise_image(path, workdir)
            rec["pages"] = [str(p)]
            rec["text"] = ocr_image(p)
        else:
            rec["text"] = ""
        rec["kind"], rec["scores"] = classify(rec["text"], path.name)
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
    return docs, mails
