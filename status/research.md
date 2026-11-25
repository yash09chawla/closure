# Research — verified facts only

Everything here was checked by running code against the real source on 2026-11-20.
Anything not verified is marked **UNVERIFIED**.

## Inputs (sample case `Case/`)

| File | What it really is | How we read it |
|---|---|---|
| `Degree.jpg` | Anna University B.E. Civil degree (scan) | Tesseract reads it well (~0.3 s); vision LLM for structure |
| `Marksheet.jpg` | Consolidated statement of grades (phone photo, CamScanner) | Tesseract output is garbage on this → needs vision LLM |
| `Diploma.jpg` | SBTET Tamil Nadu diploma (prior qualification; candidate is lateral entry — transcript starts at Sem 03) | OCR, classified as "other" |
| `FW Anna University ... CoE_YB587.msg` | Outlook **forward** (Varun → Tanuj/Aman). The real university mail is an attached `.eml` inside it | `extract-msg` → inner `.eml` → `email` stdlib |
| inner `.eml` | From `noreply6@mail1.annauniv.edu` ("Controller of Examinations - Genuineness Verification Portal - Anna University"), Cc `sonia.birla@helloverify.com`, 10 Nov 2026, attachment `CoE_YB587.pdf` | headers + html body |
| `CoE_YB587.pdf` (inside eml) | Genuineness Verification Report with **real text layer** — App No, Status=Genuine, Verified Date, Registration Number, Name, Branch, Institution, Class, Year of Passing, University, Mode of College | deterministic label/value parse, **no OCR, no LLM** |
| `Revert.pdf` | Print of the same report + degree image, **no text layer** | image only |
| `Revert 1.png` | Screenshot of the revert mail in Outlook | OCR for classification |
| `Anna Acc.pdf` / `Anna Pass.pdf` | What the ops user produced manually (target output format) | reference only |

No separate *initiation* mail exists in this sample — the engine must flag it rather than invent one.

## Ground truth from `HVOPS.html` (same case, closed by an ops user)

Case `234291-19634/2026-EDU-1`, applicant `SREE KARTHIK ANBAZHAGAN ANBAZHAGAN`.
Dropdown values saved in the DOM (text inputs were *not* serialised by Angular):

- Institute Name / University: Anna University · Country India / Republic of India
- Educational Institution Type: University Only · Year of Passing / Award Date: 2024
- Applicant Degree Pursuit: Engineering Qualification · Study Mode: Full Time - On Campus · Study Mode Response Status: Mentioned in Verified response
- Subjects/Major: Others (Civil not in list) · NQF: Level 6 – Bachelor or Equivalent · Comparability: Bachelor · Duration: 4 Year
- Arab university: Other Country (...) · Transfer: Regular Student (Not Transfer Student)
- Condition status: Found in Verification Revert · Response Type: Full response received · Email type: Official
- Degree Type: Academic · IA/Degree language: English
- Accreditation: Accredited · India · All India Council for Technical Education · Year 2026
- Result: Pass · Document Genuine · English/Arabic?: No · Payment: No · Son of: No · Transfer credit: Not Applicable
- Upload slots used: Verification Proof ← `Revert 1.png`, Revert 1 ← `Revert.pdf`, Revert 2 ← `Diploma.jpg`, Accreditation ← `Anna Acc.pdf`, Passing Criteria ← `Anna Pass.pdf`, Other ← `Marksheet.jpg`
- HTML also has fields not in the PDF screenshots: **Company Domain** and **Accreditation Year**.

## Accreditation sources

### UGC
- The URL given (`...university?type=ddmCMsxJZgXH2S/m0uMOKQ==`) is **Central Universities only** (`hdfunitypeid=1`).
- Other type tokens: `LZ1FUMk6U2JWGNLvhWfVSA==` = State (2), `0wBmFB1Rb4JGVzq9UP/iOg==` = State Private (3), `UCL6fMspL2LJS89kv++N3A==` = Deemed (4).
- The table is loaded by `GET /universitydetails/Getuniversity_details?unitypeID=N` → JSON `{List:[{uni_name,address,state,status,uni_type,url,ID}]}`. Counts: 57 / 523 / 561 / 164.
- Anna University is **State** (type 2), status `2(f) & 12B`, url `http://www.annauniv.edu` → this also gives us the **official domain** for passing-criteria search.
- Headless Chrome loads the page in ~6 s; the DataTables search box (`#tbl_filter input`) filters rows; screenshot works.

### AICTE
- `Groupwise-List of Institutions_compressed.pdf` (2025-26): 287 pages, **text-searchable**, ~181k words, 2.4 s to read all words.
- One table row = one PyMuPDF text block. Columns by x0: Sr<45, AICTE id 45–110, Name 110–275, Region 275–328, State 328–390, District 390–458, City 458–525, Group ≥525.
- `ANNA UNIVERSITY` = row 5427, id `1-3687844468`, page 115, Southern / Tamil Nadu / Chennai / Group-2 (matches the ops screenshot).
- `Public Notice 2025-26.pdf`: 2 pages; page 2 has the Group table the ops user screenshotted.

## Passing criteria

- Free search scraping is **not reliable**: DuckDuckGo HTML returns a CAPTCHA (HTTP 202), Bing returns unrelated results to scripted requests.
- OpenAI Responses API `web_search` tool with `filters.allowed_domains=["annauniv.edu"]` on `gpt-5.4-mini`: **11.4 s**, ~17k input tokens, returned
  `https://cac.annauniv.edu/aidetails/reg/2017/00.%20UG%20%28Aff%29%20Reg%20%282017%29%20-%205.9.18.pdf` — Regulations 2017, B.E./B.Tech affiliated colleges (this is the candidate's actual regulation — transcript says `2017 (CBCS)`).
- That PDF downloads (16 pages); clause **14. PASSING REQUIREMENTS** is on page 10: "not less than 50% of total marks … with a minimum of 45% of the marks prescribed for the end-semester University Examination".
- Note: the ops sample used the **R2025 B.Des** regulation, which is the wrong programme/regulation for this candidate.

## Measured results (2026-11-20)

| Run | Inputs | Time | LLM cost | Result |
|---|---|---|---|---|
| Anna sample, knowledge cache warm | Degree.jpg, Marksheet.jpg, .msg | 8.8–10.5 s | $0.004 | 79 fields, 6 docs, 1 flag (no initiation mail) |
| Anna sample, first passing lookup | same | ~25 s (search 11–15 s) | ~$0.06 | same |
| Anna sample, offline (`HV_DISABLE_LLM=1`) | same | 8.1 s | $0 | 79 fields; passing from cache flagged "regulation year not confirmed" |
| **Synthetic** Delhi University case (hand-written .eml, *not real data*) | initiation.eml, free-text revert.eml | 25.1 s | $0.074 | 75 fields; LLM revert parse; UGC Central; DU Calendar Ordinance IX §7 p.59 |

Cross-check against the ops-filled HTML for the Anna case: every dropdown the ops user chose is reproduced, except
Subjects/Major (engine: "Civil Engineering" because our option list contains it; ops chose "Others" — real list likely lacks it).

## Tooling on this Mac
- Python 3.14 (Homebrew), venv at `.venv`. Tesseract 5 with `eng`. Google Chrome installed → Playwright `channel="chrome"` (no browser download needed).
- No LibreOffice / poppler. PyMuPDF covers PDF text, render, highlight.
- OpenAI models available include `gpt-4.1-mini`, `gpt-5.4-mini`, `gpt-5-search-api`.

## Local OCR + local parsing — measured 2026-11-23 (Windows 11, CPU only)

**Engine choice.** RapidOCR 3.10 + onnxruntime 1.32 running the PaddleOCR **PP-OCRv6 small** det/rec models that
ship *inside* the `rapidocr` wheel (~31 MB, no download). modelscope.cn (RapidOCR's default model host for other
model versions) is blocked on this network, so the bundled models are also the only ones that work here.
onnxruntime has **no Python 3.15 wheels** → the venv runs on Python 3.14. Tesseract is no longer used.

| Document | OCR time | Mean line confidence | Result of the local parser |
|---|---|---|---|
| Case1 Degree.jpg (Anna, scan) | 3.0 s | 0.95 | name, degree title, class, exam session, reg. no., university — all correct |
| Case1 Marksheet.jpg (phone photo) | 8.1 s | 0.97 | name, reg. no., regulation 2017 (CBCS), college, DOB, CGPA 7.68, sem 03–07, first exams NOV 2021 — correct |
| Case2 ECERT_p1.jpg (Gothic font degree) | 3.3 s | 0.95 | name, reg. no., class, exam session correct; **degree title not readable** (decorative font) → taken from revert |
| Case3 Degree.jpg (Symbiosis) | ~3 s | 0.97 | MBA (Telecom Management) correct; name read as "Yachaspati" (V→Y) → mapper keeps the transcript/revert spelling "Vachaspati" and notes the variant |
| Case3 Marksheet.jpg | ~4 s | 0.97 | name, college, CGPA 2.551, first exams OCT 2011 correct; seat no. kept apart from PRN |
| Case5 Degree.pdf / Marksheet.pdf (IGNOU, watermark + apostille) | ~40 s (6 pages) | 0.79 / 0.85 | **not usable** — watermark text everywhere; key facts come from the revert |

Revert parsing (local, no LLM) on the four real formats:
- Case1 Anna report (table): status, reg. no., name, branch (Full Time), institution (3 wrapped lines), class, year, university, verified date — correct.
- Case2 PRIST letter (numbered table + "GENUINE and found correct"): status, name, reg. no., degree, year, class, mode — correct.
  Before the fix it was classified as a *degree* (it contains "qualified for the degree") → classifier now recognises letters addressed to HelloVerify.
- Case3 Symbiosis prose letter: status, PRN, degree, April 2013, CGPA 2.628/4, regular, institution, university, name — correct.
- Case5 IGNOU online grade card (browser print, image + URL header): enrolment no., name (surname first), programme code; status
  "COMPLETED" is **not** a genuineness statement → flagged, result Discrepancy for human review.

End-to-end (server + UI pipeline, 2026-11-23): Case1 Pass, 75 fields, 47 s; Case3 Pass, 67 fields, 38 s ($0 — cache);
Case2 Pass, 72 fields, 106 s (passing clause not confirmed → flagged); Case5 Discrepancy (revert has no status), 50 fields.

Outbound audit (`data/audit/outbound.jsonl`) for these runs contains only institution / degree / mode / regulation /
year / official domain — no names, numbers or document content.

**Scanned regulations.** PRIST `Assesment-Regulations.pdf` (44 pages) has no text layer. Local OCR of all pages took
310 s (≈7 s/page at 150 dpi); results are cached next to the PDF. The engine now OCRs at most 16 new pages per lookup,
starting around the page the search reported.

## OCR options — measured 2026-11-24 / 25
**Azure Document Intelligence** (`hvops-doc-intel-uae`, UAE North, paid; key 84 chars). Every call → 403
"Public access is disabled. Please configure private endpoint." DNS has a `privatelink` CNAME; from the laptop the name
resolves to the public IP 20.74.197.139 both off-VPN and on GlobalProtect (VPN DNS 192.168.10.249). VPN egress IPs seen:
182.156.0.66, 180.151.232.74 (they change). Key validity unknown (network check fails first). Needs IT: VPN route +
private DNS, or "Selected networks" + allow-list, or a VM inside the VNet.

**OpenAI vision OCR** (`gpt-5.4-mini`, detail "original", reasoning effort none, JSON rows of cells):
| Document | Time | Cost | Quality |
|---|---|---|---|
| Case3 Gothic-font degree (850×1167) | 4 s | $0.002 | title "Master of Business Administration (Telecom Management)" read (local OCR could not); name varies between runs (Vachaspati / Barchaspati / Bachaspati) |
| Case1 phone-photo marksheet | 10 s | $0.009 | all 65 rows, every table cell separate and correct on spot checks |
| Case5 IGNOU watermarked degree + marksheet | 15 s (6 pages) | $0.05 | IGNOU result page perfect; degree name and marksheet branch **invented** ("COMPUTER SCIENCE" for Civil/Construction Mgmt) — no [?] marks |
Whole cases: 12–21 s, $0.01–0.05.

