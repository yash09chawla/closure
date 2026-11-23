"""Case persistence: one folder per case under data/cases/<id>/ with case.json."""
import json
import re
import threading
import time
from pathlib import Path

from .config import CASES

_lock = threading.RLock()


def slug(case_ref: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", case_ref).strip("-")


def case_dir(cid: str) -> Path:
    d = CASES / cid
    d.mkdir(parents=True, exist_ok=True)
    return d


def uploads_dir(cid: str) -> Path:
    d = case_dir(cid) / "uploads"
    d.mkdir(exist_ok=True)
    return d


def work_dir(cid: str) -> Path:
    d = case_dir(cid) / "work"
    d.mkdir(exist_ok=True)
    return d


def out_dir(cid: str) -> Path:
    d = case_dir(cid) / "output"
    d.mkdir(exist_ok=True)
    return d


def load(cid: str) -> dict | None:
    p = CASES / cid / "case.json"
    if not p.exists():
        return None
    with _lock:
        return json.loads(p.read_text())


def save(case: dict) -> dict:
    with _lock:
        case["updated_at"] = time.time()
        p = case_dir(case["id"]) / "case.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(case, indent=2, default=str))
        tmp.replace(p)
    return case


def update(cid: str, fn) -> dict:
    with _lock:
        case = load(cid)
        fn(case)
        return save(case)


def list_cases() -> list[dict]:
    out = []
    for p in sorted(CASES.glob("*/case.json")):
        try:
            out.append(json.loads(p.read_text()))
        except Exception:
            pass
    out.sort(key=lambda c: c.get("created_at", 0), reverse=True)
    return out
