"""HV Closure Engine — FastAPI server for the HVOPS replica + auto-close pipeline."""
import asyncio
import shutil
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, form_schema, pipeline, store
from .evidence import browser
from .research import sources

SAMPLES = {  # demo helper: the inputs an ops user receives for each sample case
    "anna": (config.ROOT / "Cases" / "Case1",
             ["Degree.jpg", "Marksheet.jpg",
              "FW Anna University - Genuineness Verification Application Number -CoE_YB587.msg"]),
    "ignou": (config.ROOT / "Cases" / "Case5", ["Degree.pdf", "Marksheet.pdf", "Revert.pdf", "Start Date.png"]),
}
_tasks: dict[str, asyncio.Task] = {}


@asynccontextmanager
async def lifespan(app):
    threading.Thread(target=sources.warm, daemon=True).start()  # UGC + AICTE caches
    try:
        await browser.browser()                                   # Chrome ready before the first case
    except Exception:
        pass
    yield
    await browser.close()


app = FastAPI(title="HV Closure Engine", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=config.WEB / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(config.WEB / "index.html")


@app.get("/case/{cid}")
def case_page(cid: str):
    return FileResponse(config.WEB / "case.html")


@app.get("/api/schema")
def schema():
    return form_schema.schema()


@app.get("/api/status")
def status():
    return {"llm": config.USE_LLM, "extract_model": config.EXTRACT_MODEL, "search_model": config.SEARCH_MODEL,
            "ugc_cached": all((config.SOURCES / f"ugc_{t}.json").exists() for t in config.UGC_TYPES),
            "aicte_cached": (config.SOURCES / "aicte_index.json").exists()}


def _summary(c):
    e = c.get("engine") or {}
    return {"id": c["id"], "case_ref": c["case_ref"], "applicant": c["mohre"].get("applicant_full_name"),
            "institute": c["mohre"].get("institute_name"), "status": c.get("status"), "client": c.get("client"),
            "received_on": c.get("received_on"), "engine_seconds": e.get("seconds"), "cost_usd": e.get("cost_usd"),
            "closure_seconds": c.get("closure_seconds"), "flags": len(c.get("flags", [])),
            "uploads": len(list(store.uploads_dir(c["id"]).iterdir()))}


@app.get("/api/cases")
def list_cases():
    return [_summary(c) for c in store.list_cases()]


def _new_case(d: dict) -> dict:
    ref = (d.get("case_ref") or "").strip()
    if not ref:
        raise HTTPException(400, "case_ref required")
    cid = store.slug(ref)
    if store.load(cid):
        raise HTTPException(409, "case already exists")
    mohre = {k: (d.get(k) or "").strip() for k in
             ["applicant_full_name", "institute_id", "institute_details", "institute_name", "country_code",
              "country_name", "study_level", "cert_title", "study_start", "study_end", "subject_id", "subjects"]}
    mohre["institute_id"] = mohre["institute_id"] or mohre["institute_name"]
    case = {"id": cid, "case_ref": ref, "client": d.get("client") or "MOHRE-Direct API", "mohre": mohre,
            "passport_name": (d.get("passport_name") or mohre["applicant_full_name"]).strip(),
            "received_on": d.get("received_on") or time.strftime("%d-%m-%Y"),
            "insuff": d.get("insuff", []), "status": "new", "created_at": time.time(),
            "fields": {}, "flags": [], "documents": {}, "mails": [], "edits": {}}
    return store.save(case)


@app.post("/api/cases")
async def create_case(req: Request):
    return _new_case(await req.json())


DEMO = {
    "case_ref": "234291-19634/2026-EDU-1", "applicant_full_name": "SREE KARTHIK ANBAZHAGAN ANBAZHAGAN",
    "passport_name": "SREE KARTHIK ANBAZHAGAN", "institute_name": "Anna University", "institute_id": "Anna University",
    "country_code": "IND", "country_name": "Republic of India", "study_level": "Bachelor",
    "cert_title": "Civil Engineering", "study_start": "08-2021", "study_end": "11-2024", "subject_id": "0",
    "subjects": "Civil Engineering", "received_on": "28-10-2026",
    "insuff": [{"date": "28 Oct 2026 10:58:04 PM", "by": "Akash.Verma@helloverify.ae", "type": "l1_insuff",
                "status": "cleared", "id": "477",
                "remark": "Your transcript or marksheets for all semesters and years are required. Please upload a high "
                          "resolution, complete, uncropped copy officially issued by your institution. Ensure all "
                          "text, stamps, and signatures are visible."}],
}


# Online-database sample (Cases/Case5): IGNOU grade-card + admission-status portal screenshots.
# Initiation values below are only what the documents show; start/end dates are left for the engine to find.
DEMO_ONLINE = {
    "case_ref": "238371/2026-EDU-1", "applicant_full_name": "ALPESHBHAI GHANSHYAMBHAI PATEL",
    "passport_name": "ALPESHBHAI GHANSHYAMBHAI PATEL", "institute_name": "Indira Gandhi National Open University",
    "institute_id": "Indira Gandhi National Open University", "country_code": "IND",
    "country_name": "Republic of India", "study_level": "Bachelor",
    "cert_title": "Bachelor of Technology in Civil (Construction Management)", "subjects": "Civil Engineering",
    "subject_id": "0",
}


@app.post("/api/cases/demo")
def create_demo(kind: str = "anna"):
    d = DEMO_ONLINE if kind == "ignou" else DEMO
    cid = store.slug(d["case_ref"])
    if store.load(cid):
        shutil.rmtree(store.case_dir(cid))
    c = _new_case(d)
    store.update(cid, lambda x: x.update(sample=kind))
    return c


@app.get("/api/cases/{cid}")
def get_case(cid: str):
    c = store.load(cid)
    if not c:
        raise HTTPException(404)
    c["uploads"] = [{"name": p.name, "size": p.stat().st_size, "url": f"/files/{cid}/uploads/{p.name}"}
                    for p in sorted(store.uploads_dir(cid).iterdir())]
    live = pipeline.RUNS.get(cid)
    if live:
        c["run"] = {k: v for k, v in live.items()}
        c["run"]["steps"] = [{k: v for k, v in s.items() if k != "_t"} for s in live["steps"]]
    return JSONResponse(c)


@app.delete("/api/cases/{cid}")
def delete_case(cid: str):
    shutil.rmtree(store.case_dir(cid), ignore_errors=True)
    return {"ok": True}


@app.post("/api/cases/{cid}/upload")
async def upload(cid: str, files: list[UploadFile] = File(...)):
    if not store.load(cid):
        raise HTTPException(404)
    d = store.uploads_dir(cid)
    for f in files:
        name = Path(f.filename).name
        (d / name).write_bytes(await f.read())
    return {"ok": True, "count": len(files)}


@app.post("/api/cases/{cid}/sample-docs")
def sample_docs(cid: str, kind: str = "anna"):
    """Demo helper: copy a sample case's input documents (anna = e-mail revert, ignou = online database)."""
    if kind not in SAMPLES:
        raise HTTPException(400, "unknown sample")
    src, names = SAMPLES[kind]
    d = store.uploads_dir(cid)
    copied = []
    for n in names:
        if (src / n).exists():
            shutil.copy(src / n, d / n)
            copied.append(n)
    return {"ok": True, "copied": copied}


@app.delete("/api/cases/{cid}/uploads/{name}")
def delete_upload(cid: str, name: str):
    p = store.uploads_dir(cid) / Path(name).name
    if p.exists():
        p.unlink()
    return {"ok": True}


@app.post("/api/cases/{cid}/run")
async def run(cid: str):
    c = store.load(cid)
    if not c:
        raise HTTPException(404)
    if not any(store.uploads_dir(cid).iterdir()):
        raise HTTPException(400, "upload documents first")
    t = _tasks.get(cid)
    if t and not t.done():
        return {"ok": True, "already_running": True}
    store.update(cid, lambda x: x.update(status="processing", run_started=time.time()))
    _tasks[cid] = asyncio.create_task(pipeline.run(cid))
    return {"ok": True}


@app.put("/api/cases/{cid}/fields")
async def save_fields(cid: str, req: Request):
    body = await req.json()

    def apply(c):
        for k, v in body.get("fields", {}).items():
            cur = c["fields"].get(k)
            if not cur or cur.get("value") != v:
                c["edits"][k] = {"from": (cur or {}).get("value"), "to": v, "at": time.time()}
                c["fields"][k] = {**(cur or {}), "value": v, "source": "Edited by reviewer", "flag": ""}
    return store.update(cid, apply)


@app.post("/api/cases/{cid}/submit")
async def submit(cid: str, req: Request):
    body = await req.json()

    def apply(c):
        for k, v in body.get("fields", {}).items():
            if c["fields"].get(k, {}).get("value") != v:
                c["edits"][k] = {"from": c["fields"].get(k, {}).get("value"), "to": v, "at": time.time()}
                c["fields"][k] = {**c["fields"].get(k, {}), "value": v, "source": "Edited by reviewer"}
        c["status"] = "closed"
        c["closed_at"] = time.time()
        if c.get("run_started"):
            c["closure_seconds"] = round(c["closed_at"] - c["run_started"], 1)
    return store.update(cid, apply)


@app.post("/api/cases/{cid}/slot/{slot}")
async def slot_upload(cid: str, slot: str, files: list[UploadFile] = File(...)):
    """Manual upload straight into a Documents slot (like the HVOPS Upload button)."""
    d = store.case_dir(cid) / "manual"
    d.mkdir(exist_ok=True)
    entries = []
    for f in files:
        p = d / Path(f.filename).name
        p.write_bytes(await f.read())
        entries.append({"name": p.name, "url": f"/files/{cid}/manual/{p.name}", "source": "Uploaded by reviewer",
                        "generated": False})
    return store.update(cid, lambda c: c.setdefault("documents", {}).setdefault(slot, []).extend(entries))


@app.get("/files/{cid}/{path:path}")
def files(cid: str, path: str):
    base = store.case_dir(cid).resolve()
    p = (base / path).resolve()
    if not str(p).startswith(str(base)) or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, content_disposition_type="inline", filename=p.name)
