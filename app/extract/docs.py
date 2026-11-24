"""Ingest uploaded files → flat list of documents with text + classification.

Kinds: degree | transcript | diploma | verification_report | mail | mail_screenshot | online_portal | other
"""
import re
import subprocess
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymupdf
from PIL import Image

from . import mail as mailmod
from . import online

IMG_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp", ".heic"}


def norm_text(t: str) -> str:
    return unicodedata.normalize("NFKC", t or "")


def ocr_image(path: Path) -> str:
    try:
        r = subprocess.run(["tesseract", str(path), "-", "--psm", "3"], capture_output=True, text=True, timeout=60)
        return norm_text(r.stdout)
    except Exception:
        return ""


def _ocr_quality(img: Image.Image, tmp: Path) -> int:
    """Number of confidently read real words — a cheap orientation score."""
    img.save(tmp)
    try:
        r = subprocess.run(["tesseract", str(tmp), "-", "--psm", "3", "tsv"], capture_output=True, text=True, timeout=60)
    except Exception:
        return 0
    n = 0
    for ln in r.stdout.splitlines()[1:]:
        p = ln.split("\t")
        if len(p) >= 12 and re.fullmatch(r"[A-Za-z]{3,}[.,:]?", p[11].strip()):
            try:
                n += float(p[10]) >= 70
            except ValueError:
                pass
    return n


COMMON = {"the", "of", "and", "in", "to", "is", "that", "this", "has", "been", "for", "on", "with", "by", "date",
           "university", "name", "no", "degree", "certify", "marks", "total", "semester", "college", "examination",
           "status", "year", "course", "grade", "result", "registrar", "controller", "programme", "program", "board",
           "certificate", "statement", "enrolment", "enrollment", "admission", "details", "division", "class"}


def looks_upright(text: str) -> bool:
    words = set(re.findall(r"[a-z]+", (text or "").lower()))
    return len(words & COMMON) >= 5


def _line_orientation(im: Image.Image) -> str:
    """'h' if text lines run horizontally, 'v' if vertically (projection-profile variance of dark pixels)."""
    import numpy as np
    g = np.asarray(im.convert("L").resize((800, int(800 * im.height / max(1, im.width))) if im.width >= im.height
                                          else (int(800 * im.width / max(1, im.height)), 800)), dtype=np.float32)
    dark = (g < g.mean() - 2 * g.std()).astype(np.float32) if g.std() > 1 else (g < 128).astype(np.float32)
    rows, cols = dark.sum(axis=1), dark.sum(axis=0)
    rv = rows.std() / (rows.mean() + 1e-6)
    cv = cols.std() / (cols.mean() + 1e-6)
    return "h" if rv >= cv else "v"


def upright(path: Path, workdir: Path, hint: int | None = None) -> tuple[Path, int]:
    """Scans are often stored sideways (landscape page, portrait certificate). Returns (image path, angle):
    projection profile picks horizontal vs vertical lines, OCR word quality picks between the two candidates."""
    try:
        im = Image.open(path).convert("RGB")
    except Exception:
        return path, 0
    small = im.copy()
    small.thumbnail((1600, 1600))
    tmp = workdir / f"_orient_{path.stem}.png"
    tried = {}

    def q(a):
        if a not in tried:
            tried[a] = _ocr_quality(small.rotate(a, expand=True) if a else small, tmp)
        return tried[a]

    angle = 0
    if hint is not None and q(hint) >= 25:
        angle = hint
    else:
        cands = (0, 180) if _line_orientation(small) == "h" else (90, 270)
        angle = max(cands, key=q)
        if q(angle) < 12:                                  # profile unsure → full search
            angle = max((0, 90, 180, 270), key=q)
        if q(angle) < q(0) + 8:
            angle = 0
    tmp.unlink(missing_ok=True)
    if angle == 0:
        return path, 0
    out = workdir / f"{path.stem}_upright.png"
    im.rotate(angle, expand=True).save(out)
    return out, angle


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
        # keep the short text layer (e.g. the portal URL ops typed above a pasted screenshot)
        texts, hint = [], None
        for k, pg in enumerate(pages):
            t, pages[k], hint = ocr_upright(Path(pg), workdir, hint)
            texts.append(t)
        text = text.strip() + "\n" + "\n".join(texts)
    return text, pages, has_text


def ocr_upright(path: Path, workdir: Path, hint: int | None = None) -> tuple[str, str, int | None]:
    """OCR; if the text does not look like real words, fix the orientation and OCR again.
    Returns (text, image path actually used, angle to try first on the next page).
    With OpenAI OCR on, the vision model reads the pages (any orientation) — Tesseract runs once, only to
    classify the file, and the extra rotation probes are skipped."""
    from .. import config, llm
    if config.CANDIDATE_LLM and llm.available():
        return ocr_image(path), str(path), hint
    try:
        im = Image.open(path).convert("RGB")
        horizontal = _line_orientation(im) == "h"
    except Exception:
        im, horizontal = None, True
    if horizontal:
        t = ocr_image(path)
        if looks_upright(t):
            return t, str(path), hint
    elif im is not None and hint in (90, 270):
        # sideways page of a document whose previous page needed the same rotation → apply it directly
        p2 = path.with_name(f"{path.stem}_upright.png")
        im.rotate(hint, expand=True).save(p2)
        t2 = ocr_image(p2)
        if looks_upright(t2):
            return t2, str(p2), hint
        t = t2
    else:
        t = ""
    p2, angle = upright(path, workdir, hint)
    if p2 != path:
        return ocr_image(p2), str(p2), angle
    return (t or ocr_image(path)), str(path), hint


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
        # content unreadable (e.g. guilloche background) → trust an explicit file name like "Degree.pdf"
        named = [k for k in ("degree", "transcript", "diploma") if re.search(NAME_HINTS[k], fn)]
        kind = named[0] if len(named) == 1 else "other"
    # screenshot of the university's own online portal (browser address bar, "status as on", portal footer)
    ps = online.portal_score(text, filename)
    scores["online_portal"] = ps
    if ps >= 5 and ps > max(scores.get("degree", 0), scores.get("transcript", 0), scores.get("verification_report", 0)):
        kind = "online_portal"
    return kind, scores


def ingest(files: list[Path], workdir: Path) -> tuple[list[dict], list[dict]]:
    """Returns (documents, mails). Mails are effective (non-wrapper) mails with role initiation/revert."""
    docs, mails = [], []
    counter = [0]
    pending = []                      # (rec, path) — read in parallel below (Tesseract runs as a subprocess)

    def add_doc(path: Path, origin: str, parent: str | None = None):
        counter[0] += 1
        did = f"d{counter[0]}"
        rec = {"id": did, "name": path.name, "path": str(path), "ext": path.suffix.lower(), "origin": origin,
               "parent": parent, "text": "", "pages": [], "text_layer": False}
        docs.append(rec)
        pending.append((rec, path))
        return rec

    def read(rec, path):
        ext = rec["ext"]
        if ext == ".pdf":
            rec["text"], rec["pages"], rec["text_layer"] = pdf_text_and_pages(path, workdir)
        elif ext in IMG_EXT:
            p = normalise_image(path, workdir)
            rec["text"], used, _ = ocr_upright(p, workdir)
            rec["pages"] = [used]
        else:
            rec["text"] = ""
        rec["kind"], rec["scores"] = classify(rec["text"], path.name)

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
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(pending)))) as ex:
        list(ex.map(lambda rp: read(*rp), pending))
    return docs, mails


def upright_docs(docs: list[dict], workdir: Path) -> None:
    """Rotate sideways pages of the given documents in place (d['pages']) before they are sent to the vision model.
    Cheap line-direction check per page; OCR probes only for pages whose lines run vertically. Documents in parallel;
    pages of one document share the angle found on its first sideways page."""
    def one(d):
        hint = None
        for i, pg in enumerate(d.get("pages", [])):
            p = Path(pg)
            if p.stem.endswith("_upright"):
                continue
            try:
                if _line_orientation(Image.open(p).convert("RGB")) == "h":
                    continue
            except Exception:
                continue
            p2, angle = upright(p, workdir, hint)
            if p2 != p:
                d["pages"][i], hint = str(p2), angle
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(docs)))) as ex:
        list(ex.map(one, docs))
