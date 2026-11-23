# Architecture

```
Browser (replica HVOPS UI)                          FastAPI (app/main.py)
 ├─ /            case list + "inject case"   ──►     /api/cases            CRUD (JSON files in data/cases/<id>/)
 └─ /case/<id>   HVOPS replica + Auto-Close  ──►     /api/cases/<id>/upload   store raw files
                 panel (drop 4+ docs, Run)   ──►     /api/cases/<id>/run      start pipeline (background task)
                                             ◄──     /api/cases/<id>          poll: steps, fields, documents
                                             ──►     /api/cases/<id>/submit   final submit (records closure time)
```

## Pipeline (app/pipeline.py)

```
1 ingest        expand .msg → inner .eml → attachments; PDFs/images; classify each doc   (free, <1 s)
2 revert        parse university report text + mail headers (deterministic)              (free, <1 s)
   ├─ 3a certificates   Tesseract + ONE vision call (degree + transcript → JSON)         (~5-8 s)
   ├─ 3b mail PDFs      Outlook-style HTML → Chrome PDF, page sized to content (no cut)  (~2 s)
   ├─ 3c accreditation  UGC JSON + AICTE PDF index (cached locally) → match → evidence   (cache hit <2 s; UGC live screenshot ~7 s)
   └─ 3d passing        knowledge cache → else OpenAI web_search locked to official domain
                        → download doc → locate clause → highlight → evidence PDF        (first time ~15 s, cached ~1 s)
4 map           facts → HVOPS fields (rules), cross-checks, flags                         (free)
```
3a–3d run concurrently. Every field carries `{value, source, note, flag}` so the reviewer sees where it came from.

## Cost principle
Deterministic first (text layers, email headers, regex, local indexes). LLM only for (a) photographed certificates
and (b) finding a university regulation the first time. Results are cached in `data/knowledge/` so the
next case from the same university+programme costs nothing.

## Modules
| Path | Responsibility |
|---|---|
| `app/config.py` | paths, env, model names |
| `app/store.py` | case JSON persistence |
| `app/form_schema.py` | single source of truth for HVOPS fields/options (used by mapper and UI) |
| `app/extract/mail.py` | .msg/.eml parsing (nested) |
| `app/extract/docs.py` | ingest, classification, OCR, PDF text, image normalisation |
| `app/extract/revert.py` | university report label/value parser (+LLM fallback for free-text reverts) |
| `app/extract/certs.py` | degree/transcript extraction (vision LLM, regex fallback) |
| `app/llm.py` | OpenAI wrapper (JSON output, web_search), cost tracking |
| `app/research/sources.py` | download + cache UGC JSON and AICTE PDFs; AICTE row index |
| `app/research/accreditation.py` | matching + evidence capture |
| `app/research/passing.py` | regulation discovery, clause location, evidence |
| `app/evidence/browser.py` | one shared headless Chrome |
| `app/evidence/render.py` | HTML templates → PDF (mail, evidence with browser frame) |
| `app/mapper.py` | facts → form fields + document slots + flags |
| `web/` | replica UI (vanilla JS, no build step) |
