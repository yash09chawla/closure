"""Official accreditation sources, downloaded once and cached locally (refreshed weekly).

UGC   : JSON endpoint behind ugc.gov.in/universitydetails (Central/State/State Private/Deemed)
AICTE : 2025-26 Groupwise list of approved institutions (287-page text PDF) → row index
"""
import json
import re
import threading
import time
from pathlib import Path

import httpx
import pymupdf

from .. import config

_lock = threading.Lock()
_mem = {}


def _fresh(p: Path) -> bool:
    return p.exists() and (time.time() - p.stat().st_mtime) < config.SOURCE_MAX_AGE_DAYS * 86400


def fetch(url: str, timeout=60, headers: dict | None = None) -> tuple[bytes, str]:
    """GET with sane fallbacks: strict TLS → relaxed TLS (some .ac.in certs are broken) → curl."""
    h = {"User-Agent": config.UA, **(headers or {})}
    last = None
    for verify in (True, False):
        try:
            with httpx.Client(headers=h, follow_redirects=True, timeout=timeout, verify=verify) as c:
                r = c.get(url)
                r.raise_for_status()
                return r.content, r.headers.get("content-type", "")
        except httpx.HTTPStatusError:
            raise
        except Exception as e:  # TLS / timeout → next strategy
            last = e
    import subprocess
    r = subprocess.run(["curl", "-sSL", "-m", str(timeout), "-A", config.UA, url], capture_output=True)
    if r.returncode == 0 and r.stdout:
        return r.stdout, ""
    raise RuntimeError(f"download failed for {url}: {last}")


def download(url: str, dest: Path, timeout=90) -> Path:
    data, _ = fetch(url, timeout)
    dest.write_bytes(data)
    return dest


def norm(name: str) -> str:
    s = (name or "").upper().replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    s = re.sub(r"\b(THE)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def ugc_lists() -> dict[int, list[dict]]:
    with _lock:
        if "ugc" in _mem:
            return _mem["ugc"]
        out = {}
        for t in config.UGC_TYPES:
            p = config.SOURCES / f"ugc_{t}.json"
            if not _fresh(p):
                try:
                    raw, _ = fetch(config.UGC_API.format(t=t), 40, {"X-Requested-With": "XMLHttpRequest"})
                    data = json.loads(raw)
                    if data.get("List"):
                        p.write_text(json.dumps(data["List"]))
                except Exception:
                    pass  # fall back to stale cache if present
            out[t] = json.loads(p.read_text()) if p.exists() else []
        _mem["ugc"] = out
        return out


# AICTE column x0 boundaries (verified on the 2025-26 PDF)
COLS = [("sr", 0, 45), ("aicte_id", 45, 110), ("name", 110, 275), ("region", 275, 328), ("state", 328, 390),
        ("district", 390, 458), ("city", 458, 525), ("group", 525, 9999)]


def aicte_pdf() -> Path:
    p = config.SOURCES / "aicte_groupwise_2025_26.pdf"
    if not _fresh(p) or p.stat().st_size < 100000:
        try:
            download(config.AICTE_LIST, p, timeout=120)
        except Exception:
            if not p.exists():
                raise
    return p


def aicte_notice_pdf() -> Path:
    p = config.SOURCES / "aicte_public_notice_2025_26.pdf"
    if not _fresh(p):
        try:
            download(config.AICTE_NOTICE, p)
        except Exception:
            if not p.exists():
                raise
    return p


def aicte_index() -> list[dict]:
    with _lock:
        if "aicte" in _mem:
            return _mem["aicte"]
        pdf = aicte_pdf()
        idx_p = config.SOURCES / "aicte_index.json"
        if idx_p.exists() and idx_p.stat().st_mtime >= pdf.stat().st_mtime:
            rows = json.loads(idx_p.read_text())
        else:
            rows = []
            doc = pymupdf.open(str(pdf))
            for pno, page in enumerate(doc):
                words = page.get_text("words")
                # Row anchors = Sr.No cells; every other word joins the vertically nearest anchor.
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
                    cells = {k: [] for k, _, _ in COLS}
                    for w in ws:
                        for k, lo, hi in COLS:
                            if lo <= w[0] < hi:
                                cells[k].append(w[4])
                                break
                    sr = " ".join(cells["sr"])
                    if not sr.isdigit() or not cells["name"]:
                        continue
                    x0 = min(w[0] for w in ws); y0 = min(w[1] for w in ws)
                    x1 = max(w[2] for w in ws); y1 = max(w[3] for w in ws)
                    row = {k: " ".join(v) for k, v in cells.items()}
                    row.update(page=pno + 1, bbox=[x0, y0, x1, y1], norm=norm(row["name"]))
                    rows.append(row)
            idx_p.write_text(json.dumps(rows))
        _mem["aicte"] = rows
        _mem["aicte_pages"] = pymupdf.open(str(pdf)).page_count
        return rows


def aicte_page_count() -> int:
    aicte_index()
    return _mem.get("aicte_pages", 0)


def warm():
    """Pre-load all sources (called at server start in a thread)."""
    try:
        ugc_lists()
    except Exception:
        pass
    try:
        aicte_index()
        aicte_notice_pdf()
    except Exception:
        pass
