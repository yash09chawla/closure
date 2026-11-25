# Handoff — continuing on another machine (2026-11-25)

## Setting up after `git clone`
1. `cp .env.example .env` and put the OpenAI key in it (the real `.env` is never committed).
2. Python 3.13/3.14 and Google Chrome installed (no OCR engine to install — OCR is OpenAI).
3. `./run.sh` (macOS/Linux) or `.
un.ps1` (Windows) → http://localhost:8000.
4. Claude Code memory: copy `claude-memory/*.md` into
   `~/.claude/projects/<slug>/memory/` where `<slug>` = the project's absolute path with every `/` replaced by `-`
   (e.g. `/Users/me/work/closure` → `-Users-me-work-closure`). Create the folder if it doesn't exist.

## State of the code (2026-11-25)
- **Local OCR removed on the owner's instruction.** Page images go to OpenAI vision (`app/ocr.py` → `llm.vision_ocr`),
  parsed by the same rules. Decision 11/12 below are superseded by decision 20. The old local module is kept in
  `.archive/local-ocr/` (git-ignored). Azure Document Intelligence (`hvops-doc-intel-uae`) was tested and is blocked:
  private endpoint only, unreachable from the laptop even on GlobalProtect VPN (see research.md).

## State of the code (2026-11-23)
- Documents are read locally (PP-OCRv6 via RapidOCR) and parsed by rules; OpenAI only for the two research services,
  behind the privacy guard (`app/privacy.py`, audit log `data/audit/outbound.jsonl`). See `changes.md` 2026-11-23.
- Decision 1 below ("No candidate documents to OpenAI") is **implemented**. Decision 3 (close non-UGC/AICTE
  universities with a not-found evidence PDF) is implemented for accreditation.
- `Cases/` and `data/cases/` contain real candidate files and are tracked in git (GitHub remote) — see tasks.md.

## State of the code (2026-11-20)
- Prototype v1 works end to end (see `README.md`, `research.md` → "Measured results").
- Folder layout was reorganised after v1: samples are now in `Cases/Case1…Case6`, HVOPS reference in `HTML/`.
  (`SAMPLE_DIR` fixed to `Cases/Case1` on 2026-11-23.)
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
