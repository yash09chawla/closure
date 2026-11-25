# Tasks

## Done (2026-11-20) — prototype v1
- [x] Read HVOPS.html / HVOSP_HTML.pdf → field list, sections, document slots, ops precedent values
- [x] Verify every source live (UGC JSON API, AICTE PDFs, Anna University regulations, search options)
- [x] Ingest: .msg → nested .eml → attachments; PDFs; images; document classifier
- [x] Accreditation: UGC (4 lists) + AICTE (13,694 rows) matching; evidence PDF with framed captures
- [x] Passing criteria: domain-locked web search → download → clause locate + highlight → number check → evidence PDF
- [x] Knowledge cache, mail → PDF, mapper (79 fields), HVOPS replica UI + Auto-Close panel

## Done (2026-11-23) — step 1 to production: privacy + research services
- [x] Local OCR (RapidOCR + PP-OCRv6 small) replaces Tesseract and the OpenAI vision call
- [x] Rule-based degree / transcript / revert parsing (no LLM); tested on Cases 1, 2, 3, 5
- [x] Privacy guard + outbound audit log; OpenAI used only for accreditation / passing-criteria research
- [x] Accreditation service (public input, API + page, sources table, not-found evidence, name resolution)
- [x] Passing-criteria service (degree / major / mode / duration / regulation input, official-domain lookup,
      scanned regulation OCR, API + page)
- [x] Fixed sample-docs path; Python 3.14 venv; pinned requirements; run.ps1; pytest suite (31 tests)

## Done (2026-11-25) — OCR moved to OpenAI vision
- [x] Azure Document Intelligence probe (blocked: private endpoint, see research.md)
- [x] Local OCR removed; OpenAI vision OCR with per-image cache + parallel pages; Cases 1/2/3/5 re-run, same verdicts

## Open / next
- [ ] Azure Document Intelligence: needs VPN route + private DNS to `hvops-doc-intel-uae`, an IP allow-list, or a VM
      in the VNet (IT). Then compare with OpenAI OCR on Cases 1–5 (probe script ready)
- [ ] Watermarked / poor scans: OpenAI OCR invents plausible text (Case5 marksheet "COMPUTER SCIENCE", degree name).
      Consider a second read / agreement check or treat degree OCR on such scans as unverified
- [ ] **Remove candidate files from git** (`Cases/`, `data/cases/` are tracked and the repo has a GitHub remote) —
      needs the owner's decision (index removal + history purge if pushed)
- [ ] Golden set: write the correct HVOPS values for Cases 1–6 and an automated scorer (accuracy per field)
- [ ] Case4 (`235914.pdf`) and Case6 (AKTU, 19 students, `.docx`) not yet run — Case6 needs .docx ingest and
      multi-candidate reverts
- [ ] IGNOU-style watermarked scans: preprocessing (watermark suppression) or treat degree OCR as unavailable
- [ ] Gothic / decorative degree fonts: degree title currently unreadable (revert supplies it)
- [ ] Passing criteria for PRIST: found document is an assessment regulation without a clear passing clause →
      flagged; consider grade-based criteria (CGPA / letter grade) in the number check
- [ ] Get real HVOPS dropdown option lists (current lists = seen values + guesses)
- [ ] Confirm ops conventions: "English or Arabic? → No", Branch/Exam location = country,
      "Condition status = Found in Verification Revert", Award Date = exam year (not issue date)
- [ ] Open question: check the UGC fake-universities list and refuse auto-Pass when matched?
- [ ] Production engineering (phase 3): database instead of JSON files, job queue, auth, field-level audit trail,
      retention / deletion of candidate documents, structured logs
- [ ] Production path: push values into real HVOPS via its API instead of the replica
