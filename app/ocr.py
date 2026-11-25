"""Document OCR via the OpenAI vision model (decided 2026-11-25, replaces the local RapidOCR engine).

Each page image is sent to OpenAI (`config.OCR_MODEL`) with a strict JSON schema: the model returns the page as
visual rows, each row a list of separate text cells (table cells, label / value columns). The rest of the system
(layout label→value extraction, degree / transcript / revert parsers, classifier) works on that structure, so
every line gets a box. The model gives no coordinates, so the boxes are SYNTHETIC: row k of N sits at k/N of the
page height, cell j of a row with M cells spans j/M … (j+1)/M of the width. That keeps "same row", "to the right" and
"directly below" meaningful for the parsers; it is not a pixel position (do not draw highlights from it).

Results are cached per image (sha-256 of the bytes sent) in `cache_dir` when one is given, so re-running a case does
not pay twice. Without an OpenAI key (or HV_DISABLE_LLM=1) OCR returns no lines and `error` says why.
"""
import base64
import hashlib
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageOps

from . import config, llm

MAX_SIDE = 2400          # longest side sent to the model (detail="original" keeps it; marksheet text stays legible)
UNREADABLE = "[?]"
_pool = ThreadPoolExecutor(max_workers=config.OCR_WORKERS, thread_name_prefix="ocr")


def model_info() -> dict:
    return {"engine": "OpenAI vision", "model": config.OCR_MODEL, "detail": config.OCR_DETAIL,
            "network": "OpenAI API (documents are sent to OpenAI)", "available": llm.available()}


def _prepare(img) -> tuple[bytes, tuple[int, int]]:
    im = img if isinstance(img, Image.Image) else Image.open(img)
    im = ImageOps.exif_transpose(im).convert("RGB")
    size = im.size
    if max(size) > MAX_SIDE:
        im = im.copy()
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue(), size


def _lines_from_rows(rows: list[list[str]], size: tuple[int, int], page: int) -> list[dict]:
    w, h = size
    rows = [[c.strip() for c in r if c and c.strip()] for r in rows]
    rows = [r for r in rows if r]
    n = max(1, len(rows))
    rh = h / n
    lines = []
    for k, cells in enumerate(rows):
        m = len(cells)
        y0, y1 = k * rh, k * rh + rh * 0.8
        for j, txt in enumerate(cells):
            cw = w / m
            lines.append({"text": txt, "score": 0.5 if UNREADABLE in txt else 1.0, "page": page,
                          "box": [j * cw, y0, j * cw + cw * 0.95, y1], "row": k})
    return lines


def ocr(img, page: int = 0, cache_dir: Path | None = None) -> dict:
    """img = path or PIL image. Returns {lines, text, seconds, size, usd, model, cached, error}."""
    t = time.time()
    data, size = _prepare(img)
    key = hashlib.sha256(data).hexdigest()[:24]
    cache = Path(cache_dir) / f"ocr_{key}.json" if cache_dir else None
    rows, meta, cached, error = None, {}, False, ""
    if cache and cache.exists():
        try:
            rows, cached = json.loads(cache.read_text(encoding="utf-8"))["rows"], True
        except Exception:
            rows = None
    if rows is None:
        if not llm.available():
            error = "OpenAI key missing or disabled — document OCR unavailable"
            rows = []
        else:
            try:
                rows, meta = llm.vision_ocr("data:image/jpeg;base64," + base64.b64encode(data).decode(),
                                            image_sha=key)
                if cache:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_text(json.dumps({"rows": rows, "model": meta.get("model")}, ensure_ascii=False),
                                     encoding="utf-8")
            except Exception as e:
                error, rows = f"OCR failed: {type(e).__name__}: {str(e)[:200]}", []
    lines = _lines_from_rows(rows, size, page)
    return {"lines": lines, "text": rows_text(lines), "seconds": round(time.time() - t, 2), "size": list(size),
            "usd": 0.0 if cached else meta.get("usd", 0.0), "model": meta.get("model", config.OCR_MODEL),
            "cached": cached, "error": error}


def submit(img, page: int = 0, cache_dir: Path | None = None):
    """Run `ocr` on the shared thread pool (pages of a case are read in parallel). Returns a Future."""
    return _pool.submit(ocr, img, page, cache_dir)


# ---------------------------------------------------------------- layout helpers (also used for PDF text layers)

def rows(lines: list[dict]) -> list[list[dict]]:
    """Group lines into visual rows, each row sorted left→right. OCR lines carry their row number; text-layer
    lines are grouped by y-centre (within ~half a line height)."""
    if not lines:
        return []
    if all("row" in l for l in lines):
        out: dict[tuple, list] = {}
        for l in lines:
            out.setdefault((l.get("page", 0), l["row"]), []).append(l)
        return [sorted(out[k], key=lambda l: l["box"][0]) for k in sorted(out)]
    hs = sorted(l["box"][3] - l["box"][1] for l in lines)
    med = hs[len(hs) // 2] or 10
    res: list[list[dict]] = []
    for l in sorted(lines, key=lambda l: (l.get("page", 0), (l["box"][1] + l["box"][3]) / 2, l["box"][0])):
        yc = (l["box"][1] + l["box"][3]) / 2
        if res:
            row = res[-1]
            ryc = sum((x["box"][1] + x["box"][3]) / 2 for x in row) / len(row)
            if abs(yc - ryc) <= med * 0.55 and row[0].get("page", 0) == l.get("page", 0):
                row.append(l)
                continue
        res.append([l])
    for row in res:
        row.sort(key=lambda l: l["box"][0])
    return res


def rows_text(lines: list[dict]) -> str:
    return "\n".join("\t".join(l["text"] for l in row) for row in rows(lines))


def mean_score(lines: list[dict]) -> float:
    return round(sum(l["score"] for l in lines) / len(lines), 3) if lines else 0.0


def pdf_page_lines(page, page_no: int = 0) -> list[dict]:
    """Text-layer lines of a PyMuPDF page in the same shape as OCR lines (score 1.0). No OCR involved."""
    out = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            txt = "".join(s["text"] for s in ln["spans"]).strip()
            if txt:
                out.append({"text": txt, "score": 1.0, "page": page_no, "box": list(ln["bbox"])})
    return out


if __name__ == "__main__":  # python -m app.ocr <image> — quick manual check (sends the image to OpenAI)
    import sys
    for p in sys.argv[1:]:
        res = ocr(Path(p))
        print(f"== {p}  {len(res['lines'])} cells  {res['seconds']}s  ${res['usd']}  {res['error']}")
        print(res["text"])
