# HV Research API

`research.py` is a single, self-contained module (no dependency on `app/`) that checks **accreditation** and finds **passing criteria**. Every function takes a typed request model and returns a typed response model (Pydantic), so each one can be exposed as an HTTP endpoint unchanged.

| Function (async) | Sync wrapper | Endpoint | Cost |
|---|---|---|---|
| `check_accreditation(AccreditationRequest)` | `check_accreditation_sync` | `POST /research/accreditation` | $0: local UGC/AICTE match, ~0.3 s |
| `find_passing_criteria(PassingCriteriaRequest)` | `find_passing_criteria_sync` | `POST /research/passing-criteria` | $0 on cache hit; otherwise 1 OpenAI web search (~$0.02–0.05, ~20–30 s) |
| `research(ResearchRequest)` | `research_sync` | `POST /research` | both calls, chained |
| `health()` | – | `GET /research/health` | – |

`research()` runs accreditation first, then passes the **canonical university name** and the **UGC website** (the official domain) into passing criteria.

## Use

```python
from research_api.research import research_sync, find_passing_criteria, PassingCriteriaRequest

res = research_sync({"university": "Anna University, Chennai", "degree_title": "Bachelor of Engineering",
                     "degree_short": "B.E.", "regulation": "2017", "affiliated": True})
print(res.accreditation.status, res.passing.criteria)
```

Exposing it later:

```python
# mount into an existing FastAPI app
from research_api.research import create_router
app.include_router(create_router())          # adds /research, /research/accreditation, ...

# or run it standalone (Swagger docs at /docs)
python research_api/research.py serve --port 8100
```

CLI: `python research.py accreditation|passing-criteria|research examples/<payload>.json`

## Payloads

Full examples are in `examples/`. The OpenAPI schema (`/openapi.json`) is generated from the models in `research.py`.

**AccreditationRequest**: `university` (required), `college` (optional; `"Name [District]"` adds a district hint), `degree` (used to choose AICTE or UGC), `include_evidence`.

**AccreditationResponse**: `status` (`Accredited` / `Non-Accredited`), `body`, `body_short` (`UGC` / `AICTE`), `url`, `year`, `country`, `technical`, `canonical_university`, `summary`, `ugc` (name, type, status, website…), `aicte_university`, `aicte_college` (row, AICTE id, region, page…), `evidence[]`, `warnings[]`, `seconds`.

**PassingCriteriaRequest**: `university`, `degree_title` (required), `degree_short`, `regulation`, `year_of_passing`, `affiliated`, `official_domains[]`, `university_website`, `mail_domains[]`, `use_cache`, `include_evidence`. At least one official domain must come from `official_domains`, `university_website` or a `.edu` / `.ac.xx` mail domain.

**PassingCriteriaResponse**: `found`, `verified` (every % in `criteria` occurs in the document), `cached`, `loose_match`, `reason` (set when `found=false`), `url`, `document_title`, `regulation`, `clause_heading`, `criteria`, `clause_text` (verbatim), `page`, `pages`, `domains`, `evidence[]`, `llm` (model, tokens, searches, usd), `seconds`.

**Evidence** (only when `include_evidence=true`): `kind` (`aicte_row` / `passing_clause`), `title`, `source_url`, `page`, `mime`, `data_base64` (highlighted PNG, about 200–400 KB each).

Errors: invalid payloads get HTTP 422 from FastAPI's validation. Research failures are **not** exceptions: they come back as `found=false` with a `reason`.

## Rules carried over from the engine

- A URL from search is accepted only if it is on the university's own domain.
- Only results with `verified=true` are written to the knowledge cache.
- If the regulation year is unknown, the newest cached entry for the same university and programme is used, `loose_match=true` is set and the result is never marked verified.
- HTML regulation pages are read as text only. There is no browser, so no screenshot evidence for those.

## Configuration

| Env var | Default | |
|---|---|---|
| `OPENAI_API_KEY` | – | read from `research_api/.env` or `closure/.env` |
| `HV_SEARCH_MODEL` | `gpt-5.4-mini` | |
| `HV_DISABLE_LLM` | – | `1` = cache only |
| `HV_RESEARCH_DATA` | `research_api/data` | UGC/AICTE caches + knowledge cache (git-ignored) |

Dependencies: `pydantic httpx pymupdf rapidfuzz openai`, plus optionally `python-dotenv` and `fastapi uvicorn`. All are already in `closure/requirements.txt`. The first run downloads the UGC lists and the AICTE PDF (about 1 minute to index). To skip that, point `HV_RESEARCH_DATA` at a folder with a copy of `closure/data/sources`.
