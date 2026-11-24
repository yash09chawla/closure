"""Auto-close orchestrator. Live state lives in RUNS (polled by the UI) and is persisted to case.json."""
import asyncio
import re
import shutil
import time
import traceback
from pathlib import Path

from rapidfuzz import fuzz

from . import mapper, store
from .evidence import browser, render
from .extract import certs as certsmod
from .extract import docs as docsmod
from .extract import online as onlinemod
from .extract import revert as revertmod
from .research import accreditation, passing

RUNS: dict[str, dict] = {}

STEPS = [("ingest", "Reading & classifying documents"), ("revert", "Parsing university revert (e-mail)"),
         ("online", "Online database — reading portal screenshots"),
         ("certs", "Reading degree & transcript"), ("mails", "Printing e-mails / online reverts to PDF"),
         ("accreditation", "Accreditation check — UGC / AICTE"), ("passing", "Passing criteria — official university site"),
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
    R = Run(cid)
    case = store.load(cid)
    work, out = store.work_dir(cid), store.out_dir(cid)
    for p in list(work.iterdir()) + list(out.iterdir()):
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    files = sorted(store.uploads_dir(cid).iterdir())
    facts = {}
    try:
        # 1. ingest
        R.start("ingest")
        docs, mails = await asyncio.to_thread(docsmod.ingest, files, work)
        kinds = {}
        for d in docs:
            kinds.setdefault(d["kind"], []).append(d)
        for d in kinds.get("mail_screenshot", []):
            em = re.search(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", d["text"])
            d["role"] = "initiation" if em and "helloverify" in em.group(0).lower() else "revert"
        R.done("ingest", f"{len(files)} files → {len(docs)} documents, {len(mails)} e-mail(s): " +
               ", ".join(f"{k}×{len(v)}" for k, v in kinds.items()))
        for d in docs:
            R.log(f"   {d['name']}: {d['kind']}" + (f" ({d['origin']})" if d["origin"] != "upload" else ""))
        init_mails = [m for m in mails if m["role"] == "initiation"]
        rev_mails = [m for m in mails if m["role"] == "revert"]
        rmail = rev_mails[0] if rev_mails else None

        # 2. revert (deterministic first)
        R.start("revert")
        rev_docs = [d for d in kinds.get("verification_report", [])]
        if rmail:
            rev_docs = sorted(rev_docs, key=lambda d: d.get("parent") != rmail["id"])
        rev = await asyncio.to_thread(revertmod.parse_revert, rmail, rev_docs)
        R.cost(rev.get("meta"))
        facts["revert"] = rev
        facts["revert_mail"] = rmail
        facts["respondent"] = revertmod.respondent_from_mail(rmail) if rmail else {}
        rf = rev["fields"]
        portal_docs = kinds.get("online_portal", [])
        if rf:
            R.done("revert", f"{rev['method']} parse of {rev['source'] or '—'}: status {rf.get('status', '?')}, "
                             f"{len([k for k in rf if not k.startswith('_')])} fields")
        elif portal_docs and not mails:
            R.done("revert", "no e-mail revert — online-database verification", "skip")
        else:
            R.done("revert", "no revert found", "warn")

        # 2b. online database (screenshots of the university's own portal) — runs in parallel with 3a/3c
        facts["online"] = {}
        email_rf = bool(rf)

        async def t_online():
            R.start("online")
            if not portal_docs:
                R.done("online", "no online portal screenshots", "skip")
                return {}
            try:
                portals = list(await asyncio.gather(*[asyncio.to_thread(onlinemod.read_portal, d, work)
                                                      for d in portal_docs]))
            except Exception as e:
                R.done("online", f"failed: {e}", "error")
                R.log("".join(traceback.format_exception(e))[-800:])
                return {}
            for p in portals:
                R.cost(p.get("meta"))
                if p.get("vision_error"):
                    R.log(f"   vision read failed for {p['doc']} → local OCR used: {p['vision_error']}")
            on = onlinemod.combine(portals)
            facts["online"] = on
            of = on["fields"]
            for p in on["portals"]:
                R.log(f"   {p['doc']}: {p['label']} · {p['host'] or 'URL not visible'} · " +
                      ", ".join(f"{k}={v}" for k, v in p["fields"].items()
                                if not k.startswith("_") and not k.endswith(("_mm_yyyy", "_dd_mm_yyyy")))[:300])
            R.done("online", f"{'/'.join(sorted({p.get('method', 'local-ocr') for p in portals}))}: "
                             f"{len(portals)} screenshot(s) from {', '.join(on['domains']) or '?'}: "
                             f"enrolment {of.get('registration_no', '?')} · {of.get('name', '?')} · "
                             f"{of.get('programme', '')} · {of.get('status') or 'record not found'}"
                             + (f" · admission {of['admission']}" if of.get("admission") else ""),
                   "done" if on["found"] else "warn")
            if not email_rf and of:                # the portal IS the verification revert (updated in place:
                rf.update(of)                      # facts["revert"]["fields"] is the same dict)
                rf["branch"] = of.get("programme", "")
                rev.update(method="online", source=", ".join(p["host"] or p["doc"] for p in on["portals"]))
            return on

        online_task = asyncio.create_task(t_online())

        def university_now():
            return rf.get("university") or case["mohre"].get("institute_name") or ""

        def degree_hint_now():
            return rf.get("branch") or rf.get("degree") or case["mohre"].get("cert_title", "")

        # 3a certs
        async def t_certs():
            R.start("certs")
            deg = kinds.get("degree", [])
            tr = kinds.get("transcript", [])
            if not deg and not tr:
                R.done("certs", "no degree/transcript uploaded", "warn")
                return {"fields": {}, "method": "none"}
            await asyncio.to_thread(docsmod.upright_docs, deg + tr, work)   # sideways scans → upright for the model
            res = await asyncio.to_thread(certsmod.extract, deg, tr)
            R.cost(res.get("meta"))
            f = res["fields"]
            R.done("certs", f"{res['method']}: {f.get('candidate_name', '?')} · {f.get('degree_short', '')} "
                            f"{f.get('major', '')} · {f.get('class_awarded', '')} · reg {f.get('register_no', '')}")
            return res

        # 3b mail PDFs + online-revert PDFs (screenshot + link, the layout ops use)
        async def t_mails():
            R.start("mails")
            made = {"initiation": [], "revert": [], "online": []}
            for m in mails:
                label = "Initiation e-mail (HV → institution)" if m["role"] == "initiation" else \
                    "Verification revert e-mail (institution → HV)"
                name = ("Initiation Mail - " if m["role"] == "initiation" else "Revert Mail - ") + _safe(m["subject"], 110) + ".pdf"
                p = out / name
                await browser.html_to_pdf(render.mail_html(m, label), str(p), width_px=1100)
                made[m["role"]].append(p)
            await online_task
            for p in (facts["online"] or {}).get("portals", []):
                pf = p["fields"]
                rows = [("Enrolment / Roll No", pf.get("enrollment_no") or pf.get("roll_no")),
                        ("Name", pf.get("welcome_name") or pf.get("name")), ("Programme", pf.get("programme")),
                        ("Admission Year", pf.get("admission_year")), ("Admission valid upto", pf.get("valid_upto")),
                        ("Year of passing", pf.get("year_of_passing")), ("Result", pf.get("result")),
                        ("Courses", f"{p['courses']['completed']} of {p['courses']['total']} COMPLETED"
                         if p["courses"]["total"] else ""),
                        ("Regional / Study Centre", " / ".join(x for x in (pf.get("regional_centre"), pf.get("study_centre")) if x)),
                        ("Status as on", pf.get("status_as_on"))]
                f = out / f"{p['label']} - {_safe(p['host'] or Path(p['doc']).stem, 60)}.pdf"
                await browser.html_to_pdf(render.online_html(p, rows), str(f), a4=True)
                made["online"].append((p, f))
            R.done("mails", ", ".join(x for x in [
                f"{len(made['revert'])} revert, {len(made['initiation'])} initiation mail PDF(s)" if mails else "",
                f"{len(made['online'])} online revert PDF(s)" if made["online"] else ""] if x)
                   or "no e-mails or portal screenshots uploaded", "done" if mails or made["online"] else "warn")
            return made

        # 3c accreditation — starts at once with the best name known; re-checked if the portal names another university
        async def t_acc():
            university = university_now()
            if not university and portal_docs:
                await online_task
                university = university_now()
            R.start("accreditation", university)
            if not university:
                R.done("accreditation", "university unknown", "warn")
                return {}

            async def check(name):
                return await accreditation.run(name, rf.get("institution", ""), degree_hint_now(), work,
                                               out / f"Accreditation - {_safe(name.split(',')[0])}.pdf", R.log)
            res = await check(university)
            if portal_docs and not email_rf:
                await online_task
                pu = rf.get("university", "")
                if pu and fuzz.token_set_ratio(pu.lower(), university.lower()) < 90:
                    R.log(f"portal names '{pu}' (case said '{university}') — re-checking accreditation")
                    if res.get("pdf"):
                        Path(res["pdf"]).unlink(missing_ok=True)
                    res = await check(pu)
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
            await online_task
            university, degree_hint = university_now(), degree_hint_now()
            R.start("passing")
            uni = (acc or {}).get("canonical_university") or university.split(",")[0]
            res = await passing.run(
                uni, ((acc or {}).get("ugc") or {}).get("website", ""),
                ([rmail["from_email"].split("@")[-1]] if rmail else []) + (facts["online"] or {}).get("domains", []),
                ce.get("degree_short") or degree_hint.split()[0] if degree_hint else ce.get("degree_short", ""),
                ce.get("degree_title") or degree_hint, ce.get("regulation", ""),
                rf.get("year_of_passing") or ce.get("exam_month_year", ""),
                "affiliat" in rf.get("mode_of_college", "").lower() or bool(rf.get("institution")),
                work, out / f"Passing Criteria - {_safe(uni)}.pdf", R.log)
            R.cost(res.get("meta"))
            if res.get("found"):
                R.done("passing", f"{res['clause_heading']} (p.{res['page']}) "
                                  f"{'from knowledge cache' if res.get('cached') else 'found by search'}"
                                  f"{'' if res.get('verified') else (' — regulation year not confirmed' if res.get('loose') else ' — numbers NOT confirmed')}",
                       "done" if res.get("verified") else "warn")
            else:
                R.done("passing", res.get("reason", "not found"), "warn")
                # closure document records the negative result too
                pf = out / f"Passing Criteria - NOT FOUND - {_safe(uni)}.pdf"
                doms = passing.official_domains(((acc or {}).get("ugc") or {}).get("website", ""),
                                                (facts["online"] or {}).get("domains", []) +
                                                ([rmail["from_email"].split("@")[-1]] if rmail else []))
                html = render.evidence_html(
                    [("Passing Criteria", "NOT FOUND"), ("University", uni),
                     ("Programme", ce.get("degree_title") or degree_hint),
                     ("Official domain(s) searched", ", ".join(doms) or "unknown")],
                    [{"heading": "Result of the automatic search",
                      "frame_html": f'<div class="miss">{render.e(res.get("reason", "not found"))}'
                                    + (f'<br>Last URL tried: {render.e(res["url"])}' if res.get("url") else "")
                                    + "</div>"}],
                    f"Generated {time.strftime('%d-%m-%Y %H:%M:%S')} by HV Closure Engine. Only the university's own "
                    f"domain is accepted as a source — attach the regulation manually if ops find it elsewhere.")
                await browser.html_to_pdf(html, str(pf), a4=True)
                res["pdf_missing"] = str(pf)
            return res

        pass_task = asyncio.create_task(t_pass())
        results = await asyncio.gather(certs_task, mails_task, acc_task, pass_task, return_exceptions=True)
        await online_task
        mode = "online" if facts["online"] and rev.get("method") == "online" else "email"
        facts["mode"] = mode
        names = ["certs", "mails", "accreditation", "passing"]
        for n, r in zip(names, results):
            if isinstance(r, Exception):
                R.done(n, f"failed: {r}", "error")
                R.log("".join(traceback.format_exception(r))[-800:])
        facts["certs"], mail_pdfs, facts["accreditation"], facts["passing"] = [
            ({} if isinstance(r, Exception) else r) for r in results]
        mail_pdfs = mail_pdfs or {"initiation": [], "revert": [], "online": []}

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
        # online database: result/grade-card portal = Revert 1 (online screenshot); other portal pages = Revert 2
        for p, f in mail_pdfs.get("online", []):
            slot = "revert_1" if p["type"] == "result" or not any(
                q["type"] == "result" for q, _ in mail_pdfs["online"]) else "revert_2"
            slots[slot].append(_file_entry(cid, f, f"Generated: {p['label']} — {p['host'] or 'portal'} screenshot + link", True))
        for d in kinds.get("online_portal", []):
            p = next((q for q, _ in mail_pdfs.get("online", []) if q["doc"] == d["name"]), None)
            slot = "revert_1" if (p or {}).get("type") == "result" else "revert_2"
            slots[slot].append(_file_entry(cid, Path(d["path"]), "Uploaded online portal screenshot"))
        if (facts["accreditation"] or {}).get("pdf"):
            slots["accreditation"].append(_file_entry(cid, Path(facts["accreditation"]["pdf"]),
                                                      f"Generated: UGC/AICTE evidence ({facts['accreditation'].get('summary', '')})", True))
        if (facts["passing"] or {}).get("pdf"):
            slots["passing_criteria"].append(_file_entry(cid, Path(facts["passing"]["pdf"]),
                                                         "Generated: official regulation evidence", True))
        elif (facts["passing"] or {}).get("pdf_missing"):
            slots["passing_criteria"].append(_file_entry(cid, Path(facts["passing"]["pdf_missing"]),
                                                         "Generated: passing criteria NOT FOUND note", True))
        for k in ("degree", "transcript", "diploma", "other"):
            for d in kinds.get(k, []):
                if d.get("parent"):
                    continue
                slots["other"].append(_file_entry(cid, Path(d["path"]), k.title()))
        if not slots["verification_proof"] and mode == "email":
            flags.append({"level": "warn", "field": "verification_proof",
                          "msg": "No initiation e-mail among the uploads — attach it if the client requires it"})
        online_rows = [{"doc": p["doc"], "label": p["label"], "type": p["type"], "url": p["url"], "host": p["host"],
                        "domain": p["domain"], "fields": {k: v for k, v in p["fields"].items() if not k.startswith("_")},
                        "courses": p["courses"], "method": p.get("method", "local-ocr"),
                        "pdf": _file_entry(cid, f, "")["url"],
                        "shot": _file_entry(cid, Path(p["path"]), "")["url"] if Path(p["path"]).is_relative_to(
                            store.case_dir(cid)) else ""}
                       for p, f in mail_pdfs.get("online", [])]
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
        R.log(f"■ Completed in {total}s · LLM cost ${R.state['cost_usd']:.4f}")

        def apply(c):
            c["fields"] = fields
            c["flags"] = flags
            c["documents"] = slots
            c["mails"] = mail_rows
            c["online"] = online_rows
            c["verification_mode"] = mode
            c["status"] = "ready_for_review"
            c["engine"] = {**{k: v for k, v in R.state.items()}, "seconds": total,
                           "docs": [{k: d[k] for k in ("name", "kind", "origin")} for d in docs] +
                                   [{"name": m["file"], "kind": f"{m['role']} mail", "origin": "upload"} for m in mails],
                           "facts": {"mode": mode, "revert": rf, "certs": facts["certs"].get("fields", {}),
                                     "online": {k: v for k, v in (facts["online"] or {}).items() if k != "portals"},
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
