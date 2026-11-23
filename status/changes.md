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
