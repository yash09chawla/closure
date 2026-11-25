# HV Closure Engine — prototype

Replica of the HVOPS Education closure screen with an engine that fills it automatically.

## Run
```bash
./run.sh            # macOS / Linux — first run creates .venv and installs requirements
.
un.ps1           # Windows PowerShell
# → http://localhost:8000   (research tools: http://localhost:8000/research)
```
Needs: **Python 3.13 or 3.14**, Google Chrome (used headless).
`OPENAI_API_KEY` in `.env` is **required for reading documents**: page images are sent to OpenAI for OCR
(`app/ocr.py`, since 2026-11-25). PDFs with a real text layer are read directly. Research (accreditation /
passing criteria) also uses OpenAI, with general programme information only. Without a key, scanned documents and
photos cannot be read and research runs from the cache.

Env switches: `HV_DISABLE_LLM=1` (no OpenAI at all), `HV_OCR_MODEL`, `HV_OCR_DETAIL`, `HV_OCR_WORKERS`,
`HV_SEARCH_MODEL`, `PORT`.
Tests: `.venv/Scripts/python -m pytest tests` (install `requirements-dev.txt`).

## Demo script
1. Cases page → **Load Anna University demo case** (or **Inject case** with your own initiation data).
2. In the Auto-Close panel drop the documents (degree, transcript, initiation mail, revert mail —
   `.jpg/.png/.pdf/.msg/.eml`) or click *use sample documents*.
3. **Auto-close this case** → watch the steps; fields fill with a green bar and a source label
   (hover for detail); amber = needs review.
4. Open the generated PDFs from the Documents table (Revert mail, Accreditation, Passing Criteria).
5. Fix anything, **Final Submit** → closure time vs the 15–20 min manual baseline.

Research tools page (`/research`): accreditation check and passing-criteria lookup from general information only
(institution, degree, major, mode, duration, regulation) — each produces an evidence PDF.

To show a *first-time* university lookup (live search, ~25 s) delete its entry in `data/knowledge/passing.json`.

## Status notes
- `research.md` — verified facts about inputs and sources
- `architecture.md` — pipeline and modules
- `decisions.md` — why things are built this way
- `plan.md`, `tasks.md` — progress
- `changes.md` — change log
- `handoff.md` — moving to another machine + latest decisions
