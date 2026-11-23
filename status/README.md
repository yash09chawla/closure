# HV Closure Engine — prototype

Replica of the HVOPS Education closure screen with an engine that fills it automatically.

## Run
```bash
./run.sh            # first run creates .venv and installs requirements
open http://localhost:8000
```
Needs: Python 3.12+, Tesseract (`brew install tesseract`), Google Chrome (used headless).
`OPENAI_API_KEY` in `.env` (optional — without it the engine runs in offline mode).

Env switches: `HV_DISABLE_LLM=1` (force offline), `HV_EXTRACT_MODEL`, `HV_SEARCH_MODEL`, `PORT`.

## Demo script
1. Cases page → **Load Anna University demo case** (or **Inject case** with your own initiation data).
2. In the Auto-Close panel drop the documents (degree, transcript, initiation mail, revert mail —
   `.jpg/.png/.pdf/.msg/.eml`) or click *use sample documents*.
3. **Auto-close this case** → watch the steps; fields fill with a green bar and a source label
   (hover for detail); amber = needs review.
4. Open the generated PDFs from the Documents table (Revert mail, Accreditation, Passing Criteria).
5. Fix anything, **Final Submit** → closure time vs the 15–20 min manual baseline.

To show a *first-time* university lookup (live search, ~25 s) delete its entry in `data/knowledge/passing.json`.

## Status notes
- `research.md` — verified facts about inputs and sources
- `architecture.md` — pipeline and modules
- `decisions.md` — why things are built this way
- `plan.md`, `tasks.md` — progress
- `changes.md` — change log
- `handoff.md` — moving to another machine + latest decisions
