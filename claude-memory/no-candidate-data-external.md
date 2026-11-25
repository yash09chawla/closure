---
name: no-candidate-data-external
description: "Document OCR goes to OpenAI (owner's choice, 2026-11-25); research prompts must still carry general info only; don't publish candidate files"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 1fad8a76-60a4-4fbd-aa32-ff09937c0e86
  modified: 2026-11-25T05:09:03.304Z
---

**Current rule (2026-11-25):** the user told me to "remove local OCR … make the system use OPEN AI API KEY for OCR
again". Candidate document page images are now sent to OpenAI vision for OCR (`app/ocr.py` → `llm.vision_ocr`).
Local OCR (RapidOCR) was deleted and archived in `.archive/local-ocr/`. Don't reintroduce local OCR unless asked.

Still in force:
- Research prompts (accreditation, passing criteria) carry only general programme info (institution, degree, major,
  mode, duration, regulation year), checked by `app/privacy.py` through `llm.web_search_json`. Never put OCR text,
  names or register numbers in them.
- OCR calls are audited without content (model, image hash, cost).
- Treat committing or publishing candidate files (e.g. `Cases/` or `data/cases/` to the GitHub remote) as off-limits:
  flag it, don't do it.

**Why:** the earlier rule (2026-11-20 / 23, "no document to OpenAI") was the user's own. They reversed it on
2026-11-25 after Azure Document Intelligence turned out unreachable ([[azure-doc-intelligence]]). A BGV company still
must not leak candidate data into search queries or public repos.
**How to apply:** for OCR changes in [[hv-closure-prototype]], OpenAI is the engine. For any new outbound call that
isn't OCR, route it through the privacy guard.
