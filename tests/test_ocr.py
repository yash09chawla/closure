"""OCR module (OpenAI vision) — the API call is mocked; checks row → line geometry, caching and failure handling."""
from PIL import Image

from app import llm, ocr
from app.extract import layout

ROWS = [["ANNA UNIVERSITY"], ["NAME OF THE CANDIDATE", "RAVI KUMAR", "REGISTER NO.", "123456789"],
        ["PROGRAMME & BRANCH", "B.E. Civil Engineering"], ["Classification : FIRST CLASS"]]


def fake(calls):
    def vision_ocr(url, image_sha="", model=None):
        calls.append(image_sha)
        return ROWS, {"model": "test", "usd": 0.001}
    return vision_ocr


def test_rows_become_positioned_lines(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(llm, "vision_ocr", fake(calls))
    monkeypatch.setattr(llm, "available", lambda: True)
    img = Image.new("RGB", (1000, 800), "white")
    res = ocr.ocr(img, cache_dir=tmp_path)
    assert res["text"].splitlines()[1] == "NAME OF THE CANDIDATE\tRAVI KUMAR\tREGISTER NO.\t123456789"
    assert res["usd"] == 0.001 and not res["error"]
    labels = {"NAME OF THE CANDIDATE": "name", "REGISTER NO": "reg", "PROGRAMME & BRANCH": "prog",
              "CLASSIFICATION": "cls"}
    v = layout.values(layout.kv(res["lines"], labels))
    assert v == {"name": "RAVI KUMAR", "reg": "123456789", "prog": "B.E. Civil Engineering", "cls": "FIRST CLASS"}
    # second read of the same image comes from the case cache: no API call, no cost
    again = ocr.ocr(img, cache_dir=tmp_path)
    assert len(calls) == 1 and again["cached"] and again["usd"] == 0 and again["text"] == res["text"]


def test_unreadable_marks_lower_the_score(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "vision_ocr", lambda *a, **k: ([["Reg No 12[?]45"]], {"usd": 0}))
    res = ocr.ocr(Image.new("RGB", (400, 200), "white"))
    assert res["lines"][0]["score"] < 0.85


def test_no_key_means_no_lines_and_a_reason(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: False)
    res = ocr.ocr(Image.new("RGB", (400, 200), "white"))
    assert res["lines"] == [] and "unavailable" in res["error"]


def test_api_error_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: True)

    def boom(*a, **k):
        raise TimeoutError("slow")
    monkeypatch.setattr(llm, "vision_ocr", boom)
    res = ocr.ocr(Image.new("RGB", (400, 200), "white"))
    assert res["lines"] == [] and "TimeoutError" in res["error"]
