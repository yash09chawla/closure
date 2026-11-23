---
name: no-candidate-data-external
description: "Candidate documents (degree, marksheet, revert contents) must never be sent to OpenAI or other external services"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 41494c4e-ace1-4248-9c88-02b4ede0026d
  modified: 2026-11-23T04:22:18.769Z
---

Do not send candidate documents or candidate personal data (degree, marksheet/transcript images, revert e-mail text with
names/roll numbers) to the OpenAI API or any external service. Use local OCR (Tesseract / PaddleOCR / Apple Vision) and,
if structuring is needed, a local model. Public information (university name, programme, regulation year) may still be
used in the passing-criteria web search.

**Why:** the user said explicitly (2026-11-20): "I dont want any candidate document to go to OPENAI API". Privacy of candidate data at a background-verification company.
**How to apply:** when changing extraction code in [[hv-closure-prototype]], replace the vision call in `app/extract/certs.py` and the
free-text revert fallback in `app/extract/revert.py` with local processing. Treat publishing candidate files (e.g. to a public GitHub repo) the same way.
