"""Degree + transcript extraction — rules over OCR lines (app/ocr.py: OpenAI vision transcription; PDF text layers
are read directly). No model is asked to interpret the fields: values come from patterns in the transcribed text.

Degree certificates are prose ("… hereby makes known that X has been admitted to the Degree of …"), so they
are read with sentence patterns. Transcripts/marksheets are forms, so they are read with label → value layout
rules (`layout.kv`). Every field keeps the OCR confidence of the lines it came from; low-confidence fields are
reported so the mapper can flag them for review instead of trusting them silently.
"""
import re
import time

from . import layout

FIELDS = ["candidate_name", "degree_title", "degree_level", "degree_short", "major", "faculty", "university",
          "college", "register_no", "class_awarded", "exam_month_year", "issue_date", "cgpa",
          "medium_of_instruction", "date_of_birth", "regulation", "first_semester", "last_semester",
          "earliest_exam_month_year", "last_appearance", "son_of_mentioned", "document_language", "seat_no", "notes"]
LOW_CONFIDENCE = 0.85

MONTH = r"(?:JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?|MAY|JUNE?|JULY?|AUG(?:UST)?|SEP(?:T(?:EMBER)?)?|" \
        r"OCT(?:OBER)?|NOV(?:EMBER)?|DEC(?:EMBER)?)"
MONTH_YEAR = rf"\b{MONTH}\b\.?\s*[-/,']?\s*(?:19|20)\d{{2}}\b"
MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV",
                                      "DEC"], 1)}

# OCR confusions seen on real certificates (decorative / Gothic fonts): u↔v, b↔v, tu↔w
OCR_FIXES = [(r"(?i)\bUni[uv]ersity\b", "University"), (r"(?i)\bUnibersity\b", "University"),
             (r"(?i)\bknoun\b", "known"), (r"(?i)\bhabing\b", "having"), (r"(?i)\breceibe\b", "receive"),
             (r"(?i)\btuith\b", "with"), (r"(?i)\bGiben\b", "Given"), (r"(?i)\b(f|b)as been\b", "has been"),
             (r"(?i)\bbeemn\b", "been"), (r"(?i)\bExecutibe\b", "Executive"), (r"(?i)\bAcademie\b", "Academic")]

SHORT_RE = re.compile(r"^\s*(B\.?\s?E|B\.?\s?TECH|M\.?\s?E|M\.?\s?TECH|B\.?\s?SC|M\.?\s?SC|B\.?\s?COM|M\.?\s?COM|BBA|MBA|"
                      r"MCA|BCA|B\.?\s?A|M\.?\s?A|B\.?\s?ARCH|M\.?\s?ARCH|B\.?\s?PHARM|M\.?\s?PHARM|PH\.?\s?D|"
                      r"DIPLOMA)\b\.?\s*[-–(]?\s*(.*)$", re.I)
SHORT_CANON = {"BE": "B.E.", "BTECH": "B.Tech", "ME": "M.E.", "MTECH": "M.Tech", "BSC": "B.Sc", "MSC": "M.Sc",
               "BCOM": "B.Com", "MCOM": "M.Com", "BBA": "BBA", "MBA": "MBA", "MCA": "MCA", "BCA": "BCA", "BA": "B.A.",
               "MA": "M.A.", "BARCH": "B.Arch", "MARCH": "M.Arch", "BPHARM": "B.Pharm", "MPHARM": "M.Pharm",
               "PHD": "Ph.D", "DIPLOMA": "Diploma"}
LONG_FORM = {"BE": ("Bachelor", "Bachelor of Engineering"), "BTECH": ("Bachelor", "Bachelor of Technology"),
             "ME": ("Master", "Master of Engineering"), "MTECH": ("Master", "Master of Technology"),
             "BSC": ("Bachelor", "Bachelor of Science"), "MSC": ("Master", "Master of Science"),
             "BCOM": ("Bachelor", "Bachelor of Commerce"), "MCOM": ("Master", "Master of Commerce"),
             "BBA": ("Bachelor", "Bachelor of Business Administration"),
             "MBA": ("Master", "Master of Business Administration"),
             "BCA": ("Bachelor", "Bachelor of Computer Applications"),
             "MCA": ("Master", "Master of Computer Applications"), "BA": ("Bachelor", "Bachelor of Arts"),
             "MA": ("Master", "Master of Arts"), "BARCH": ("Bachelor", "Bachelor of Architecture"),
             "BPHARM": ("Bachelor", "Bachelor of Pharmacy"), "PHD": ("Doctorate", "Doctor of Philosophy"),
             "DIPLOMA": ("Diploma", "Diploma")}

TRANSCRIPT_LABELS = {
    "NAME OF THE CANDIDATE": "candidate_name", "NAME OF CANDIDATE": "candidate_name", "CANDIDATE NAME": "candidate_name",
    "NAME OF THE STUDENT": "candidate_name", "STUDENT NAME": "candidate_name", "STUDENT S NAME": "candidate_name",
    "NAME": "candidate_name",
    "REGISTER NO": "register_no", "REGISTER NUMBER": "register_no", "REG NO": "register_no",
    "REGISTRATION NO": "register_no", "REGISTRATION NUMBER": "register_no", "ROLL NO": "register_no",
    "ROLL NUMBER": "register_no", "ENROLLMENT NO": "register_no", "ENROLMENT NO": "register_no",
    "ENROLLMENT NUMBER": "register_no", "ENROLMENT NUMBER": "register_no", "PRN": "register_no", "PRN NO": "register_no",
    "SEAT NO": "seat_no", "SEAT NUMBER": "seat_no", "UNIVERSITY SEAT NUMBER": "register_no", "USN": "register_no",
    "REGULATIONS": "regulation", "REGULATION": "regulation", "SCHEME": "regulation",
    "COLLEGE OF STUDY": "college", "NAME OF THE COLLEGE": "college", "COLLEGE NAME": "college", "COLLEGE": "college",
    "NAME OF THE INSTITUTION": "college", "INSTITUTION": "college",
    "DATE OF BIRTH": "date_of_birth", "DOB": "date_of_birth",
    "PROGRAMME NAME": "programme", "NAME OF THE PROGRAMME": "programme", "PROGRAM NAME": "programme",
    "COLLEGE/INSTITUTE": "college", "INSTITUTE": "college", "NAME OF THE INSTITUTE": "college",
    "PROGRAMME & BRANCH": "programme", "PROGRAM & BRANCH": "programme", "PROGRAMME": "programme",
    "PROGRAM": "programme", "BRANCH": "programme", "BRANCH OF STUDY": "programme", "DEGREE & BRANCH": "programme",
    "MONTH & YEAR OF LAST APPEARANCE": "last_appearance", "MONTH & YEAR OF PASSING": "last_appearance",
    "MEDIUM OF INSTRUCTION": "medium_of_instruction",
    "CGPA": "cgpa", "CUMULATIVE GRADE POINT AVERAGE": "cgpa", "OGPA": "cgpa", "CPI": "cgpa",
    "CLASSIFICATION": "class_awarded", "CLASS": "class_awarded", "CLASS AWARDED": "class_awarded",
    # stop-labels: never extracted, they only end the value of the field before them on the same row
    "GENDER": "_", "SEX": "_", "SEMESTER": "_", "MONTH/YEAR OF EXAM": "_", "MONTH & YEAR OF EXAM": "_",
    "FOLIO NO": "_", "SL NO": "_", "SERIAL NO": "_", "DATE": "_", "FATHER S NAME": "_", "MOTHER S NAME": "_",
    "DATE OF ISSUE": "_", "PHOTO": "_", "GRADE SHEET": "_", "MEDIUM": "_", "CERTIFICATE NO": "_",
}
TRANSCRIPT_VALID = {"register_no": r"\d{3,}", "seat_no": r"\d{3,}", "date_of_birth": r"\d", "cgpa": r"^\s*\d{1,2}(\.\d{1,3})?\b",
                    "candidate_name": r"^[A-Za-z][A-Za-z .']{2,}$", "regulation": r"(19|20)\d{2}|R\s?\d{2}",
                    "last_appearance": r"(19|20)\d{2}", "class_awarded": r"(?i)class|distinction|pass",
                    # a programme is words, never another label / number line ("CERTIFICATE NO. : C00109811")
                    "programme": r"(?i)^(?!.*\b(?:certificate|serial|folio|date|no)\b\s*\.?\s*:)(?!.*\d{5,})[A-Za-z]"}


def _fix(text: str) -> str:
    for pat, rep in OCR_FIXES:
        text = re.sub(pat, rep, text)
    return text


def _clean_name(s: str) -> str:
    s = re.sub(r"^(?i:mr|ms|mrs|miss|shri|sri|smt|kumari|kum)\.?\s+", "", s.strip())
    s = re.sub(r"\s*\.\s*", ".", s)          # "SHAYSHAD.A. V" → "SHAYSHAD.A.V"
    s = re.sub(r"\.(?=[A-Za-z]{2})", ". ", s) if " " in s else s
    return re.sub(r"\s+", " ", s).strip(" .,")


def month_year_key(s: str) -> tuple[int, int]:
    m = re.search(rf"({MONTH})\b\.?\s*[-/,']?\s*((?:19|20)\d{{2}})", s or "", re.I)
    if not m:
        return (9999, 99)
    return int(m.group(2)), MONTHS[m.group(1)[:3].upper()]


def _title_case(s: str) -> str:
    letters = [c for c in s if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.6:
        s = s.title()
    return re.sub(r"\b(Of|In|And|The|With)\b", lambda m: m.group(1).lower(), s)


def _short_key(s: str) -> str:
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def _lines_with(lines, needle_re):
    return [l for l in lines if re.search(needle_re, l["text"], re.I)]


def read_degree(docs: list[dict]) -> tuple[dict, dict]:
    """Sentence patterns over the degree certificate. Returns (fields, confidence)."""
    f, conf = {}, {}
    lines = [l for d in docs for l in d.get("lines", [])]
    text = _fix(" ".join(d["text"] for d in docs))
    flat = layout.flat(text)

    def score_of(value):
        hit = [l for l in lines if value and value.split()[0].lower() in _fix(l["text"]).lower()]
        return min((l["score"] for l in hit), default=0.0)

    pats = [r"(?:known|certify|certified|certifies)\s+that\s+((?:Mr|Ms|Mrs|Shri|Smt|Kumari)?\.?\s*[A-Z][A-Za-z.' ]{1,60}?)"
            r"\s+(?:has|have)\s+been\s+(?:duly\s+)?(?:admitted|awarded|conferred)",
            r"\b([A-Z][A-Z.' ]{2,60}?)\s+(?:has|have)\s+been\s+(?:duly\s+)?(?:admitted|awarded|conferred)",
            r"conferred\s+(?:up)?on\s+([A-Z][A-Za-z.' ]{2,60}?)\s+(?:the|for)\b",
            r"certify\s+that\s+((?:Mr|Ms|Mrs|Shri|Smt|Kumari)?\.?\s*[A-Z][A-Za-z.' ]{2,60}?)\s*(?:\[|\(|having\b|is\b|was\b)"]
    for p in pats:
        m = re.search(p, flat)
        if m and len(re.sub(r"[^A-Za-z]", "", m.group(1))) >= 3:
            f["candidate_name"] = _clean_name(m.group(1))
            break

    m = re.search(r"degree\s+of\s+((?:bachelor|master|doctor)\s+of\s+[a-z&]+(?:\s+[a-z&]+){0,3}?)"
                  r"(?:\s*[-–]?\s*in\s+([a-z&,.() ]+?))?\s*(?:under\b|having\b|with\b|in\s+the\b|for\b|$|[.;,])",
                  flat, re.I)
    if m:
        lvl = re.sub(r"\s+", " ", m.group(1)).strip()
        maj = re.sub(r"\s+", " ", m.group(2) or "").strip(" -,.")
        f["degree_title"] = _title_case(lvl + (f" in {maj}" if maj else ""))
        if maj:
            f["major"] = _title_case(maj)
        f["degree_level"] = next((v for k, v in (("doctor", "Doctorate"), ("master", "Master"), ("bachelor", "Bachelor"))
                                  if k in lvl.lower()), "")
        for k, (lv, long) in LONG_FORM.items():
            if long.lower() == lvl.lower():
                f["degree_short"] = SHORT_CANON[k]
        conf["degree_title"] = score_of(lvl)
    else:  # title printed on its own line: "Master of Business Administration" / "(Telecom Management)"
        m = re.search(r"\b((?:Bachelor|Master|Doctor)\s+of\s+(?:[A-Z][a-z]+|and|&)(?:\s+(?:[A-Z][a-z]+|and|&)){0,4})"
                      r"(?:\s*\(([^)]{3,60})\))?", flat)
        if m:
            lvl, maj = m.group(1).strip(), (m.group(2) or "").strip()
            f["degree_title"] = lvl + (f" ({maj})" if maj else "")
            if maj:
                f["major"] = maj
            f["degree_level"] = next((v for k, v in (("Doctor", "Doctorate"), ("Master", "Master"),
                                                     ("Bachelor", "Bachelor")) if lvl.startswith(k)), "")
            for k, (lv, long) in LONG_FORM.items():
                if long.lower() == lvl.lower():
                    f["degree_short"] = SHORT_CANON[k]
            conf["degree_title"] = score_of(lvl)
    m = re.search(r"under\s+the\s+faculty\s+of\s+([A-Za-z& ]+?)(?:\s*,|\s+having|\.)", flat, re.I)
    if m:
        f["faculty"] = _title_case(m.group(1).strip())

    m = re.search(r"(FIRST|SECOND|THIRD)\s*CLASS(?:\s+WITH\s+(DISTINCTION|HONOU?RS))?", flat, re.I)
    if m:
        f["class_awarded"] = (m.group(1).title() + " Class" + (f" with {m.group(2).title()}" if m.group(2) else ""))
    elif re.search(r"\bPASS\s*CLASS\b", flat, re.I):
        f["class_awarded"] = "Pass Class"

    m = re.search(rf"examinations?\s+(?:held|conducted)\s+(?:in|during)\s+(?:the\s+month\s+of\s+)?({MONTH_YEAR})",
                  flat, re.I) or re.search(rf"examination[^.]{{0,40}}?({MONTH_YEAR})", flat, re.I)
    if m:
        f["exam_month_year"] = re.sub(r"[-/,']", " ", m.group(1)).title().replace("  ", " ")
        conf["exam_month_year"] = score_of(m.group(1))

    m = re.search(rf"day\s+of\s+({MONTH}\s*,?\s*(?:19|20)\d{{2}})", flat, re.I) or \
        re.search(rf"(?:dated?|issued\s+on)\s*[:\-]?\s*(\d{{1,2}}[-/. ]\w+[-/. ](?:19|20)\d{{2}})", flat, re.I)
    if m:
        f["issue_date"] = m.group(1).title()
    else:  # a bare "February 2026" line printed near the signatures
        bare = [l["text"] for l in lines if re.fullmatch(rf"\s*{MONTH}\s*,?\s*(?:19|20)\d{{2}}\s*", l["text"], re.I)
                and l["text"].upper() != f.get("exam_month_year", "").upper()]
        if bare:
            f["issue_date"] = bare[-1].strip().title()

    m = re.search(r"\bReg(?:istration|ister|n)?\s*\.?\s*N[o0a]\s*\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{4,})", flat, re.I)
    if m:
        f["register_no"] = m.group(1).strip("-/")
        conf["register_no"] = score_of(m.group(0).split()[0])

    m = re.search(r"\b((?:[A-Z][A-Za-z.&']+\s+){1,5}(?:University|UNIVERSITY))\b", flat)
    if m and not re.match(r"(?i)this\b", m.group(1)):
        f["university"] = re.sub(r"(?i)^(the|of)\s+", "", m.group(1)).strip()
    if not f.get("university"):
        m = re.search(r"\b((?:[A-Z][A-Z&]+\s+){1,6}INSTITUTE\s+OF\s+(?:[A-Z&]+\s*){1,4})", flat)
        if m:
            f["university"] = _title_case(m.group(1).strip())

    f["son_of_mentioned"] = "yes" if re.search(r"\b(S/o|D/o|son of|daughter of|father'?s name)\b", text, re.I) else "no"
    if "candidate_name" in f:
        conf["candidate_name"] = score_of(f["candidate_name"])
    return f, conf


def read_transcript(docs: list[dict]) -> tuple[dict, dict]:
    f, conf = {}, {}
    lines = [l for d in docs for l in d.get("lines", [])]
    if not lines:
        return f, conf
    found = layout.kv(lines, TRANSCRIPT_LABELS, multiline={"college", "programme"}, validate=TRANSCRIPT_VALID)
    for k, v in found.items():
        f[k] = v["value"]
        conf[k] = v["score"]
    if "candidate_name" in f:
        f["candidate_name"] = _clean_name(f["candidate_name"])
    for k in ("register_no", "seat_no"):
        if f.get(k):  # "21919PR.NO." → "21919" (next label glued to the value by OCR)
            f[k] = re.sub(r"(?i)(PR\.?\s?N\.?\s?O?\.?|ENROL+MENT|ROLL|REG)\W*$", "", f[k].split()[0]).strip("-/.:")
    # a seat / exam number is NOT the registration number (it changes per exam) → kept separately, never
    # cross-checked against the revert's register no. / PRN
    if f.get("seat_no"):
        conf["seat_no"] = conf.get("seat_no", 0.9)
    prog = f.pop("programme", "")
    header_short = next((l["text"] for l in lines if SHORT_RE.match(l["text"]) and len(l["text"]) <= 10), "")
    m = SHORT_RE.match(prog) or SHORT_RE.match(header_short)
    if m:
        k = _short_key(m.group(1))
        f["degree_short"] = SHORT_CANON.get(k, m.group(1))
        lvl, long = LONG_FORM.get(k, ("", ""))
        f["degree_level"] = lvl
        major = (m.group(2) if SHORT_RE.match(prog) else "").strip(" ()-")
        if major:
            f["major"] = _title_case(major)
        if SHORT_RE.match(prog):   # a bare "BE" header is not enough to state the full title
            f["degree_title"] = long + (f" in {_title_case(major)}" if long and major else "")
    elif prog:
        lvl_m = re.match(r"(?i)\s*((?:bachelor|master|doctor)\s+of\s+[a-z& ]+?)(?:\s+in\s+(.+))?$", prog)
        if lvl_m:
            f["degree_title"] = _title_case(prog)
            f["degree_level"] = next((v for k, v in (("doctor", "Doctorate"), ("master", "Master"),
                                                     ("bachelor", "Bachelor")) if lvl_m.group(1).lower().startswith(k)), "")
            for k, (lv, long) in LONG_FORM.items():
                if long.lower() == re.sub(r"\s+", " ", lvl_m.group(1)).lower():
                    f["degree_short"] = SHORT_CANON[k]
            if lvl_m.group(2):
                f["major"] = _title_case(lvl_m.group(2))
        else:
            f["major"] = _title_case(prog)

    text = " ".join(d["text"] for d in docs)
    if f.get("regulation"):
        m = re.search(r"((?:19|20)\d{2}(?:\s*\([A-Z ]+\))?|R\s?\d{2})", f["regulation"])
        f["regulation"] = m.group(1) if m else f["regulation"]
    else:
        m = re.search(r"REGULATIONS?\s*[:\-]?\s*((?:19|20)\d{2}(?:\s*\([A-Z]+\))?)", text, re.I)
        if m:
            f["regulation"] = m.group(1)

    # semesters: small numbers in the column under a "SEM" header
    sem_heads = [l for l in lines if re.fullmatch(r"\s*SEM(?:ESTER)?\.?\s*(?:NO\.?)?\s*", l["text"], re.I)]
    sems = set()
    for h in sem_heads:
        x0, x1 = h["box"][0], h["box"][2]
        w = max(10, x1 - x0)
        for l in lines:
            cx = (l["box"][0] + l["box"][2]) / 2
            if l.get("page") == h.get("page") and l["box"][1] > h["box"][3] and x0 - 0.6 * w <= cx <= x1 + 0.6 * w:
                t = l["text"].strip().upper()
                roman = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}
                if re.fullmatch(r"0?([1-9]|1[0-2])", t):
                    sems.add(int(t))
                elif t in roman:
                    sems.add(roman[t])
    if sems:
        f["first_semester"] = f"{min(sems):02d}"
        f["last_semester"] = f"{max(sems):02d}"

    # earliest month & year of passing in the grade table (birth dates excluded)
    body = text.replace(f.get("date_of_birth", "\0"), " ")
    cands = [m.group(0) for m in re.finditer(MONTH_YEAR, body, re.I)
             if not re.search(r"\d{1,2}\s*[-/. ]\s*$", body[max(0, m.start() - 4):m.start()])]
    last = f.get("last_appearance", "")
    cands = [c for c in cands if c.strip().upper() != last.strip().upper()] or cands
    if cands:
        f["earliest_exam_month_year"] = min(cands, key=month_year_key).upper()
    return f, conf


def _language(text: str) -> str:
    if re.search(r"[؀-ۿ]", text):
        return "Arabic"
    if len(re.findall(r"[ऀ-ॿ]", text)) > 20:
        return "Hindi"
    return "English"


def extract(degree_docs: list[dict], transcript_docs: list[dict]) -> dict:
    t = time.time()
    deg, deg_conf = read_degree(degree_docs) if degree_docs else ({}, {})
    tr, tr_conf = read_transcript(transcript_docs) if transcript_docs else ({}, {})
    fields = {k: "" for k in FIELDS}
    confidence, source = {}, {}
    # degree certificate wins for what it states (name, title, class, exam session); transcript fills the rest
    for k in FIELDS:
        if deg.get(k):
            fields[k], confidence[k], source[k] = deg[k], deg_conf.get(k, 0.95), "degree"
        elif tr.get(k):
            fields[k], confidence[k], source[k] = tr[k], tr_conf.get(k, 0.95), "transcript"
    if not deg.get("degree_title") and tr.get("degree_title"):
        for k in ("degree_title", "degree_level", "degree_short", "major"):
            if tr.get(k):
                fields[k], confidence[k], source[k] = tr[k], tr_conf.get(k, 0.95), "transcript"
    if not fields["degree_level"] and fields["degree_short"]:
        fields["degree_level"] = LONG_FORM.get(_short_key(fields["degree_short"]), ("", ""))[0]
    if not fields["degree_short"] and fields["degree_title"]:
        for k, (lv, long) in LONG_FORM.items():
            if fields["degree_title"].lower().startswith(long.lower()):
                fields["degree_short"] = SHORT_CANON[k]
    fields["document_language"] = _language(" ".join(d["text"] for d in degree_docs + transcript_docs))

    notes = []
    if deg.get("candidate_name") and tr.get("candidate_name") and \
            re.sub(r"[^A-Z]", "", deg["candidate_name"].upper()) != re.sub(r"[^A-Z]", "", tr["candidate_name"].upper()):
        notes.append(f"name on transcript '{tr['candidate_name']}' differs from degree '{deg['candidate_name']}'")
    if deg.get("register_no") and tr.get("register_no") and \
            re.sub(r"\D", "", deg["register_no"]) != re.sub(r"\D", "", tr["register_no"]):
        notes.append(f"register no. on transcript {tr['register_no']} vs degree {deg['register_no']}")
    if fields["first_semester"] and fields["first_semester"].lstrip("0") == "3":
        notes.append("transcript starts at semester 03 (lateral entry?)")
    low = sorted(k for k, c in confidence.items() if c and c < LOW_CONFIDENCE)
    if degree_docs and not deg.get("degree_title"):
        notes.append("degree title not readable on the certificate (decorative font?) — taken from transcript/revert")
    fields["notes"] = "; ".join(notes)
    name_candidates = [n for n in (deg.get("candidate_name"), tr.get("candidate_name")) if n]
    return {"fields": fields, "confidence": confidence, "source": source, "low_confidence": low,
            "name_candidates": name_candidates,
            "method": "openai-ocr", "meta": {"seconds": round(time.time() - t, 2), "engine": "OpenAI vision OCR + rules"}}
