"""Auto-close orchestrator. Live state lives in RUNS (polled by the UI) and is persisted to case.json."""
import asyncio
import re
import shutil
import time
import traceback
from pathlib import Path

from . import mapper, privacy, store
from .evidence import browser, render
from .extract import certs as certsmod
from .extract import docs as docsmod
from .extract import revert as revertmod
from .research import accreditation, passing

RUNS: dict[str, dict] = {}

STEPS = [("ingest", "Reading & classifying documents (OpenAI OCR)"), ("revert", "Parsing university revert"),
         ("certs", "Reading degree & transcript"), ("mails", "Printing e-mails to PDF (layout preserved)"),
         ("accreditation", "Accreditation check — UGC / AICTE"), ("passing", "Passing criteria — official institute website"),
         ("fill", "Filling HVOPS form & attaching documents")]


class Run:
    def __init__(self, cid):
        self.cid = cid
        self.state = {"status": "running", "started": time.time(), "finished": None, "cost_usd": 0.0,
                      "steps": [{"id": i, "label": l, "status": "pending", "seconds": None, "detail": ""}
                                for i, l in STEPS], "log": []}
        RUNS[cid] = self.state

    def step(self, sid):
        return next(s for s in self.state["steps"] if s["id"] == sid)

    def start(self, sid, detail=""):
        s = self.step(sid)
        s.update(status="running", _t=time.time(), detail=detail)
        self.log(f"▶ {s['label']}")

    def done(self, sid, detail="", status="done"):
        s = self.step(sid)
        s.update(status=status, seconds=round(time.time() - s.get("_t", time.time()), 1), detail=detail)
        self.log(f"{'✓' if status == 'done' else '⚠'} {s['label']} — {detail} ({s['seconds']}s)")

    def log(self, msg):
        self.state["log"].append({"t": round(time.time() - self.state["started"], 1), "msg": msg})

    def cost(self, meta):
        if meta and meta.get("usd"):
            self.state["cost_usd"] = round(self.state["cost_usd"] + meta["usd"], 4)


def _safe(s, n=70):
    return re.sub(r"[^\w\-. ()&']+", " ", s or "").strip()[:n].strip() or "document"


def _file_entry(cid, path: Path, source: str, generated=False) -> dict:
    rel = path.relative_to(store.case_dir(cid))
    return {"name": path.name, "url": f"/files/{cid}/{rel.as_posix()}", "source": source, "generated": generated}


async def run(cid: str):
    case = store.load(cid)
    mo = case.get("mohre", {})
    ids = [case.get("passport_name"), mo.get("applicant_full_name")]
    # the identifiers grow as documents are read (degree name, register no., DOB) → _run adds them
    with privacy.case_identifiers(ids):
        await _run(cid, case)


async def _run(cid: str, case: dict):
    R = Run(cid)
    work, out = store.work_dir(cid), store.out_dir(cid)
    for p in list(work.iterdir()) + list(out.iterdir()):
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    files = sorted(store.uploads_dir(cid).iterdir())
    facts = {}
    try:
        # 1. ingest
        R.start("ingest")
        docs, mails = await asyncio.to_thread(docsmod.ingest, files, work)
        ocr_usd = round(sum(d.get("ocr_usd", 0) for d in docs), 4)
        R.cost({"usd": ocr_usd})
        R.state["ocr_cost_usd"] = ocr_usd
        for d in docs:
            for e in d.get("ocr_errors", []):
                R.log(f"   ⚠ {d['name']}: {e}")
        kinds = {}
        for d in docs:
            kinds.setdefault(d["kind"], []).append(d)
        for d in kinds.get("mail_screenshot", []):
            em = re.search(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", d["text"])
            d["role"] = "initiation" if em and "helloverify" in em.group(0).lower() else "revert"
        R.done("ingest", f"{len(files)} files → {len(docs)} documents, {len(mails)} e-mail(s): " +
               ", ".join(f"{k}×{len(v)}" for k, v in kinds.items()) + f" · OCR ${ocr_usd:.4f}")
        for d in docs:
            R.log(f"   {d['name']}: {d['kind']}" + (f" ({d['origin']})" if d["origin"] != "upload" else ""))
        init_mails = [m for m in mails if m["role"] == "initiation"]
        rev_mails = [m for m in mails if m["role"] == "revert"]
        rmail = rev_mails[0] if rev_mails else None

        # 2. revert (deterministic first)
        R.start("revert")
        rev_docs = list(kinds.get("verification_report", [])) + \
            [d for d in kinds.get("mail_screenshot", []) if d.get("role") != "initiation"]
        if not rev_docs and not rmail:
            # e.g. a screenshot of the university's online result / grade-card page — parsed, never assumed genuine
            rev_docs = [d for d in kinds.get("other", []) if not d.get("parent")]
        if rmail:
            rev_docs = sorted(rev_docs, key=lambda d: d.get("parent") != rmail["id"])
        hints = [case.get("passport_name"), case["mohre"].get("applicant_full_name")]
        rev = await asyncio.to_thread(revertmod.parse_revert, rmail, rev_docs, hints)
        privacy.add_identifiers([rev["fields"].get(k) for k in ("name", "registration_no", "dob", "app_no")])
        facts["revert"] = rev
        facts["revert_mail"] = rmail
        facts["respondent"] = revertmod.respondent_from_mail(rmail) if rmail else {}
        rf = rev["fields"]
        R.done("revert", f"{rev['method']} parse of {rev['source'] or '—'}: status {rf.get('status', '?')}, "
                         f"{len([k for k in rf if not k.startswith('_')])} fields" if rf else "no revert found",
               "done" if rf else "warn")

        university = rf.get("university") or case["mohre"].get("institute_name") or ""
        degree_hint = rf.get("branch") or rf.get("degree") or case["mohre"].get("cert_title", "")

        # 3a certs
        async def t_certs():
            R.start("certs")
            deg = kinds.get("degree", [])
            tr = kinds.get("transcript", [])
            if not deg and not tr:
                R.done("certs", "no degree/transcript uploaded", "warn")
                return {"fields": {}, "method": "none"}
            res = await asyncio.to_thread(certsmod.extract, deg, tr)
            f = res["fields"]
            privacy.add_identifiers([f.get("register_no"), f.get("date_of_birth")] + res.get("name_candidates", []))
            R.done("certs", f"{res['method']}: {f.get('candidate_name', '?')} · {f.get('degree_short', '')} "
                            f"{f.get('major', '')} · {f.get('class_awarded', '')} · reg {f.get('register_no', '')}")
            return res

        # 3b mail PDFs
        async def t_mails():
            R.start("mails")
            made = {"initiation": [], "revert": []}
            for m in mails:
                label = "Initiation e-mail (HV → institution)" if m["role"] == "initiation" else \
                    "Verification revert e-mail (institution → HV)"
                name = ("Initiation Mail - " if m["role"] == "initiation" else "Revert Mail - ") + _safe(m["subject"], 110) + ".pdf"
                p = out / name
                await browser.html_to_pdf(render.mail_html(m, label), str(p), width_px=1100)
                made[m["role"]].append(p)
            R.done("mails", f"{len(made['revert'])} revert, {len(made['initiation'])} initiation mail PDF(s)"
                   if mails else "no .msg/.eml uploaded", "done" if mails else "warn")
            return made

        # 3c accreditation
        async def t_acc():
            nonlocal university
            if not university:   # neither revert nor initiation names it → use what the degree says
                university = ((await certs_task).get("fields") or {}).get("university", "")
            R.start("accreditation", university)
            if not university:
                R.done("accreditation", "university unknown", "warn")
                return {}
            q = accreditation.AccreditationQuery(university=university, college=rf.get("institution", ""),
                                                 programme=degree_hint)
            res = await accreditation.run(q, work, out / f"Accreditation - {_safe(university.split(',')[0])}.pdf", R.log)
            R.cost(res.get("meta"))
            R.done("accreditation", f"{res['status']} — {res['body']}" if res.get("body_short") else res["status"],
                   "done" if res["status"] == "Accredited" else "warn")
            return res

        certs_task = asyncio.create_task(t_certs())
        mails_task = asyncio.create_task(t_mails())
        acc_task = asyncio.create_task(t_acc())

        # 3d passing — needs programme + regulation (from transcript) and official domain (from UGC)
        async def t_pass():
            ce = (await certs_task)["fields"]
            acc = await acc_task
            R.start("passing")
            uni = (acc or {}).get("canonical_university") or university.split(",")[0]
            mode = rf.get("mode_of_study") or (re.search(r"\(([^)]*time[^)]*)\)", rf.get("branch", ""), re.I) or [None, ""])[1]
            rv_deg = rf.get("degree") or ""
            degree = rv_deg or ce.get("degree_title") or ce.get("degree_short") or degree_hint
            major = ce.get("major") or (re.search(r"(?i)\bin\s+(.+)$", rv_deg) or [None, ""])[1]
            short = mapper.short_key(ce.get("degree_short")) or mapper.short_from_text(degree)
            q = passing.PassingQuery(
                institute=uni, degree=degree, major=major, mode=mode or "Full-time",
                duration_years=mapper.DURATION_BY_DEGREE.get(short) or None,
                regulation=ce.get("regulation", ""),
                passing_year=mapper.year_of(rf.get("year_of_passing") or ce.get("exam_month_year", "")),
                affiliated_college="affiliat" in rf.get("mode_of_college", "").lower() or bool(rf.get("institution")),
                official_website=((acc or {}).get("ugc") or {}).get("website", "") or (acc or {}).get("resolved_website", ""),
                domain_hints=[rmail["from_email"].split("@")[-1]] if rmail else [])
            res = await passing.run(q, work, out / f"Passing Criteria - {_safe(uni)}.pdf", R.log)
            R.cost(res.get("meta"))
            if res.get("found"):
                R.done("passing", f"{res['clause_heading']} (p.{res['page']}) "
                                  f"{'from knowledge cache' if res.get('cached') else 'found by search'}"
                                  f"{'' if res.get('verified') else (' — regulation year not confirmed' if res.get('loose') else ' — numbers NOT confirmed')}",
                       "done" if res.get("verified") else "warn")
            else:
                R.done("passing", res.get("reason", "not found"), "warn")
            return res

        pass_task = asyncio.create_task(t_pass())
        results = await asyncio.gather(certs_task, mails_task, acc_task, pass_task, return_exceptions=True)
        names = ["certs", "mails", "accreditation", "passing"]
        for n, r in zip(names, results):
            if isinstance(r, Exception):
                R.done(n, f"failed: {r}", "error")
                R.log("".join(traceback.format_exception(r))[-800:])
        facts["certs"], mail_pdfs, facts["accreditation"], facts["passing"] = [
            ({} if isinstance(r, Exception) else r) for r in results]
        mail_pdfs = mail_pdfs or {"initiation": [], "revert": []}

        # 4. fill
        R.start("fill")
        fields, flags, remarks = mapper.build(case, facts)
        slots = {k: [] for k in ["payment_proof", "verification_proof", "revert_1", "revert_2", "accreditation",
                                 "passing_criteria", "other"]}
        for p in mail_pdfs["initiation"]:
            slots["verification_proof"].append(_file_entry(cid, p, "Initiation e-mail rendered to PDF", True))
        for d in kinds.get("mail_screenshot", []):
            if d.get("role") == "initiation":
                slots["verification_proof"].append(_file_entry(cid, Path(d["path"]), "Uploaded mail screenshot"))
        for p in mail_pdfs["revert"]:
            slots["revert_1"].append(_file_entry(cid, p, "Revert e-mail rendered to PDF", True))
        for d in kinds.get("mail_screenshot", []):
            if d.get("role") != "initiation":
                slots["revert_1"].append(_file_entry(cid, Path(d["path"]), "Uploaded mail screenshot"))
        for d in kinds.get("verification_report", []):
            slots["revert_2"].append(_file_entry(cid, Path(d["path"]),
                                                 "Attachment of revert e-mail" if d.get("parent") else "Uploaded"))
        if (facts["accreditation"] or {}).get("pdf"):
            slots["accreditation"].append(_file_entry(cid, Path(facts["accreditation"]["pdf"]),
                                                      "Generated: UGC/AICTE evidence", True))
        if (facts["passing"] or {}).get("pdf"):
            slots["passing_criteria"].append(_file_entry(cid, Path(facts["passing"]["pdf"]),
                                                         "Generated: official regulation evidence", True))
        rev_src = (facts.get("revert") or {}).get("source", "")
        for d in kinds.get("other", []):
            if d["name"] == rev_src:   # online result page / screenshot used as the revert
                slots["revert_1"].append(_file_entry(cid, Path(d["path"]), "Online verification screenshot"))
        for k in ("degree", "transcript", "diploma", "other"):
            for d in kinds.get(k, []):
                if d.get("parent") or (k == "other" and d["name"] == rev_src):
                    continue
                slots["other"].append(_file_entry(cid, Path(d["path"]), k.title()))
        if not slots["verification_proof"]:
            flags.append({"level": "warn", "field": "verification_proof",
                          "msg": "No initiation e-mail among the uploads — attach it if the client requires it"})
        mail_rows = [{"role": m["role"], "from": f"{m['from_name']} <{m['from_email']}>",
                      "to": ", ".join(a["email"] for a in m["to"] + m["cc"]), "subject": m["subject"],
                      "date": m["date"], "attachments": [a["name"] for a in m["attachments"]], "file": m["file"]}
                     for m in mails]
        filled = len(fields)
        R.done("fill", f"{filled} fields filled, {sum(len(v) for v in slots.values())} documents attached, "
                       f"{len(flags)} item(s) for review")

        R.state["status"] = "done"
        R.state["finished"] = time.time()
        total = round(R.state["finished"] - R.state["started"], 1)
        R.log(f"■ Completed in {total}s · OpenAI cost ${R.state['cost_usd']:.4f} "
              f"(OCR ${R.state.get('ocr_cost_usd', 0):.4f} + research)")

        def apply(c):
            c["fields"] = fields
            c["flags"] = flags
            c["documents"] = slots
            c["mails"] = mail_rows
            c["status"] = "ready_for_review"
            c["engine"] = {**{k: v for k, v in R.state.items()}, "seconds": total,
                           "docs": [{k: d[k] for k in ("name", "kind", "origin")} for d in docs] +
                                   [{"name": m["file"], "kind": f"{m['role']} mail", "origin": "upload"} for m in mails],
                           "facts": {"revert": rf, "certs": facts["certs"].get("fields", {}),
                                     "accreditation": {k: v for k, v in (facts["accreditation"] or {}).items()
                                                       if k not in ("aicte_university", "aicte_college")},
                                     "passing": {k: v for k, v in (facts["passing"] or {}).items() if k != "meta"}}}
            for s in c["engine"]["steps"]:
                s.pop("_t", None)
        store.update(cid, apply)
    except Exception as e:
        R.state["status"] = "error"
        R.state["finished"] = time.time()
        R.log(f"✗ pipeline error: {e}")
        R.log(traceback.format_exc()[-1500:])
        store.update(cid, lambda c: c.update(status="error"))
    finally:
        for s in R.state["steps"]:
            s.pop("_t", None)
