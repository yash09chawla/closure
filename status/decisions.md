# Decisions (with reasons)

1. **Standalone FastAPI + vanilla JS replica**, not a copy of the Angular bundle. The saved Angular JS cannot run offline without its backend; a hand-built replica with the same labels/sections/colours is controllable and demo-safe.
2. **No browser for searching.** UGC is queried through its own JSON endpoint; AICTE is a text PDF indexed locally. A headless browser is used only to *capture* evidence (UGC page screenshot) and to print HTML → PDF.
3. **AICTE evidence rendered straight from the official PDF** with PyMuPDF (page render + highlight of the matched row), framed in a Chrome-PDF-viewer style bar showing the real URL and page number. Faster and sharper than screenshotting a browser PDF viewer.
4. **Passing criteria via OpenAI `web_search` restricted to the university's official domain** (domain comes from UGC record / revert email domain). Free scraping (DuckDuckGo/Bing) was tested and blocked. The returned URL is rejected if it is not on the allowed domain, and the criteria text must be found in the downloaded document — otherwise the field is flagged, not filled.
5. **Knowledge cache** (`data/knowledge/*.json`) per university+programme+regulation — repeat universities cost $0 and take ~1 s.
6. **One vision call for degree + transcript** (images downscaled to ≤1600 px). Tesseract text is passed as a hint. Without an API key, regex on Tesseract output is the fallback.
7. **Mail PDFs are printed at content size** (custom page height) so landscape Outlook layouts are never cut.
8. **Precedent defaults** taken from the ops-filled HTML (e.g. "Are the transcripts in English or Arabic? → No", Branch/Examination location → country) live in `app/mapper.py` `DEFAULTS` so ops can change them in one place.
9. **Nothing invented.** If a fact is missing (e.g. no initiation mail in the sample) the field stays empty and is flagged for the reviewer.
10. **Dropdown option lists are partial** — only options seen in the HTML/PDF plus obvious siblings. Real HVOPS lists may contain more (UNVERIFIED).
11. **No candidate data to OpenAI — enforced in code (2026-11-23).** Documents are read by a local OCR model
    (RapidOCR + PP-OCRv6 small, ONNX on CPU); degree/transcript/revert are structured by layout + rule parsers.
    `app/llm.py` only offers web search; every prompt passes `app/privacy.py` (generic PII patterns + the identifiers
    of the case being processed) and is written to an audit log. A blocked prompt is never sent.
12. **PP-OCRv6 small via RapidOCR** rather than Tesseract / EasyOCR / a vision LLM: best accuracy on phone photos and
    tables among small CPU models, pip-only on Windows, models bundled in the wheel (works without network). Tesseract
    produced unusable text on the phone-photo marksheet.
13. **Rules, not a local LLM, for structuring.** The fields that decide the closure come from the university revert;
    rule parsers are deterministic, explainable and fast (<1 s). A local LLM (e.g. via Ollama) remains an option for
    free-text reverts the rules miss — only if measured to help.
14. **Two research services with public inputs only**: `AccreditationQuery` (institution, college, programme, state)
    and `PassingQuery` (institute, degree, major, mode, duration, regulation, years, affiliated). Both are usable
    stand-alone (`/research`, `/api/research/*`) and from the pipeline.
15. **OpenAI never decides accreditation.** It may only suggest an institution's official / former names; those names
    are matched again against the official UGC / AICTE lists. Not found → Non-Accredited with an evidence PDF showing
    the UGC searches returning no records.
16. **Official domain for passing criteria**: UGC record website → university e-mail domain → OpenAI lookup accepted
    only for academic domains (.ac.in / .edu / .edu.xx / .ac.xx …) and never directory sites.
17. **The revert outranks OCR for the degree title** unless the title was read from the degree certificate itself
    (a "BE" transcript header is not proof of the degree; PRIST's revert says B.Tech EEE). Differences are flagged.
18. **Seat / exam numbers are not registration numbers** and are never cross-checked against the revert's PRN.
19. **Python 3.14** (onnxruntime has no 3.15 wheels). Pinned requirements.
20. **Document OCR by OpenAI vision (2026-11-25, owner's decision) — supersedes 11 and 12.** Page images are sent to
    `gpt-5.4-mini` (detail "original", reasoning effort none, strict JSON schema: rows of cells). Local OCR
    (RapidOCR) is removed. The same layout + rule parsers structure the text, so no model interprets the fields.
    OCR calls are audited without content (model, image hash, cost); research prompts are still privacy-guarded.
    The model gives no coordinates → line boxes are synthetic row/column positions; scanned regulation evidence
    quotes the clause instead of drawing a highlight. Measured: Gothic degree titles now read; watermarked scans
    (IGNOU) are read *confidently wrong* (invented names/branch), so the revert stays the authority.
