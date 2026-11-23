"""Thin OpenAI wrapper: JSON extraction (text/vision) and domain-locked web search.
Tracks token usage so the UI can show cost per case."""
import base64
import io
import json
import re
import time

from PIL import Image

from . import config

_client = None

# USD per 1M tokens (input, output) — approximate list prices, used only for the demo cost display.
PRICES = {"gpt-4.1-mini": (0.40, 1.60), "gpt-5.4-mini": (0.75, 4.50), "gpt-4o-mini": (0.15, 0.60)}
WEB_SEARCH_CALL_USD = 0.01


def client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=90)
    return _client


def available() -> bool:
    return config.USE_LLM


def _cost(model, usage, searches=0):
    pi, po = PRICES.get(model, (1.0, 4.0))
    it = getattr(usage, "input_tokens", 0) or 0
    ot = getattr(usage, "output_tokens", 0) or 0
    return round(it / 1e6 * pi + ot / 1e6 * po + searches * WEB_SEARCH_CALL_USD, 5), it, ot


def image_to_data_url(path, max_side=1600) -> str:
    im = Image.open(path)
    im = im.convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _parse_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


def extract_json(prompt: str, images: list[str] | None = None, schema: dict | None = None,
                 model: str | None = None) -> tuple[dict, dict]:
    """Returns (data, meta). images = list of file paths."""
    model = model or config.EXTRACT_MODEL
    content = [{"type": "input_text", "text": prompt}]
    for p in images or []:
        content.append({"type": "input_image", "image_url": image_to_data_url(p), "detail": "high"})
    kwargs = {}
    if schema:
        kwargs["text"] = {"format": {"type": "json_schema", "name": "extraction", "schema": schema, "strict": True}}
    t = time.time()
    try:
        r = client().responses.create(model=model, input=[{"role": "user", "content": content}],
                                      temperature=0, **kwargs)
    except Exception as e:  # some reasoning models reject temperature
        if "temperature" not in str(e):
            raise
        r = client().responses.create(model=model, input=[{"role": "user", "content": content}], **kwargs)
    cost, it, ot = _cost(model, r.usage)
    return _parse_json(r.output_text), {"model": model, "seconds": round(time.time() - t, 1),
                                        "usd": cost, "in": it, "out": ot}


def web_search_json(prompt: str, allowed_domains: list[str], model: str | None = None) -> tuple[dict, dict]:
    model = model or config.SEARCH_MODEL
    t = time.time()
    r = client().responses.create(
        model=model,
        tools=[{"type": "web_search", "filters": {"allowed_domains": allowed_domains}}],
        reasoning={"effort": "low"},
        input=prompt,
    )
    n_search = sum(1 for o in r.output if getattr(o, "type", "") == "web_search_call")
    cost, it, ot = _cost(model, r.usage, n_search)
    return _parse_json(r.output_text), {"model": model, "seconds": round(time.time() - t, 1),
                                        "usd": cost, "in": it, "out": ot, "searches": n_search}
