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
