"""OpenAI wrapper — two uses:

1. `vision_ocr`  — document OCR (decided 2026-11-25): candidate document page images are sent to OpenAI and
   transcribed into rows of text cells. Each call is written to the audit log WITHOUT its content (service, model,
   image hash, cost), so the log itself holds no candidate data.
2. `web_search_json` — accreditation + passing-criteria research. These prompts must contain only general, public
   programme information: they pass the privacy guard (app/privacy.py) before sending, and the full prompt is audited.
Token usage is tracked so the UI can show the OpenAI cost per case.
"""
import json
import re
import time

from . import config, privacy

_client = None

# USD per 1M tokens (input, output) — approximate list prices, used only for the cost display.
PRICES = {"gpt-4.1-mini": (0.40, 1.60), "gpt-5.4-mini": (0.75, 4.50), "gpt-4o-mini": (0.15, 0.60)}
WEB_SEARCH_CALL_USD = 0.01

OCR_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["rows"],
              "properties": {"rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}}}}
OCR_PROMPT = (
    "You are an OCR engine. Transcribe ALL printed, stamped and handwritten text in the image exactly as it appears, "
    "top to bottom. Return one entry per visual line in `rows`; each entry is the list of separate text cells on that "
    "line from left to right (table cells, label and value columns, and separate blocks on the same line are separate "
    "cells; a label and its value printed together like 'Name : X' stay one cell). Copy spelling, capitalisation, "
    "punctuation, numbers, dates and codes exactly; do not correct, translate, summarise, explain or add anything. "
    "Ignore watermarks and background patterns. Write [?] for a character you cannot read. "
    "If the image has no text, return an empty list.")


def client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=180, max_retries=3)
    return _client


def available() -> bool:
    return config.USE_LLM


def _cost(model, usage, searches=0):
    pi, po = PRICES.get(model, (1.0, 4.0))
    it = getattr(usage, "input_tokens", 0) or 0
    ot = getattr(usage, "output_tokens", 0) or 0
    return round(it / 1e6 * pi + ot / 1e6 * po + searches * WEB_SEARCH_CALL_USD, 5), it, ot


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


def vision_ocr(image_data_url: str, image_sha: str = "", model: str | None = None) -> tuple[list[list[str]], dict]:
    """Transcribe one page image. Returns (rows of cells, meta). The image (candidate document) is sent to OpenAI."""
    if not available():
        raise RuntimeError("OpenAI is disabled (no OPENAI_API_KEY or HV_DISABLE_LLM=1)")
    model = model or config.OCR_MODEL
    kw = dict(model=model,
              input=[{"role": "user", "content": [
                  {"type": "input_text", "text": OCR_PROMPT},
                  {"type": "input_image", "image_url": image_data_url, "detail": config.OCR_DETAIL}]}],
              text={"format": {"type": "json_schema", "name": "ocr", "schema": OCR_SCHEMA, "strict": True}})
    t = time.time()
    try:
        r = client().responses.create(reasoning={"effort": config.OCR_EFFORT}, **kw)
    except Exception as e:   # model without that reasoning effort (or a non-reasoning model)
        if "reasoning" not in str(e) and "effort" not in str(e):
            raise
        r = client().responses.create(**kw)
    cost, it, ot = _cost(model, r.usage)
    meta = {"model": model, "seconds": round(time.time() - t, 1), "usd": cost, "in": it, "out": ot,
            "service": "document-ocr"}
    privacy.audit("document-ocr", {"model": model, "image_sha256": image_sha, "usd": cost, "in": it, "out": ot})
    return _parse_json(r.output_text).get("rows", []), meta


def web_search_json(prompt: str, allowed_domains: list[str] | None, service: str,
                    model: str | None = None) -> tuple[dict, dict]:
    """Web search answered as JSON. allowed_domains=None → open web (used only to resolve public facts such as an
    institution's official website; results are always re-validated against official sources by the caller).
    Raises privacy.PrivacyViolation (request not sent) if the prompt contains personal data."""
    if not available():
        raise RuntimeError("OpenAI research is disabled (no OPENAI_API_KEY or HV_DISABLE_LLM=1)")
    privacy.assert_public(prompt, service)
    model = model or config.SEARCH_MODEL
    tool = {"type": "web_search"}
    if allowed_domains:
        tool["filters"] = {"allowed_domains": allowed_domains}
    t = time.time()
    r = client().responses.create(model=model, tools=[tool], reasoning={"effort": "low"}, input=prompt)
    n_search = sum(1 for o in r.output if getattr(o, "type", "") == "web_search_call")
    cost, it, ot = _cost(model, r.usage, n_search)
    meta = {"model": model, "seconds": round(time.time() - t, 1), "usd": cost, "in": it, "out": ot,
            "searches": n_search, "service": service}
    privacy.audit(service, {"model": model, "allowed_domains": allowed_domains or "open web", "prompt": prompt,
                            "usd": cost})
    return _parse_json(r.output_text), meta
