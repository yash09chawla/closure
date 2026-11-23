# Handoff — continuing on another machine (2026-11-23)

## Setting up after `git clone`
1. `cp .env.example .env` and put the OpenAI key in it (the real `.env` is never committed).
2. Install Tesseract (`brew install tesseract`) and have Google Chrome installed.
3. `./run.sh` → http://localhost:8000 (first run creates `.venv` from `requirements.txt`).
4. Claude Code memory: copy `claude-memory/*.md` into
   `~/.claude/projects/<slug>/memory/` where `<slug>` = the project's absolute path with every `/` replaced by `-`
   (e.g. `/Users/me/work/closure` → `-Users-me-work-closure`). Create the folder if it doesn't exist.

## State of the code
- Prototype v1 works end to end (see `README.md`, `research.md` → "Measured results").
- Folder layout was reorganised after v1: samples are now in `Cases/Case1…Case4`, HVOPS reference in `HTML/`.
  **Known break:** `app/main.py` `SAMPLE_DIR = config.ROOT / "Case"` must become `Cases/Case1`
  (the "use sample documents" button fails until then).
- `Cases/Case2–4` are new real cases — not yet run through the engine.

## Decisions from the 2026-11-20 discussion (not yet implemented)
1. **No candidate documents to OpenAI.** Degree/marksheet must be read with local OCR
   (Tesseract for clean scans; PaddleOCR — or Apple Vision on Mac — for phone photos/tables), structured by rules
   and optionally a local model (e.g. Qwen 7B via Ollama). The free-text revert fallback must also go local.
   Public info (university, programme, regulation year) may still be used in the passing-criteria search.
   Expected: same accuracy on the key fields (they come from the university revert), somewhat weaker on poor
   photos; slower (10–30 s). Must be measured on real cases before claiming parity.
2. **New universities.** Accreditation already uses full UGC (4 lists) + AICTE (13,694 rows) lists. To add:
   match on revert e-mail domain vs UGC website domain, abbreviation/alias list (VTU, JNTU…),
   yearly AICTE list URL update. Passing criteria is generic; to add: OCR for scanned regulation PDFs,
   grade-based criteria (CGPA/letter grade) in the number check, save manual findings to the knowledge cache.
3. **University not in UGC/AICTE → close anyway.** Set Non-Accredited / NOT DISCLOSED, still produce an
   evidence PDF showing the searches returned nothing, Result from the revert only (no Discrepancy),
   passing criteria still researched — official domain from the revert e-mail domain or a search that only
   accepts `.ac.in / .edu.in / .edu` style domains.
   **Open question to the user:** also check the UGC *fake universities* list and refuse auto-Pass when matched?
