# Architecture

```
Browser (replica HVOPS UI)                          FastAPI (app/main.py)
 ├─ /            case list + "inject case"   ──►     /api/cases            CRUD (JSON files in data/cases/<id>/)
 ├─ /case/<id>   HVOPS replica + Auto-Close  ──►     /api/cases/<id>/upload   store raw files
 │               panel (drop 4+ docs, Run)   ──►     /api/cases/<id>/run      start pipeline (background task)
 │                                           ◄──     /api/cases/<id>          poll: steps, fields, documents
 │                                           ──►     /api/cases/<id>/submit   final submit (records closure time)
 └─ /research    standalone research tools   ──►     /api/research/accreditation      public info → result + evidence PDF
                                             ──►     /api/research/passing-criteria   public info → result + evidence PDF
```

## Data boundary (2026-11-25 — documents go to OpenAI for OCR, owner's decision)

```
 CANDIDATE DOCUMENTS                                  RESEARCH QUERIES (general info only)
 degree, transcript, revert scans / photos            institution name, college name, programme,
        │                                             degree, major, study mode, duration, regulation year
        ▼                                                       │
 app/ocr.py → llm.vision_ocr  — page image to OpenAI            ▼
   (audited without content: model, image hash, cost)  app/research/*  — AccreditationQuery / PassingQuery
 PDF text layers are read locally (no OCR call)        app/llm.py      — web_search_json
        │                                              app/privacy.py  — guard: blocks e-mails, phone numbers,
        ▼                                                ID numbers, birth dates and the current case's name /
 app/extract/* — layout + rule parsers (local)           register no.; full prompt in data/audit/outbound.jsonl
```
OCR'd text stays in the case folder (`data/cases/<id>/work/ocr_<sha>.json`); research prompts never contain it.

## Pipeline (app/pipeline.py)

```
1 ingest     expand .msg → inner .eml → attachments; PDFs (text layer, else OpenAI OCR per page); images (OpenAI
             OCR); every page → positioned lines; classify each doc                                    (~10 s/image)
2 revert     layout label/value parser (tables) + prose patterns (letters) + online result pages      (<1 s)
   ├─ 3a certificates   degree = sentence patterns; transcript = label/value layout; confidence per field (<1 s)
   ├─ 3b mail PDFs      Outlook-style HTML → Chrome PDF, page sized to content (no cut)                (~2 s)
   ├─ 3c accreditation  UGC JSON + AICTE PDF index (cached locally) → match → [OpenAI name resolution if no
   │                    match, public name only] → evidence PDF with sources table                     (~5-8 s)
   └─ 3d passing        knowledge cache → else official domain (UGC record / mail domain / OpenAI lookup,
                        academic domains only) → OpenAI web_search locked to that domain → download → locate
                        clause (text layer, or OpenAI OCR for scanned PDFs) → highlight → evidence PDF  (cached ~1 s,
                        first time 20-60 s, scanned regulation +~7 s/page, max 16 pages)
4 map        facts → HVOPS fields (rules), cross-checks, flags                                         (free)
```
3a–3d run concurrently. Every field carries `{value, source, note, flag}` so the reviewer sees where it came from.
The case's identifiers are registered with the privacy guard for the whole run (`privacy.case_identifiers`) and
extended as documents are read (`privacy.add_identifiers`).

## Cost principle
Documents: OpenAI OCR, ~$0.002 per certificate page, ~$0.009 per dense marksheet (measured 2026-11-25: $0.01–0.05 per
case), cached per image so re-runs are free. Research: OpenAI only for (a) resolving an institution's official name
when it does not match the official lists directly and (b) finding a regulation the first time. Results are cached in
`data/knowledge/`, so the next case from the same university + degree + mode + regulation costs nothing.

## Modules
| Path | Responsibility |
|---|---|
| `app/config.py` | paths, env, model name |
| `app/ocr.py` | OCR via OpenAI vision (rows of cells → lines with synthetic boxes, per-image cache, parallel), PDF text-layer lines in the same shape |
| `app/privacy.py` | outbound guard (generic PII patterns + case identifiers), audit log |
| `app/store.py` | case JSON persistence |
| `app/form_schema.py` | single source of truth for HVOPS fields/options (used by mapper and UI) |
| `app/extract/mail.py` | .msg/.eml parsing (nested) |
| `app/extract/docs.py` | ingest, per-page text layer vs OCR, classification, image normalisation |
| `app/extract/layout.py` | label → value extraction on positioned lines (same row, stacked, inline, wrapped, fuzzy labels) |
| `app/extract/revert.py` | revert parser: tables, numbered letters, prose letters, result pages (no LLM) |
| `app/extract/certs.py` | degree (sentence rules) + transcript (layout rules), confidence, name candidates (no LLM) |
| `app/llm.py` | OpenAI: vision OCR (audited, no content) + web search (privacy-checked, audited), cost tracking |
| `app/research/sources.py` | download + cache UGC JSON and AICTE PDFs; AICTE row index |
| `app/research/accreditation.py` | `AccreditationQuery` → matching, name resolution, evidence (found / not found) |
| `app/research/passing.py` | `PassingQuery` → official domain, regulation search, clause location (text or OCR), evidence |
| `app/evidence/browser.py` | one shared headless Chrome |
| `app/evidence/render.py` | HTML templates → PDF (mail, evidence with browser frame + sources table) |
| `app/mapper.py` | facts → form fields + document slots + flags |
| `web/` | replica UI + research page (vanilla JS, no build step) |
| `tests/` | pytest: privacy guard, layout, parsers, API input checks (synthetic data only) |
