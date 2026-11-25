"""Outbound privacy guard + audit log.

Rules:
  * 2026-11-25 (owner's decision): candidate DOCUMENT IMAGES are sent to OpenAI for OCR (app/ocr.py →
    llm.vision_ocr). Those calls are audited without content (model, image hash, cost).
  * Research prompts (still guarded) may only contain GENERAL, PUBLIC programme information:
      - accreditation   → university / college name, programme type, state
      - passing criteria → institute, degree, major, study mode, duration, regulation / academic year

Every research request goes through `assert_public()`:
  1. generic patterns that never belong in a research query (e-mail, phone, long ID numbers, birth dates)
  2. the identifiers of the case currently being processed (name, register no., DOB, e-mails), which the
     pipeline registers with `case_identifiers(...)` for the duration of the run (context-local, so concurrent
     cases cannot see each other's identifiers)
A hit raises PrivacyViolation and the request is NOT sent. Every request that is sent is appended to
data/audit/outbound.jsonl (service, time, full prompt) so an auditor can see exactly what left the machine.
"""
import contextvars
import json
import re
import threading
import time
from contextlib import contextmanager

from . import config

AUDIT = config.DATA / "audit"
AUDIT.mkdir(parents=True, exist_ok=True)
_audit_lock = threading.Lock()
_case_ids: contextvars.ContextVar[list[str] | tuple] = contextvars.ContextVar("case_ids", default=())

GENERIC = [
    ("e-mail address", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("phone number", re.compile(r"\+\d{1,3}[\s-]?\d{6,}|(?<![\d-])\d{10}(?![\d-])|\(\d{3,5}\)\s?\d{6,8}")),
    ("ID-like number (7+ digits)", re.compile(r"(?<![\d.])\d{7,}(?![\d.])")),
    ("ID-like code", re.compile(r"\b(?=[A-Z0-9/-]*\d{4,})(?=[A-Z0-9/-]*[A-Z])[A-Z0-9/-]{8,}\b")),
    ("date of birth-like date", re.compile(r"\b\d{1,2}[-/.](?:\d{1,2}|[A-Za-z]{3})[-/.](?:19|20)\d{2}\b")),
]


class PrivacyViolation(Exception):
    pass


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _identifiers(values) -> list[str]:
    ids = []
    for v in values or []:
        v = (v or "").strip()
        if not v:
            continue
        n = _norm(v)
        if re.search(r"\d", n):
            digits = re.sub(r"\D", "", v)
            if len(digits) >= 5:
                ids.append(digits)          # register / roll / PRN numbers, in any formatting
        else:
            toks = [t for t in n.split() if len(t) >= 2]
            if len(toks) >= 2:              # full names: any two consecutive name tokens
                ids += [f"{a} {b}" for a, b in zip(toks, toks[1:])]
            elif toks and len(toks[0]) >= 6:
                ids.append(toks[0])
    return ids


@contextmanager
def case_identifiers(values):
    """Register the current case's personal identifiers while the block runs. The list object is shared by every
    asyncio task started inside the block, so identifiers added later (add_identifiers) are seen by all of them."""
    token = _case_ids.set(list(dict.fromkeys(_identifiers(values))))
    try:
        yield
    finally:
        _case_ids.reset(token)


def add_identifiers(values) -> None:
    """Add identifiers discovered while reading the documents (name on degree, register no., date of birth)."""
    cur = _case_ids.get()
    if isinstance(cur, list):
        cur.extend(i for i in _identifiers(values) if i not in cur)


def problems(text: str) -> list[str]:
    out = [label for label, pat in GENERIC if pat.search(text or "")]
    n = f" {_norm(text)} "
    # digits of every alphanumeric token ("963520103316/RG" → "963520103316"), compared with case numbers
    token_digits = {re.sub(r"\D", "", t) for t in re.findall(r"[A-Za-z0-9/-]+", text or "")}
    for ident in _case_ids.get():
        if ident.isdigit():
            if any(ident in d for d in token_digits if len(d) >= len(ident)):
                out.append("candidate identifier (number)")
        elif f" {ident} " in n:
            out.append("candidate name")
    return out


def assert_public(text: str, service: str) -> None:
    found = problems(text)
    if found:
        raise PrivacyViolation(f"{service}: outbound request blocked — contains {', '.join(sorted(set(found)))}")


def audit(service: str, payload: dict) -> None:
    rec = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "service": service, **payload}
    with _audit_lock, open(AUDIT / "outbound.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
