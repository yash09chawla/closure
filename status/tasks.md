# Tasks

## Done (2026-11-20)
- [x] Read HVOPS.html / HVOSP_HTML.pdf → field list, sections, document slots, ops precedent values
- [x] Verify every source live (UGC JSON API, AICTE PDFs, Anna University regulations, search options)
- [x] Ingest: .msg → nested .eml → attachments; PDFs (text layer first, OCR fallback); images (Tesseract)
- [x] Document classifier (degree / transcript / diploma / verification report / mail screenshot / mail)
- [x] Revert parser: deterministic table parser + LLM fallback for free-text replies
- [x] Degree + transcript extraction: one vision call (`gpt-5.4-mini`), regex fallback offline
- [x] Accreditation: UGC (4 lists) + AICTE (13,694 rows indexed) matching; evidence PDF with framed captures
- [x] Passing criteria: domain-locked web search → download → clause locate + highlight → number check → evidence PDF
- [x] Knowledge cache for passing criteria (exact key + "regulation unknown" fallback, flagged)
- [x] Mail → PDF in Outlook layout, page sized to content (no cropping)
- [x] Mapper: 79 HVOPS fields with source/note/flag, cross-checks (name, reg. no., year, class, status, domain)
- [x] HVOPS replica UI (case list, case page, documents table, Final Submit) + Auto-Close panel
- [x] End-to-end tests: Anna sample (UI + API), synthetic free-text case, offline mode

## Open / next
- [ ] Get real HVOPS dropdown option lists (current lists = seen values + guesses)
- [ ] Test on more real cases (Case1, Case2 … folders) — only one real sample so far
- [ ] Confirm ops conventions with the team: "English or Arabic? → No", Branch/Exam location = country,
      "Condition status = Found in Verification Revert", Award Date = exam year (not issue date)
- [ ] Initiation mail: ask initiation team to always forward it (sample had none)
- [ ] Non-Indian universities (no UGC/AICTE) → needs a different accreditation source list
- [ ] HTML regulation pages (code path exists, not yet exercised by a real case)
- [ ] Production path: push values into real HVOPS via its API instead of the replica
