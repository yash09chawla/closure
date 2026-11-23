# Plan

Goal: working local demo where a case is injected, the 4 documents are dropped in, and the closure form +
all evidence uploads are completed in ≤2 minutes, ready for a human "Final Submit".

## Phases
1. Research & feasibility (sources, parsing, OCR, search) — see `research.md`.
2. Backend engine: ingest → extract → research → map.
3. Evidence generation: mail PDFs, accreditation PDF, passing-criteria PDF.
4. Replica UI: case list, HVOPS case page, Auto-Close panel with live steps and field provenance.
5. End-to-end test on the Anna University sample; measure time & cost.
6. Hardening: offline/no-key fallbacks, caching, error flags.

Progress is tracked in `tasks.md`; every change is logged in `changes.md`.
