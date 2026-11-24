"""Facts → HVOPS form values. Every value carries its source so the reviewer can audit it.

DEFAULTS are ops conventions taken from the HVOPS case closed by an ops user (HVOPS.html) — change here."""
import re
from datetime import datetime

from rapidfuzz import fuzz

from .form_schema import SUBJECTS
from .extract.mail import FREE_MAIL, domain_of, registrable_domain

DEFAULTS = {
    "q_lang": "No",              # ops answered "No" for English documents in both reference cases
    "o_lang": "No",
    "v_branch": "India",         # ops typed the country for Branch Name / Examination Location
    "v_exam_location": "India",
    "o_payment": "No",
    "n_audit": "No",
    "v_cond_status": "Found in Verification Revert",
    "v_degree_type": "Academic",
    "v_source": "EMAIL",
}
DURATION_BY_DEGREE = {"BE": 4, "BTECH": 4, "BARCH": 5, "BPHARM": 4, "MBBS": 5, "BSC": 3, "BCOM": 3, "BA": 3,
                      "BCA": 3, "BBA": 3, "ME": 2, "MTECH": 2, "MBA": 2, "MCA": 2, "MSC": 2, "MCOM": 2, "MA": 2,
                      "DIPLOMA": 3}
NQF = {"Diploma": "Level 5 – Diploma or Equivalent", "Bachelor": "Level 6 – Bachelor or Equivalent",
       "Master": "Level 7 – Master or Equivalent", "Doctorate": "Level 8 – Doctorate or Equivalent"}
MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV",
                                      "DEC"], 1)}


def clean_name(s):
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z .]", " ", s or "")).strip().upper()


def clean_college(s):
    s = re.sub(r"\[.*?\]", "", s or "")
    s = re.sub(r"\s*-\s*(INDIA|India)\s*$", "", s)
    return re.sub(r"\s+", " ", s).strip(" ,-")


def year_of(s):
    m = re.search(r"(19|20)\d{2}", s or "")
    return m.group(0) if m else ""


def mm_yyyy(s):
    if not s:
        return ""
    m = re.search(r"([A-Za-z]{3})[A-Za-z]*\W*((?:19|20)\d{2})", s)
    if m and m.group(1).upper() in MONTHS:
        return f"{MONTHS[m.group(1).upper()]:02d}-{m.group(2)}"
    m = re.search(r"((?:19|20)\d{2})-(\d{2})", s)
    return f"{m.group(2)}-{m.group(1)}" if m else ""


def dd_mm_yyyy(s):
    m = re.search(r"((?:19|20)\d{2})-(\d{2})-(\d{2})", s or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def name_match(doc_name: str, passport: str) -> tuple[str, str]:
    d, p = clean_name(doc_name).replace(".", " ").split(), clean_name(passport).replace(".", " ").split()
    if not d or not p:
        return "", "name missing"
    full, initials, miss = 0, [], []
    pool = list(p)
    for t in d:
        if t in pool:
            full += 1
            pool.remove(t)
        elif len(t) == 1 and any(x.startswith(t) for x in pool):
            x = next(x for x in pool if x.startswith(t))
            initials.append(f"{t} = {x}")
            pool.remove(x)
        else:
            miss.append(t)
    if not miss and full >= 2:
        note = "all name parts present on passport" + (f"; initial {', '.join(initials)}" if initials else "")
        return "Yes- Name is matching on documents", note
    if full >= 1:
        return "Partially matching", f"unmatched: {' '.join(miss)}"
    return "No- Name is not matching on documents", f"unmatched: {' '.join(miss)}"


def level_from_text(t: str) -> str:
    t = (t or "").lower()
    for k, v in (("doctor", "Doctorate"), ("ph.d", "Doctorate"), ("master", "Master"), ("bachelor", "Bachelor"),
                 ("diploma", "Diploma")):
        if k in t:
            return v
    if re.search(r"\bm\.?\s?(sc|com|a|tech|e|ba|ca)\b|\bmba\b|\bmca\b", t):
        return "Master"
    if re.search(r"\bb\.?\s?(sc|com|a|tech|e|ba|ca|arch|pharm)\b", t):
        return "Bachelor"
    return ""


def short_from_text(t: str) -> str:
    u = (t or "").upper()
    table = [("BACHELOR OF ENGINEERING", "BE"), ("BACHELOR OF TECHNOLOGY", "BTECH"), ("BACHELOR OF COMMERCE", "BCOM"),
             ("BACHELOR OF SCIENCE", "BSC"), ("BACHELOR OF ARTS", "BA"), ("BACHELOR OF COMPUTER APPLICATIONS", "BCA"),
             ("BACHELOR OF BUSINESS ADMINISTRATION", "BBA"), ("BACHELOR OF ARCHITECTURE", "BARCH"),
             ("MASTER OF BUSINESS ADMINISTRATION", "MBA"), ("MASTER OF COMPUTER APPLICATIONS", "MCA"),
             ("MASTER OF TECHNOLOGY", "MTECH"), ("MASTER OF ENGINEERING", "ME"), ("MASTER OF SCIENCE", "MSC"),
             ("MASTER OF COMMERCE", "MCOM"), ("MASTER OF ARTS", "MA")]
    for k, v in table:
        if k in u:
            return v
    m = re.match(r"\s*([A-Z]\.?\s?[A-Z]{1,4}\.?)\b", u)
    return short_key(m.group(1)) if m else ""


def short_key(s):
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def build(case: dict, facts: dict) -> tuple[dict, list[dict], str]:
    """Returns (fields, flags, remarks)."""
    F, flags = {}, []
    rv = facts.get("revert", {}).get("fields", {})
    rv_src = f"University revert · {facts.get('revert', {}).get('source', '')}"
    ce = facts.get("certs", {}).get("fields", {})
    ce_src = f"Degree/Transcript ({facts.get('certs', {}).get('method', '')})"
    acc = facts.get("accreditation") or {}
    pas = facts.get("passing") or {}
    rmail = facts.get("revert_mail") or {}
    resp = facts.get("respondent") or {}
    mo = case.get("mohre", {})
    online = facts.get("mode") == "online"
    on = facts.get("online") or {}
    on_src = on.get("sources", {})
    if online:
        rv_src = f"Online portal · {facts.get('revert', {}).get('source', '')}"

    def osrc(key, default=""):
        """Provenance label for a value read from a portal screenshot: 'Online portal · host (file)'."""
        s = on_src.get(key) or {}
        host = re.sub(r"^https?://([^/]+).*$", r"\1", s.get("url", "")) if s.get("url") else ""
        return f"Online portal · {host or s.get('doc', '')}" if s else default

    def put(key, value, source, note="", flag=""):
        if value in (None, ""):
            return
        F[key] = {"value": value, "source": source, "note": note, "flag": flag}

    # ---------- MOHRE (case initiation data, read-only) ----------
    for k, mk in [("m_applicant_full_name", "applicant_full_name"), ("m_institute_id", "institute_id"),
                  ("m_institute_details", "institute_details"), ("m_institute_name", "institute_name"),
                  ("m_country_code", "country_code"), ("m_country_name", "country_name"),
                  ("m_study_level", "study_level"), ("m_cert_title", "cert_title"), ("m_study_start", "study_start"),
                  ("m_study_end", "study_end"), ("m_subject_id", "subject_id"), ("m_subjects", "subjects")]:
        put(k, mo.get(mk, ""), "Case initiation (MOHRE API)")
    put("n_passport_name", case.get("passport_name") or mo.get("applicant_full_name"), "Case initiation (passport)")

    # ---------- core facts with cross-checks ----------
    univ = acc.get("canonical_university") or rv.get("university", "").split(",")[0].strip() or ce.get("university", "")
    univ_src = "UGC/AICTE official record" if acc.get("canonical_university") else (rv_src if rv else ce_src)
    college = clean_college(rv.get("institution", "")) or clean_college(ce.get("college", ""))
    doc_name = ce.get("candidate_name") or rv.get("name", "")
    regno_rev = re.sub(r"\D", "", rv.get("registration_no", ""))
    regno_doc = re.sub(r"\D", "", ce.get("register_no", ""))
    regno = rv.get("registration_no") or re.sub(r"/.*$", "", ce.get("register_no", ""))
    year = year_of(rv.get("year_of_passing")) or year_of(ce.get("exam_month_year")) or year_of(ce.get("last_appearance"))
    rv_degree = rv.get("degree") or rv.get("branch", "")
    level = ce.get("degree_level") or level_from_text(rv_degree)
    dshort = short_key(ce.get("degree_short")) or short_from_text(rv_degree)
    title_doc = re.sub(r"(?i)^degree of\s+", "", ce.get("degree_title", "") or rv.get("degree", "")).strip()
    title_doc = re.sub(r"\s+", " ", title_doc)
    letters = [c for c in title_doc if c.isalpha()]
    mostly_upper = letters and sum(c.isupper() for c in letters) / len(letters) > 0.6
    title_display = title_doc.title().replace(" In ", " in ").replace(" Of ", " of ") if mostly_upper else title_doc
    major = ce.get("major") or re.sub(r"(?i)^\s*[A-Z.]+\s+|\(.*?\)", "", rv.get("branch", "")).strip()
    status = rv.get("status", "")
    genuine = bool(re.search(r"(?i)\bgenuine\b", status)) and not re.search(r"(?i)not\s+genuine|fake", status)
    if online:
        # the university's own portal shows the record: genuine when the record is found and complete
        genuine = bool(rv.get("_found") and rv.get("_complete"))
        nc = (rv.get("_courses") or {}).get("not_completed") or []
        if rv.get("_found") and nc:
            flags.append({"level": "error", "field": "o_result",
                          "msg": f"Portal shows {len(nc)} course(s) not completed: {', '.join(nc[:8])}"})
        elif rv.get("_found") and not rv.get("_complete"):
            flags.append({"level": "warn", "field": "o_result",
                          "msg": "Portal record found but no completion/result status was read — check the screenshot"})
        if not rv.get("_found"):
            flags.append({"level": "error", "field": "revert_1",
                          "msg": "Enrolment/name could not be read from the online portal screenshots"})

    if rv.get("name") and doc_name and clean_name(rv["name"]) != clean_name(doc_name):
        flags.append({"level": "warn", "field": "q_applicant_name",
                      "msg": f"Name differs: revert '{rv['name']}' vs degree '{doc_name}'"})
    if regno_rev and regno_doc and regno_rev != regno_doc:
        flags.append({"level": "error", "field": "n_enrollment",
                      "msg": f"Register no. mismatch: revert {regno_rev} vs degree {regno_doc}"})
    yr_doc = year_of(ce.get("exam_month_year"))
    if year and yr_doc and year != yr_doc:
        flags.append({"level": "warn", "field": "q_year", "msg": f"Year mismatch: revert {year} vs degree {yr_doc}"})
    if rv.get("class") and ce.get("class_awarded") and clean_name(rv["class"]) != clean_name(ce["class_awarded"]):
        flags.append({"level": "warn", "field": "o_result",
                      "msg": f"Class differs: revert '{rv['class']}' vs degree '{ce['class_awarded']}'"})
    if online:
        pass                                   # online-specific checks above
    elif not rv:
        flags.append({"level": "error", "field": "revert_1", "msg": "No university revert found in the uploads"})
    elif not status:
        flags.append({"level": "warn", "field": "o_genuine", "msg": "Revert does not state a verification status"})
    elif not genuine:
        flags.append({"level": "error", "field": "o_genuine", "msg": f"Revert status is '{status}'"})

    title_src = ce_src if ce.get("degree_title") else rv_src
    level_src = ce_src if ce.get("degree_level") else rv_src
    table_rev = facts.get("revert", {}).get("method", "").startswith("table")
    verified_date = (dd_mm_yyyy(rv.get("verified_date")) if table_rev else "") or dd_mm_yyyy(rmail.get("date", ""))
    verified_src = rv_src if table_rev and rv.get("verified_date") else "Date of the university's reply e-mail"
    if online:
        verified_date = rv.get("verified_date", "")
        verified_src = osrc("verified_date", rv_src) + " ('Status as on' date)"
    india = "india" in (rv.get("institution", "") + rv.get("university", "") + mo.get("country_name", "") +
                        mo.get("country_code", "")).lower() or bool(acc.get("ugc") or acc.get("aicte_university"))
    country, country_name = ("India", "Republic of India") if india else ("", "")
    duration = DURATION_BY_DEGREE.get(dshort) or DURATION_BY_DEGREE.get("DIPLOMA" if level == "Diploma" else "", 0)
    pursuit = "Engineering Qualification" if acc.get("technical") or re.search(r"(?i)engineering|technology", title_doc + major + " " + ce.get("notes", "")) \
        else ("Management Qualification" if re.search(r"(?i)management|business", title_doc) else "Academic Qualification")
    inst_type = "University Only" if univ else ("Institute Only" if college else "")
    full_time = re.search(r"(?i)full[\s-]*time|\bregular\b", rv.get("branch", "") + " " + rv.get("mode_of_study", ""))
    lateral = ce.get("first_semester", "").lstrip("0") in ("3",) or "lateral" in (ce.get("notes", "").lower())
    transfer_note = "Transcript starts at Semester 03 → lateral entry (after diploma), not a transfer" if lateral else ""
    subj = max(SUBJECTS, key=lambda s: fuzz.ratio(s.lower(), major.lower())) if major else ""
    if subj and fuzz.ratio(subj.lower(), major.lower()) < 88:
        subj = "Others"

    # ---------- 2. Qualification document details ----------
    put("q_country", country, univ_src)
    put("q_inst_type", inst_type, "Rule: university named on documents", "ops convention for affiliated colleges")
    put("q_university", univ, univ_src)
    put("q_college", college, rv_src if rv.get("institution") else ce_src)
    put("q_applicant_name", doc_name, ce_src if ce.get("candidate_name") else rv_src)
    put("q_year", year, rv_src if rv.get("year_of_passing") else ce_src)
    put("q_cert_title", title_display, title_src)
    put("q_study_level", level, level_src)
    put("q_arab", "Other Country (If required raise insufficiency for marksheet/transcript)" if country else "",
        "Rule: institution outside the Arab region")
    put("q_duration", f"{duration} Year" if duration else "", f"Standard duration of {ce.get('degree_short') or dshort}",
        transfer_note)
    put("q_transfer", "Regular Student (Not Transfer Student)", "Transcript (single institution)", transfer_note)
    put("q_lang", DEFAULTS["q_lang"], "Ops convention (precedent case)",
        f"documents are in {ce.get('document_language') or 'English'}")

    # ---------- 3. Name check ----------
    name_src = ce_src if ce.get("candidate_name") else rv_src
    put("n_doc_name", doc_name, name_src)
    match, note = name_match(doc_name, case.get("passport_name") or mo.get("applicant_full_name", ""))
    put("n_match", match, "Engine: degree name vs passport name", note,
        "" if match.startswith("Yes") else "review")
    put("n_enrollment", regno, rv_src if rv.get("registration_no") else ce_src,
        "matches degree Reg.No." if regno_rev and regno_rev == regno_doc else "")
    put("n_audit", DEFAULTS["n_audit"], "Default")

    # ---------- Certification verification details ----------
    put("v_institute", univ, univ_src)
    put("v_country_name", country_name, univ_src)
    code_only = online and not title_doc and re.fullmatch(r"[A-Z]{2,8}", rv.get("branch", "") or "")
    put("v_cert_title", title_doc.upper() if title_doc else rv.get("branch", "").upper(), title_src,
        "programme code shown by the portal — confirm the full title on the degree" if code_only else "",
        "review" if code_only else "")
    if code_only:
        flags.append({"level": "warn", "field": "v_cert_title",
                      "msg": f"Degree title not readable from the documents — portal shows programme code {rv['branch']}; "
                             f"type the full title from the degree"})
    if online and rv.get("start_mm_yyyy"):
        put("v_start", rv["start_mm_yyyy"], osrc("start_mm_yyyy", rv_src) + " · Admission Year",
            f"portal: Admission Year {rv.get('admission', '')}"
            + (f"; admission valid upto {rv['valid_upto']}" if rv.get("valid_upto") else ""))
        if mo.get("study_start") and mo["study_start"] != rv["start_mm_yyyy"]:
            flags.append({"level": "warn", "field": "v_start",
                          "msg": f"Start date differs: portal {rv['start_mm_yyyy']} vs initiation {mo['study_start']}"})
    else:
        put("v_start", "Not Disclosed", "Online portal screenshots do not show a start date" if online
            else "Revert does not state a start date",
            f"transcript: first exams {ce.get('earliest_exam_month_year')}" + (f", {transfer_note}" if lateral else "")
            if ce.get("earliest_exam_month_year") else "")
    end = mm_yyyy(rv.get("year_of_passing")) or (rv.get("end_mm_yyyy") if online else "") or \
        mm_yyyy(ce.get("last_appearance")) or mm_yyyy(ce.get("exam_month_year"))
    end_src = (osrc("end_mm_yyyy", rv_src) if online and rv.get("end_mm_yyyy") else rv_src) \
        if rv.get("year_of_passing") or (online and rv.get("end_mm_yyyy")) else ce_src
    put("v_end", end, end_src, f"admission valid upto {rv['valid_upto']} (validity, not completion)"
        if online and rv.get("valid_upto") else "", "review" if online and end and end_src == ce_src else "")
    if online and end and mo.get("study_end") and mo["study_end"] != end:
        flags.append({"level": "warn", "field": "v_end",
                      "msg": f"End date differs: {end} vs initiation {mo['study_end']}"})
    put("v_pursuit", pursuit, "Rule: programme type")
    if online and rv.get("mode_of_study"):
        explicit = rv.get("_mode_explicit")
        put("v_mode", rv["mode_of_study"], osrc("mode_of_study", rv_src) if explicit else "Online portal + university type",
            rv.get("_mode_how", ""), "" if explicit else "review")
        put("v_mode_status", "Mentioned in Verified response", rv_src, rv.get("_mode_how", ""),
            "" if explicit else "review")
    else:
        put("v_mode", "Full Time - On Campus" if full_time else "", rv_src, rv.get("mode_of_study") or rv.get("branch", ""))
        put("v_mode_status", "Mentioned in Verified response" if full_time else "", rv_src)
    put("v_branch", DEFAULTS["v_branch"] if country else "", "Ops convention (precedent case)")
    put("v_exam_location", DEFAULTS["v_exam_location"] if country else "", "Ops convention (precedent case)")
    put("v_country_study", country_name, univ_src)
    put("v_award", year, rv_src if rv.get("year_of_passing") else ce_src,
        f"degree issued {ce.get('issue_date')}" if ce.get("issue_date") else "")
    put("v_subjects", subj, ce_src, f"major on degree: {major}" if subj == "Others" else "")
    put("v_country", country, univ_src)
    put("v_inst_type", inst_type, "Rule: university named on documents")
    put("v_applicant_name", doc_name, name_src)

    # ---------- Academic programme ----------
    put("v_nqf", NQF.get(level, ""), "Rule: study level")
    put("v_compat", level if level in ("Diploma", "Bachelor", "Master", "Doctorate") else "", "Rule: study level")
    put("v_duration", F.get("q_duration", {}).get("value", ""), F.get("q_duration", {}).get("source", ""), transfer_note)
    put("v_arab", F.get("q_arab", {}).get("value", ""), "Rule: institution outside the Arab region")
    put("v_transfer", "Regular Student (Not Transfer Student)", "Transcript (single institution)", transfer_note)
    if online:
        put("v_cond_status", "Found on University Website" if pas.get("found") else "Not Found",
            "Passing criteria search (official university domain)",
            "" if pas.get("found") else pas.get("reason", ""), "" if pas.get("found") else "review")
    else:
        put("v_cond_status", DEFAULTS["v_cond_status"], "Ops convention (precedent case)")
    if pas.get("found"):
        cond = (f"As per {pas.get('regulation') or pas.get('document_title')}, clause {pas.get('clause_heading')}: "
                f"{pas.get('criteria')}")
        put("v_cond", cond, f"Official university document ({', '.join(pas.get('domains', []))}), page {pas.get('page')}",
            pas.get("url", ""), "" if pas.get("verified") else "review")
        if not pas.get("verified"):
            flags.append({"level": "warn", "field": "v_cond", "msg":
                          "Regulation year not readable from the transcript — confirm the cached regulation applies"
                          if pas.get("loose") else "Passing-criteria numbers could not be confirmed in the document text — check"})
    else:
        flags.append({"level": "warn", "field": "v_cond",
                      "msg": f"Passing criteria not found automatically ({pas.get('reason', 'not run')})"})
    if online:
        full = bool(rv.get("_found") and rv.get("_complete") and rv.get("name"))
        put("v_response_type", "Full response received" if full else ("Partial response received" if rv.get("_found") else ""),
            rv_src, "enrolment, name and completion status shown by the portal" if full else "")
        put("v_source", "ONLINE", "Verified on the university's online portal", ", ".join(on.get("domains", [])))
    else:
        put("v_response_type", "Full response received" if rv and status and len(rv) >= 5 else
            ("Partial response received" if rv else ""), rv_src)
        put("v_source", DEFAULTS["v_source"] if rmail else "", "Revert received by e-mail")
    put("v_university", univ, univ_src)
    put("v_college", college, rv_src if rv.get("institution") else ce_src)
    put("v_study_level", level, level_src)
    sender = rmail.get("from_email", "")
    dom = registrable_domain(domain_of(sender)) if sender else ""
    if online and on.get("domains"):
        pdom = on["domains"][0]
        uni_dom = registrable_domain((acc.get("ugc") or {}).get("website", "") or "")
        official = bool(re.search(r"\.(ac\.in|edu\.in|edu|gov\.in|nic\.in|ac\.[a-z]{2}|edu\.[a-z]{2})$", pdom)) or pdom == uni_dom
        put("v_email_type", "Official" if official else "Public", f"Portal domain {pdom}",
            ("matches university website " + uni_dom) if uni_dom and uni_dom == pdom else "", "" if official else "review")
        put("v_domain", pdom, "Online portal URL", ", ".join(p.get("url", "") for p in on.get("portals", [])))
        if uni_dom and uni_dom != pdom:
            flags.append({"level": "warn", "field": "v_domain",
                          "msg": f"Portal domain {pdom} differs from university website domain {uni_dom}"})
        if not official:
            flags.append({"level": "warn", "field": "v_email_type", "msg": f"Portal domain {pdom} is not an official academic domain"})
        dom = ""                                # skip the e-mail sender checks below
    if dom:
        official = dom not in FREE_MAIL
        uni_dom = registrable_domain((acc.get("ugc") or {}).get("website", "") or "")
        put("v_email_type", "Official" if official else "Public", f"Sender domain {domain_of(sender)}",
            ("matches university website " + uni_dom) if uni_dom and uni_dom == dom else "",
            "" if official else "review")
        put("v_domain", dom, f"Revert sender {sender}")
        if uni_dom and uni_dom != dom and official:
            flags.append({"level": "warn", "field": "v_domain",
                          "msg": f"Revert domain {dom} differs from university website domain {uni_dom}"})
        if not official:
            flags.append({"level": "warn", "field": "v_email_type", "msg": f"Revert came from a public mailbox ({dom})"})
    put("v_degree_type", DEFAULTS["v_degree_type"], "Rule: academic degree")
    lang = (ce.get("document_language") or "English").split()[0].title()
    put("v_ia_lang", "English" if rv else "", "Online portal language" if online else "Revert language")
    put("v_degree_lang", lang if lang in ("English", "Arabic", "Hindi") else "Other", ce_src)

    # ---------- Accreditation ----------
    if acc:
        put("a_status", acc.get("status"), f"{acc.get('body_short') or 'UGC/AICTE'} official list",
            "", "" if acc.get("status") == "Accredited" else "review")
        put("a_country", acc.get("country"), "Accreditation body country")
        put("a_url", acc.get("url"), "Official list used as proof")
        put("a_body", acc.get("body"), "Engine: technical programme → AICTE, otherwise UGC" if acc.get("body_short") else "")
        put("a_year", acc.get("year"), "Approval session of the list (2025-26 → 2026)" if acc.get("body_short") == "AICTE"
            else "Year of check")
        if acc.get("pdf"):
            put("a_proof", "accreditation.pdf", "Generated evidence PDF")
        if acc.get("status") != "Accredited":
            flags.append({"level": "error", "field": "a_status",
                          "msg": f"'{univ}' not found in UGC or AICTE lists — manual accreditation check"})

    # ---------- Quality ----------
    put("o_result", "Pass" if genuine and not any(f["level"] == "error" for f in flags) else
        ("Discrepancy" if rv else ""), "Engine: revert status + cross-checks")
    put("o_genuine", "Document Genuine" if genuine else ("Unable to confirm" if rv else ""), rv_src, f"status: {status}")
    put("o_date", verified_date, verified_src)
    put("o_enrollment", regno, rv_src)
    put("o_lang", DEFAULTS["o_lang"], "Ops convention (precedent case)")
    put("o_resp_name", resp.get("name"), "Revert e-mail sender / signature")
    put("o_resp_email", resp.get("email"), "Revert e-mail header")
    put("o_resp_desig", resp.get("designation"), "Revert e-mail sender / signature")
    paid = re.search(r"(?i)\b(fee|payment|paid|remit)\b", (rmail.get("body_text") or ""))
    put("o_payment", "Yes" if paid else DEFAULTS["o_payment"],
        "Online portal — instant, no fee" if online else "Revert e-mail text",
        "mail mentions a fee/payment" if paid else "", "review" if paid else "")
    put("o_son_of", "Yes" if ce.get("son_of_mentioned", "").lower() == "yes" else "No", ce_src)
    put("o_transfer_credit", "Not Applicable - Not transfer student", "Not a transfer student")

    # ---------- remarks ----------
    bits = []
    if online:
        crs = rv.get("_courses") or {}
        for p in on.get("portals", []):
            pf = p["fields"]
            bits.append(f"{p['label']}: verified online on {p['host'] or p['doc']}"
                        + (f" (status as on {pf['status_as_on']})" if pf.get("status_as_on") else "") + ".")
        bits.append(", ".join(x for x in [
            rv.get("name"), f"Enrolment {rv['registration_no']}" if rv.get("registration_no") else "",
            f"Programme {rv['programme']}" if rv.get("programme") else "",
            f"{crs['completed']}/{crs['total']} courses COMPLETED" if crs.get("total") else "",
            f"admission {rv['admission']}" if rv.get("admission") else "",
            f"mode {rv['mode_of_study']}" if rv.get("mode_of_study") else ""] if x) + ".")
    elif rv:
        bits.append(f"Verified via {rv.get('_title') or 'university revert'}"
                    + (f" (App No {rv['app_no']}" if rv.get("app_no") else "")
                    + (f", verified {verified_date}" if verified_date else "")
                    + (")" if rv.get("app_no") else "") + f": status {status or 'n/a'}.")
        bits.append(", ".join(x for x in [rv.get("name"), f"Reg No {rv.get('registration_no')}" if rv.get("registration_no") else "",
                                          rv.get("branch"), rv.get("class"), rv.get("year_of_passing"),
                                          clean_college(rv.get("institution", "")),
                                          rv.get("mode_of_college", "").split(" Verifier")[0]] if x) + ".")
    if acc.get("body_short"):
        a = acc.get("aicte_university") or acc.get("aicte_college")
        bits.append(f"Accreditation: {acc['body_short']}" + (f" 2025-26 list row {a['sr']} (p.{a['page']})" if a and acc['body_short'] == 'AICTE' else "")
                    + (f"; UGC {acc['ugc']['type']} {acc['ugc']['status']}" if acc.get("ugc") else "")
                    + (f" ({acc['summary']})" if acc.get("summary") else "") + ".")
    elif acc.get("summary"):
        bits.append(f"Accreditation: {acc['summary']}.")
    if lateral:
        bits.append("Note: lateral entry (transcript from Sem 03).")
    remarks = " ".join(bits)
    put("o_remarks", remarks, "Engine summary")
    return F, flags, remarks
