# Changes log

## 2026-11-25 — OCR switched to OpenAI vision (local OCR removed)
- `app/ocr.py` rewritten: page image → `llm.vision_ocr` (strict JSON rows of cells) → lines with synthetic row/column
  boxes, cached per image in the case work folder (`ocr_<sha>.json`), pages of a case read in parallel (6 workers).
- `docs.ingest` submits all OCR pages first, then resolves them; per-document `ocr_usd`, `ocr_errors`. The pipeline adds
  the OCR cost to the case cost and logs OCR errors.
- Removed `rapidocr`, `opencv-python-headless` and RapidOCR's helper packages (numpy / onnxruntime stay: PyMuPDF 2.1
  requires them). Old module archived in `.archive/local-ocr/`.
- Scanned regulation evidence: no highlight rectangles (no pixel boxes); page band + verbatim clause quote.
- `layout.kv`: a value below a label is the cell overlapping the label column most (touching table columns picked
  the neighbour "-" before). Transcript `programme` validated (never "CERTIFICATE NO. : …").
- Status API: `documents_leave_machine: true`, `ocr.engine = OpenAI vision`. UI texts updated. 36 tests.
- E2E (same verdicts as 2026-11-23): Case1 Pass $0.011 · Case2 Pass $0.023 · Case3 Pass $0.018 · Case5 Discrepancy
  (revert "COMPLETED") $0.055. 12–21 s per case.
- Azure Document Intelligence probe: 403 "Public access is disabled" (private endpoint; VPN DNS returns public IP).

## 2026-11-23 — local OCR, privacy guard, research services
- **Documents no longer go to OpenAI.** Removed the vision call (`certs.py`) and the free-text revert LLM fallback
  (`revert.py`); removed `llm.extract_json` / `image_to_data_url` and the `HV_EXTRACT_MODEL` setting.
- New `app/ocr.py`: RapidOCR + PP-OCRv6 small (bundled, offline). Lines keep boxes + confidence; rows rebuilt with TABs.
- `docs.py`: per-page decision text layer vs OCR — pages that are mostly image (browser print of a screenshot with only a
  URL header as text) are OCR-ed. Classifier recognises confirmation letters addressed to HelloVerify as reverts.
- New `app/extract/layout.py`: label → value on positioned lines (same row, stacked, inline/glued, wrapped values centred
  on the label, values split over cells, fuzzy OCR-damaged labels, stop-labels).
- `certs.py` rewritten (rules): degree sentence patterns incl. Gothic-font OCR confusions; transcript layout labels;
  per-field confidence; name candidates; seat no. kept apart from register no.
- `revert.py` rewritten (rules): tables, numbered letters, prose letters, online result pages; status only from explicit
  wording; candidate name located with known names in any order; mode needs context ("Online Verification" ≠ online mode).
- New `app/privacy.py`: outbound guard + `data/audit/outbound.jsonl`; case identifiers registered for each run and
  extended as documents are read (shared across the run's asyncio tasks).
- Accreditation: `AccreditationQuery`; aliases (VTU, AKTU, IGNOU, PRIST …); OpenAI name resolution (public name only)
  when nothing matches, re-matched against the official lists; "Sources consulted" table; not-found evidence with the
  four UGC list searches showing no records.
- Passing criteria: `PassingQuery` (degree, major, mode, duration, regulation, years); official-domain lookup restricted
  to academic domains; cache key includes study mode (regular keys unchanged); cache stores file names (portable);
  scanned regulation PDFs located with local OCR (cached per document, max 16 new pages per lookup); sources table.
- Mapper: revert's degree outranks a transcript header abbreviation (flag on difference); best document name chosen
  against revert/passport when OCR variants differ; low-confidence OCR fields flagged; study mode incl. part-time /
  distance; clearer message when a revert has no genuineness statement.
- API: `POST /api/research/accreditation`, `POST /api/research/passing-criteria`, `/research` page,
  `/research-files/...`; `/api/status` reports OCR engine and that documents do not leave the machine.
- Fixed `SAMPLE_DIR` → `Cases/Case1`. venv rebuilt on Python 3.14; requirements pinned; `run.ps1` for Windows.
- `tests/` (pytest, synthetic data only): 31 tests — privacy guard, layout, parsers, API input checks.
- `.gitignore`: `Cases/`, `data/cases/`, `data/research/`, `data/audit/` (already-tracked files are still tracked).

## 2026-11-20 — prototype v1
- Project scaffold: `app/` (FastAPI engine), `web/` (replica UI), `data/` (runtime), `status/` (these notes), `run.sh`.
- Sources: UGC JSON endpoint + AICTE PDFs cached in `data/sources/` (weekly refresh, stale fallback).
- AICTE index v1 grouped words by text block → lost ~35% of rows (some blocks hold several rows).
  **Fixed** by anchoring on Sr.No cells and assigning words to the nearest row → 13,694/13,694 rows.
- PDF text normalised with NFKC (ligatures like "ﬁ" broke label matching in the Anna report).
- Vision model switched `gpt-4.1-mini` → `gpt-5.4-mini`: same speed (~4 s) and cost, read the
  transcript's semester range correctly (4.1-mini said 1–7, real is 03–08).
- httpx with `verify=False` stalled on cac.annauniv.edu (handshake timeout) while strict TLS worked in 0.6 s →
  shared `sources.fetch()` tries strict TLS, then relaxed, then curl.
- Passing-criteria evidence: screenshot capped in height (block was jumping to page 2); quote trimmed to the
  first sub-clause; whole sub-clause highlighted instead of a short phrase.
- Clause heading matching made tolerant of footnote markers ("7. 157 Passing/Promotion …") after the
  Delhi University test highlighted a neighbouring clause.
- Mapper: falls back to revert text for degree title/level/duration when no degree image is uploaded;
  free-text reverts use the reply date as verification date (LLM had taken the date of HV's request).
- Offline mode: if the regulation year cannot be read, reuse the cached regulation for the same
  university+programme, flagged "regulation year not confirmed".
- UI: case list with KPIs, HVOPS case page, Auto-Close drawer (drop zone, live steps, timer, cost, flags,
  log), field provenance labels, reviewer-edit tracking, Final Submit with closure time.
