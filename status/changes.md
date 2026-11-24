# Changes log

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

## 2026-11-23 — Online Database verification (branch feature/online-database)
- New document kind `online_portal`: screenshots of the university's own portal (PNG/JPG, or PDFs with pasted
  screenshots + typed URL). Detected by browser address-bar URL + portal markers ("status as on", footer, login).
- `app/extract/online.py` (local Tesseract only): per screenshot → URL (PDF text layer, else 3× address-bar OCR),
  page type (result / admission), enrolment, name (re-OCR of the name cell when the full pass drops it),
  programme, admission year (= study start), valid-upto, status-as-on (= verification date), course table
  (COMPLETED / NOT COMPLETED), regional/study centre, mode of study. Screenshots are merged; a name confirmed by
  two screenshots wins (grade card read "DATEL", admission page "PATEL" → PATEL).
- Pipeline step "Online database"; when there is no e-mail revert the portal facts become the revert
  (`verification_mode = online`). Online-revert PDFs in the ops layout (label + link + screenshot + facts table):
  result page → Revert 1, admission/other pages → Revert 2, originals attached alongside.
- Mapper (online mode): start date from Admission Year, end date from portal year of passing else marksheet
  (flagged), mode of study (explicit on portal, else inferred from open-university / study-centre clues, flagged),
  Verification source ONLINE, Company Domain = portal domain (Official if academic/govt domain or UGC website),
  Result Pass only if record found and all courses completed, Condition status Found on University Website / Not Found,
  payment No (instant online), remarks summarise each portal.
- Accreditation PDF now also records negative searches ("Found in UGC, Not found in AICTE" + AICTE list page with
  0/0 find bar, or UGC search screenshot). Passing criteria not found → "NOT FOUND" note PDF in the slot.
- UI: working tabs; Online Database tab mirrors the E-mail tab (history, Initiate button, per-portal table with
  URL/enrolment/name/programme/status-as-on/PDF/screenshot, "Details fetched" card); auto-selects the tab and the
  "Online instant (no fee)" status. IGNOU demo case + sample documents (Cases/Case5).
- Ingest: sideways scans auto-rotated (projection profile + OCR word quality); files read in parallel;
  short PDF text layer kept when OCR is used. File name decides degree/transcript when content is unreadable.
- Privacy: candidate documents no longer go to the vision LLM unless `HV_CANDIDATE_LLM=1` (same for the free-text
  revert fallback). The key is still used for the public passing-criteria search.
- Fixed known break: sample documents now come from `Cases/Case1` (Anna) / `Cases/Case5` (IGNOU).
- Measured on Case5 (IGNOU, 4 files): ingest 26 s, portal OCR 5 s, 72 fields, 8 docs; passing search ~2 min
  (official prospectus found, numbers not auto-confirmed → flagged). Anna e-mail case unchanged: 79 fields.

## 2026-11-23 (later) — Chrome driver fix + OpenAI OCR (temporary)
- Fixed "Connection closed while reading from the driver" / "handler is closed": Playwright's Node driver needs
  `libatomic.so.1`, missing on this Oracle Linux WSL. `app/evidence/browser.py` now adds `vendor/lib` (git-ignored
  local copy) to `LD_LIBRARY_PATH` when the system has no libatomic, and resets the driver after a failed start
  instead of reusing a dead handle. Permanent fix: `sudo dnf install libatomic`.
- OCR of candidate documents and online-portal screenshots now uses the OpenAI vision model **for now**
  (`HV_CANDIDATE_LLM` defaults on; `=0` → local Tesseract). Portal screenshots: one vision call per document
  (all overlapping parts together, courses de-duplicated); local OCR is the fallback on error.
  Degree/transcript: gaps the model leaves are filled from the local OCR regexes ("vision-llm+ocr").
  Images sent to the model are margin-trimmed and up to 2048 px.
- Measured: IGNOU 98 s / $0.20 / 72 fields; Anna 31 s / $0.06 / 79 fields, passing criteria confirmed again.
- Known: vision model normalised the IGNOU title to "Civil Engineering" (degree says "Civil (Construction
  Management)") — reviewer must check the title.

## 2026-11-24 — speed: parallel portal reading, rotation off the critical path, slower polling
- Portal reading runs as its own task in parallel with degree/transcript reading, accreditation and PDF printing.
  Accreditation starts with the best known university name and re-checks only if the portal names a clearly
  different university. Passing criteria waits for the portal (domain, year).
- With OpenAI OCR on, ingest runs Tesseract once per page (classification only); sideways pages are rotated inside
  the degree/transcript step (parallel, line-direction check first, OCR probes only for vertical pages).
  Skipping rotation entirely was tried and rejected: the vision model then read the certificate no. as the
  enrolment and the issue date as the end date (→ false Discrepancy).
- UI polling: one request every 1.5 s (was 0.45 s), never overlapping, paused while the tab is hidden, stopped when
  the run ends. Measured: 7 requests for an 18 s run, 0 while hidden, 0 after finish.
- Measured IGNOU: everything before passing criteria done at ~36 s (was ~48 s). Passing-criteria web search still
  50–140 s and its result varies run to run (found clause / clause not located).
