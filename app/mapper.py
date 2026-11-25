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
    certs = facts.get("certs", {}) or {}
    ce = certs.get("fields", {})
    ce_src = "Degree/Transcript (OCR)" if certs.get("method") == "openai-ocr" else \
        f"Degree/Transcript ({certs.get('method', '')})"
    ce_low = set(certs.get("low_confidence", []))
    acc = facts.get("accreditation") or {}
    pas = facts.get("passing") or {}
    rmail = facts.get("revert_mail") or {}
    resp = facts.get("respondent") or {}
    mo = case.get("mohre", {})

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
    # the name as printed on the documents: when degree and transcript OCR disagree by a letter or two
    # ("Yachaspati" / "Vachaspati"), keep the reading confirmed by the revert / passport and note the variant
    name_cands = [n for n in certs.get("name_candidates", []) if n] or ([ce["candidate_name"]] if ce.get("candidate_name") else [])
    refs = [x for x in (rv.get("name"), case.get("passport_name"), mo.get("applicant_full_name")) if x]
    name_note = ""
    if len({clean_name(n) for n in name_cands}) > 1 and refs:
        best = max(name_cands, key=lambda n: max(fuzz.token_sort_ratio(clean_name(n), clean_name(r)) for r in refs))
        others = [n for n in name_cands if clean_name(n) != clean_name(best)]
        name_note = f"OCR read '{others[0]}' on another document; '{best}' matches the revert/passport"
        doc_name = best
    else:
        doc_name = (name_cands[0] if name_cands else "") or rv.get("name", "")
    regno_rev = re.sub(r"\D", "", rv.get("registration_no", ""))
    regno_doc = re.sub(r"\D", "", ce.get("register_no", ""))
    regno = rv.get("registration_no") or re.sub(r"/.*$", "", ce.get("register_no", ""))
    year = year_of(rv.get("year_of_passing")) or year_of(ce.get("exam_month_year")) or year_of(ce.get("last_appearance"))
    rv_degree = rv.get("degree") or rv.get("branch", "")
    # the university's own statement of the degree outranks OCR of a header abbreviation; the certificate's
    # printed title is kept when it was actually read from the degree itself
    cert_title_from_degree = (certs.get("source") or {}).get("degree_title") == "degree"
    use_rv_degree = bool(rv.get("degree")) and not cert_title_from_degree
    level = (level_from_text(rv_degree) if use_rv_degree else "") or ce.get("degree_level") or level_from_text(rv_degree)
    dshort = (short_from_text(rv_degree) if use_rv_degree else "") or short_key(ce.get("degree_short")) or short_from_text(rv_degree)
    if rv.get("degree") and ce.get("degree_short") and short_from_text(rv["degree"]) and \
            short_key(ce["degree_short"]) != short_from_text(rv["degree"]):
        flags.append({"level": "warn", "field": "q_cert_title",
                      "msg": f"Degree differs: revert '{rv['degree']}' vs documents '{ce.get('degree_title') or ce['degree_short']}'"})
    title_doc = re.sub(r"(?i)^degree of\s+", "", (rv.get("degree", "") if use_rv_degree else "")
                       or ce.get("degree_title", "") or rv.get("degree", "")).strip()
    title_doc = re.sub(r"\s+", " ", title_doc)
    letters = [c for c in title_doc if c.isalpha()]
    mostly_upper = letters and sum(c.isupper() for c in letters) / len(letters) > 0.6
    title_display = title_doc.title().replace(" In ", " in ").replace(" Of ", " of ") if mostly_upper else title_doc
    rv_major = ""
    if rv.get("degree"):
        m = re.search(r"(?i)\bin\s+(.+)$", rv["degree"]) or re.search(r"\(([^)]+)\)", rv["degree"])
        rv_major = m.group(1).strip() if m else ""
    major = (rv_major if use_rv_degree else "") or ce.get("major") or rv_major or \
        re.sub(r"(?i)^\s*[A-Z.]+\s+|\(.*?\)", "", rv.get("branch", "")).strip()
    status = rv.get("status", "")
    genuine = bool(re.search(r"(?i)\bgenuine\b", status)) and not re.search(r"(?i)not\s+genuine|fake", status)
    for k in sorted(ce_low):
        flags.append({"level": "warn", "field": "q_applicant_name" if k == "candidate_name" else "q_cert_title",
                      "msg": f"Low OCR confidence for '{k}' — check against the document image"})

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
    if not rv:
        flags.append({"level": "error", "field": "revert_1", "msg": "No university revert found in the uploads"})
    elif not status:
        flags.append({"level": "warn", "field": "o_genuine", "msg": "Revert does not state a verification status"})
    elif not genuine:
        flags.append({"level": "error", "field": "o_genuine",
                      "msg": f"Revert status is '{status}'" + ("" if re.search(r"(?i)genuine|fake|forged", status)
                                                                else " — it does not state that the document is genuine")})

    title_src = rv_src if use_rv_degree or not ce.get("degree_title") else ce_src
    level_src = rv_src if use_rv_degree or not ce.get("degree_level") else ce_src
    table_rev = facts.get("revert", {}).get("method", "").startswith("table")
    verified_date = (dd_mm_yyyy(rv.get("verified_date")) if table_rev else "") or dd_mm_yyyy(rmail.get("date", ""))
    verified_src = rv_src if table_rev and rv.get("verified_date") else "Date of the university's reply e-mail"
    india = "india" in (rv.get("institution", "") + rv.get("university", "") + mo.get("country_name", "") +
                        mo.get("country_code", "")).lower() or bool(acc.get("ugc") or acc.get("aicte_university"))
    country, country_name = ("India", "Republic of India") if india else ("", "")
    duration = DURATION_BY_DEGREE.get(dshort) or DURATION_BY_DEGREE.get("DIPLOMA" if level == "Diploma" else "", 0)
    pursuit = "Engineering Qualification" if acc.get("technical") or re.search(r"(?i)engineering|technology", title_doc + major) \
        else ("Management Qualification" if re.search(r"(?i)management|business", title_doc) else "Academic Qualification")
    inst_type = "University Only" if univ else ("Institute Only" if college else "")
    mode_text = rv.get("branch", "") + " " + rv.get("mode_of_study", "")
    full_time = re.search(r"(?i)full[\s-]*time|\bregular\b", mode_text)
    study_mode = "Full Time - On Campus" if full_time else (
        "Part Time" if re.search(r"(?i)part[\s-]*time", mode_text) else
        "Distance / Online" if re.search(r"(?i)distance|online|correspondence|open", mode_text) else "")
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
    put("q_applicant_name", doc_name, ce_src if ce.get("candidate_name") else rv_src, name_note,
        "review" if "candidate_name" in ce_low else "")
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
    put("n_doc_name", doc_name, ce_src, name_note)
    match, note = name_match(doc_name, case.get("passport_name") or mo.get("applicant_full_name", ""))
    put("n_match", match, "Engine: degree name vs passport name", note,
        "" if match.startswith("Yes") else "review")
    put("n_enrollment", regno, rv_src if rv.get("registration_no") else ce_src,
        "matches degree Reg.No." if regno_rev and regno_rev == regno_doc else "")
    put("n_audit", DEFAULTS["n_audit"], "Default")

    # ---------- Certification verification details ----------
    put("v_institute", univ, univ_src)
    put("v_country_name", country_name, univ_src)
    put("v_cert_title", title_doc.upper() if title_doc else rv.get("branch", "").upper(), title_src)
    put("v_start", "Not Disclosed", "Revert does not state a start date",
        f"transcript: first exams {ce.get('earliest_exam_month_year')}" + (f", {transfer_note}" if lateral else "")
        if ce.get("earliest_exam_month_year") else "")
    end = mm_yyyy(rv.get("year_of_passing")) or mm_yyyy(ce.get("last_appearance")) or mm_yyyy(ce.get("exam_month_year"))
    put("v_end", end, rv_src if rv.get("year_of_passing") else ce_src)
    put("v_pursuit", pursuit, "Rule: programme type")
    put("v_mode", study_mode, rv_src, rv.get("mode_of_study") or rv.get("branch", ""))
    put("v_mode_status", "Mentioned in Verified response" if study_mode else "", rv_src)
    put("v_branch", DEFAULTS["v_branch"] if country else "", "Ops convention (precedent case)")
    put("v_exam_location", DEFAULTS["v_exam_location"] if country else "", "Ops convention (precedent case)")
    put("v_country_study", country_name, univ_src)
    put("v_award", year, rv_src if rv.get("year_of_passing") else ce_src,
        f"degree issued {ce.get('issue_date')}" if ce.get("issue_date") else "")
    put("v_subjects", subj, ce_src, f"major on degree: {major}" if subj == "Others" else "")
    put("v_country", country, univ_src)
    put("v_inst_type", inst_type, "Rule: university named on documents")
    put("v_applicant_name", doc_name, ce_src)

    # ---------- Academic programme ----------
    put("v_nqf", NQF.get(level, ""), "Rule: study level")
    put("v_compat", level if level in ("Diploma", "Bachelor", "Master", "Doctorate") else "", "Rule: study level")
    put("v_duration", F.get("q_duration", {}).get("value", ""), F.get("q_duration", {}).get("source", ""), transfer_note)
    put("v_arab", F.get("q_arab", {}).get("value", ""), "Rule: institution outside the Arab region")
    put("v_transfer", "Regular Student (Not Transfer Student)", "Transcript (single institution)", transfer_note)
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
    put("v_response_type", "Full response received" if rv and status and len(rv) >= 5 else
        ("Partial response received" if rv else ""), rv_src)
    put("v_source", DEFAULTS["v_source"] if rmail else "", "Revert received by e-mail")
    put("v_university", univ, univ_src)
    put("v_college", college, rv_src if rv.get("institution") else ce_src)
    put("v_study_level", level, level_src)
    sender = rmail.get("from_email", "")
    dom = registrable_domain(domain_of(sender)) if sender else ""
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
    put("v_ia_lang", "English" if rv else "", "Revert language")
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
    put("o_payment", "Yes" if paid else DEFAULTS["o_payment"], "Revert e-mail text",
        "mail mentions a fee/payment" if paid else "", "review" if paid else "")
    put("o_son_of", "Yes" if ce.get("son_of_mentioned", "").lower() == "yes" else "No", ce_src)
    put("o_transfer_credit", "Not Applicable - Not transfer student", "Not a transfer student")

    # ---------- remarks ----------
    bits = []
    if rv:
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
                    + (f"; UGC {acc['ugc']['type']} {acc['ugc']['status']}" if acc.get("ugc") else "") + ".")
    if lateral:
        bits.append("Note: lateral entry (transcript from Sem 03).")
    remarks = " ".join(bits)
    put("o_remarks", remarks, "Engine summary")
    return F, flags, remarks
