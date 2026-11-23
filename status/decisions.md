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
