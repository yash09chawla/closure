"""University revert parsing — 100 % local, nothing is sent to any API.

Real reverts come in three shapes (all seen in Cases/):
  1. form/table reports      label → value ("Status  Genuine", "Year of Passing  November-2024")   [Anna Univ.]
  2. letters with a table    "1 Name SHAYSHAD.A.V / 2 Register Number … / … is GENUINE"            [PRIST]
  3. prose letters / mails   "X, PRN-110…, … has completed Master of Business Administration
                              (Telecom Management), a regular degree programme in April 2013 …"   [Symbiosis]
plus online result pages (grade-card screenshots) that list the record without a genuineness statement.

Strategy: layout label/value extraction on positioned lines (OCR or PDF text layer) → prose patterns over the
flattened text → merge (table values win). Status is only "Genuine" / "Not Genuine" when the revert says so;
otherwise it stays empty and the mapper flags it for the reviewer.
"""
import re

from . import layout

LABELS = {
    "APP NO": "app_no", "APPLICATION NO": "app_no", "APPLICATION NUMBER": "app_no", "REF NO & APPLIED DATE": "ref_no",
    "STATUS": "status", "VERIFICATION STATUS": "status", "RESULT": "result", "REMARKS": "remarks",
    "VERIFIED DATE": "verified_date", "DATE OF VERIFICATION": "verified_date",
    "REGISTRATION NUMBER": "registration_no", "REGISTRATION NO": "registration_no", "REGISTER NUMBER": "registration_no",
    "REGISTER NO": "registration_no", "REG NO": "registration_no", "ENROLLMENT NO": "registration_no",
    "ENROLMENT NO": "registration_no", "ENROLLMENT NUMBER": "registration_no", "ENROLMENT NUMBER": "registration_no",
    "ROLL NO": "registration_no", "ROLL NUMBER": "registration_no", "PRN": "registration_no", "PRN NO": "registration_no",
    "SEAT NO": "registration_no", "USN": "registration_no", "UNIVERSITY SEAT NUMBER": "registration_no",
    "NAME": "name", "NAME OF THE CANDIDATE": "name", "NAME OF CANDIDATE": "name", "CANDIDATE NAME": "name",
    "STUDENT NAME": "name", "NAME OF THE STUDENT": "name",
    "BRANCH": "branch", "PROGRAMME": "branch", "PROGRAM": "branch", "SPECIALIZATION": "branch",
    "SPECIALISATION": "branch", "PROGRAMME CODE": "programme_code",
    "DEGREE": "degree", "DEGREE QUALIFIED": "degree", "DEGREE AWARDED": "degree", "NAME OF THE DEGREE": "degree",
    "QUALIFICATION": "degree", "COURSE NAME": "degree",
    "INSTITUTION": "institution", "COLLEGE": "institution", "NAME OF THE COLLEGE": "institution",
    "NAME OF THE INSTITUTION": "institution", "COLLEGE NAME": "institution", "STUDY CENTRE": "institution",
    "CLASS": "class", "CLASSIFICATION": "class", "CLASS OBTAINED": "class", "DIVISION": "class",
    "CGPA": "cgpa", "CGPA OBTAINED": "cgpa", "PERCENTAGE": "cgpa", "OGPA": "cgpa",
    "YEAR OF PASSING": "year_of_passing", "MONTH & YEAR OF PASSING": "year_of_passing",
    "MONTH AND YEAR OF PASSING": "year_of_passing", "PASSING YEAR": "year_of_passing", "YEAR OF COMPLETION": "year_of_passing",
    "UNIVERSITY": "university", "MODE OF COLLEGE": "mode_of_college", "MODE OF STUDY": "mode_of_study",
    "MODE": "mode_of_study", "VERIFIER DETAILS": "verifier", "DATE OF BIRTH": "dob",
    # stop-labels
    "SCAN & VERIFY": "_", "NOTE": "_", "DISCLAIMER": "_", "SL NO": "_", "S NO": "_",
}
MULTILINE = {"branch", "degree", "institution", "university", "verifier", "remarks"}
JOIN_ROW = {"name"}
VALID = {"registration_no": r"\d{3,}", "year_of_passing": r"(19|20)\d{2}", "verified_date": r"\d",
         "university": r"(?i)^(?!(completed|status|grade|result|the\s+people)\b).*(universit|institut|vidyap|academy|college)",
         "branch": r"(?i)^(?!.*\b(asgn|term\s+end|credits?|grade\s+point)\b)",
         "name": r"^[A-Za-z][A-Za-z .']{2,}$", "cgpa": r"\d"}
STOP = re.compile(r"(?i)^(note\s*:|scan & verify|disclaimer)")

MONTH = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|" \
        r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
NEGATIVE = re.compile(r"(?i)\bnot\s+genuine\b|\bfake\b|\bforged\b|\bfabricated\b|\bno\s+such\s+(?:student|candidate|record)|"
                      r"\bnot\s+(?:found|available)\s+in\s+(?:our|the)\s+records?|\bnot\s+(?:a\s+)?bona\s*fide\b|"
                      r"\bdoes\s+not\s+(?:belong|pertain)|\bnot\s+issued\s+by\b|\bnot\s+been\s+issued\b")
POSITIVE = re.compile(r"(?i)\bgenuine\b|\bfound\s+(?:to\s+be\s+)?correct\b|\bverified\s+and\s+found\b|"
                      r"\bis\s+(?:a\s+)?bona\s*fide\b|\bhas\s+(?:successfully\s+)?completed\b|\bqualified\s+for\s+the\s+degree\b|"
                      r"\bauthentic\b|\bas\s+per\s+(?:our|the)\s+(?:office\s+)?records\b")


def _clean(v: str) -> str:
    return re.sub(r"\s+", " ", v or "").strip(" :-–|,")


def parse_report_text(text: str) -> dict:
    """Plain-text label/value parser (one label per line, value on the same or next lines). Used for mail bodies
    and text-layer documents without usable positions."""
    L = layout.LabelSet(LABELS)
    out, cur, title = {}, None, []
    for raw in text.replace("\r", "").split("\n"):
        cells = [c.strip() for c in raw.split("\t") if c.strip()]
        if not cells:
            continue
        if STOP.match(cells[0]):
            cur = None
            continue
        if re.fullmatch(r"\d{1,2}[.)]?", cells[0]) and len(cells) > 1:   # numbered table: "2  Register Number  …"
            cells = cells[1:]
        key = L.exact(cells[0], fuzzy=False)
        if key:
            cur = key
            out.setdefault(cur, "")
            rest = " ".join(cells[1:])
            if rest:
                out[cur] = _clean(out[cur] + " " + rest)
            continue
        hit = L.inline(cells[0])
        if hit:
            cur = hit[0]
            out[cur] = _clean(out.get(cur, "") + " " + hit[1] + " " + " ".join(cells[1:]))
            continue
        line = " ".join(cells)
        if cur and cur in MULTILINE and len(line) <= 80:   # wrapped value (e.g. "(Full Time)" under the branch)
            out[cur] = _clean(out[cur] + " " + line)
        elif cur:
            cur = None                                     # prose after the table is not part of a value
        elif not out:
            title.append(" ".join(cells))
    out = {k: v for k, v in out.items() if v and not k.startswith("_")
           and (k not in VALID or re.search(VALID[k], v))}
    out["_title"] = " ".join(title[:4])
    return out


def _find_name(flat: str, hints: list[str]) -> str:
    """Locate the candidate's name in the revert text using names we already know (passport / initiation /
    degree). All name tokens (initials may be single letters) must occur close together, in any order
    ("PATEL ALPESHBHAI GHANSHYAMBHAI" = "Alpeshbhai Ghanshyambhai Patel"). Returns the span as printed."""
    for h in hints:
        toks = [t for t in re.split(r"[\s.]+", h or "") if len(t) >= 2]
        if not toks:
            continue
        spans = []
        for t in toks:
            hits = [m.span() for m in re.finditer(rf"(?<![A-Za-z]){re.escape(t)}(?![A-Za-z])", flat, re.I)]
            if not hits:
                break
            spans.append(hits)
        else:
            # choose, for the first token, the occurrence that gives the tightest window over all tokens
            best = None
            for s0 in spans[0]:
                pts = [s0] + [min(hs, key=lambda s: abs(s[0] - s0[0])) for hs in spans[1:]]
                lo, hi = min(p[0] for p in pts), max(p[1] for p in pts)
                if hi - lo <= sum(len(t) for t in toks) + 6 * len(toks) and (best is None or hi - lo < best[1] - best[0]):
                    best = (lo, hi)
            if best:
                return flat[best[0]:best[1]].strip(" ,.:")
    return ""


# capitalised words only (case-sensitive on purpose: "constituent of X University" must not match from "constituent")
UNI_LINE = re.compile(r"^\s*((?:[A-Z][A-Za-z.&']*\s+){1,6}\(?(?:(?:Deemed|DEEMED)\s+(?:(?:to|TO)\s+(?:be|BE)\s+)?)?"
                      r"(?:University|UNIVERSITY)\)?)(?:\s*[,.(-].*)?$")


def university_from_lines(text: str) -> str:
    """First stand-alone line naming a university (letterhead), e.g. 'INDIRA GANDHI NATIONAL OPEN UNIVERSITY'."""
    for cell in re.split(r"[\n\t]", text or ""):
        # drop status words OCR glued in front ("COMPLETED Indira Gandhi National Open University")
        cell = re.sub(r"^\s*(?:(?:COMPLETED|PASSED|FAILED|RESULT|STATUS|GENUINE)\b[\s:|-]*)+", "", cell)
        m = UNI_LINE.match(cell)
        if m and not re.match(r"(?i)\s*(deemed|this|the\s+said|under|grade|status)\b", m.group(1)):
            return _clean(m.group(1))
    return ""


def parse_prose(text: str, name_hints: list[str]) -> dict:
    f = {}
    flat = layout.flat(text)
    if NEGATIVE.search(flat):
        f["status"] = "Not Genuine"
    elif POSITIVE.search(flat):
        f["status"] = "Genuine"
    m = re.search(r"(?i)\b(?:PRN|Reg(?:istration|ister|n)?\.?\s*(?:No|Number)|Enrol+ment\s*(?:No|Number)|Roll\s*(?:No|Number)|"
                  r"Seat\s*(?:No|Number)|USN)\b\.?\s*[-:–]?\s*([A-Z0-9][A-Z0-9/\-]{4,})", flat)
    if m:
        f["registration_no"] = m.group(1).strip("-/")
    m = re.search(r"(?i)(?:completed|qualified\s+for|awarded|conferred\s+(?:with|the\s+degree\s+of)?|passed)\s+(?:the\s+)?"
                  r"(?:degree\s+of\s+)?((?:Bachelor|Master|Doctor|Diploma|Post\s*Graduate\s+Diploma)\s+(?:of|in)\s+"
                  r"[A-Za-z&.]+(?:\s+(?:[A-Za-z&.]+|\([^)]{2,60}\))){0,8}?)\s*(?=,|\.\s|\s+(?:a|an|the|in|during|with|from|held)\b)",
                  flat)
    if m:
        f["degree"] = _clean(m.group(1))
    m = re.search(rf"(?i)(?:programme|degree|course|examination|exam)s?\b[^.]{{0,60}}?\b(?:in|during|of|held\s+in)\s+"
                  rf"({MONTH}\s*[-,]?\s*(?:19|20)\d{{2}})", flat) or \
        re.search(rf"(?i)(?:passed|completed)[^.]{{0,160}}?\b(?:in|during)\s+({MONTH}\s*[-,]?\s*(?:19|20)\d{{2}})", flat)
    if m:
        f["year_of_passing"] = _clean(m.group(1))
    m = re.search(r"(?i)\bCGPA\s*(?:of\s*)?([0-9]+(?:\.[0-9]+)?)(?:\s*out\s+of\s*([0-9]+(?:\.[0-9]+)?))?", flat)
    if m:
        f["cgpa"] = m.group(1) + (f" / {m.group(2)}" if m.group(2) else "")
    m = re.search(r"(?i)\b(first|second|third|pass)\s*class(?:\s+with\s+(distinction|honou?rs))?", flat)
    if m:
        f["class"] = m.group(1).title() + " Class" + (f" with {m.group(2).title()}" if m.group(2) else "")
    # mode needs context: "Online Verification" / "regular expression" must not become a study mode
    m = re.search(r"(?i)\b(full[\s-]*time|part[\s-]*time)\b", flat) or \
        re.search(r"(?i)\b(regular)\s+(?:degree\s+)?(?:programme|program|course|mode|student|basis)\b", flat) or \
        re.search(r"(?i)\b(distance|online|correspondence|open)\s+(?:and\s+distance\s+)?(?:mode|education|learning|"
                  r"programme|program|course)\b", flat)
    if m:
        f["mode_of_study"] = m.group(1).title()
    # "… is a bonafide student of <college>, a constituent of …" — only with that explicit construction
    m = re.search(r"\b(?:bona\s*fide\s+)?student\s+of\s+([A-Z][A-Za-z&.' ]{4,90}?(?:,\s*[A-Z][a-z]+)?)"
                  r",\s*(?:a\s+constituent|affiliated|an\s+affiliated)", flat, re.I)
    if m:
        f["institution"] = _clean(m.group(1))
    uni = university_from_lines(text)
    if not uni:
        m = re.search(r"\b((?:[A-Z][A-Za-z.&]+\s+){1,5}\((?:Deemed\s+(?:to\s+be\s+)?University)\))", flat)
        uni = _clean(m.group(1)) if m else ""
    if uni:
        f["university"] = uni
    name = _find_name(flat, name_hints)
    if name:
        f["name"] = name
    return f


def parse_revert(mail: dict | None, report_docs: list[dict], name_hints: list[str] | None = None) -> dict:
    """Returns {'fields':{...}, 'method': 'table'|'table-ocr'|'letter'|'none', 'source': doc name, 'meta':{}}"""
    name_hints = [h for h in (name_hints or []) if h]
    best = None
    for d in sorted(report_docs, key=lambda d: not d.get("text_layer")):
        tab = layout.values(layout.kv(d.get("lines") or [], LABELS, MULTILINE, VALID, JOIN_ROW)) if d.get("lines") else {}
        if len(tab) < 3:
            tab = {k: v for k, v in parse_report_text(d["text"]).items() if not k.startswith("_")}
        prose = parse_prose(d["text"], name_hints)
        core = [k for k in ("status", "name", "registration_no", "branch", "degree", "year_of_passing", "university")
                if k in tab]
        merged = {**prose, **tab}
        if prose.get("name") and tab.get("name") and len(prose["name"]) > len(tab["name"]) and \
                all(t.lower() in prose["name"].lower() for t in re.findall(r"[A-Za-z]{2,}", tab["name"])):
            merged["name"] = prose["name"]   # table cell held only part of the name (split over cells/lines)
        if "status" in tab and not re.search(r"(?i)genuine|verified|correct|fake|forged", tab["status"]):
            merged["status"] = prose.get("status", tab["status"])   # e.g. "COMPLETED" on a result page
        method = ("table" if d.get("text_layer") else "table-ocr") if len(core) >= 4 else "letter"
        title = parse_report_text(d["text"]).get("_title", "")
        score = len(core) * 2 + len(prose)
        if best is None or score > best[0]:
            best = (score, {"fields": merged, "method": method, "source": d["name"], "meta": {"title": title}})
    if mail:
        body = mail.get("body_text") or ""
        tab = {k: v for k, v in parse_report_text(body).items() if not k.startswith("_")}
        prose = parse_prose(body, name_hints)
        if prose.get("status") or tab:
            score = len(tab) * 2 + len(prose)
            if best is None or score > best[0]:
                best = (score, {"fields": {**prose, **tab}, "method": "letter", "source": "revert mail body", "meta": {}})
            elif best:
                for k, v in {**prose, **tab}.items():   # fill gaps from the mail body
                    best[1]["fields"].setdefault(k, v)
    if not best:
        return {"fields": {}, "method": "none", "source": "", "meta": {}}
    res = best[1]
    f = {k: _clean(v) for k, v in res["fields"].items() if v}
    f["_title"] = res["meta"].get("title", "")
    if f.get("result") and not f.get("status") and re.search(r"(?i)pass", f["result"]):
        f["status"] = "Genuine" if re.search(r"(?i)genuine", f["result"]) else ""
    res["fields"] = {k: v for k, v in f.items() if v or k == "_title"}
    return res


def respondent_from_mail(mail: dict) -> dict:
    """Respondent name/designation from signature or display name (deterministic)."""
    name, desig = "", ""
    body = mail.get("body_text") or ""
    sig = re.search(r"(?is)(regards|sincerely|thanking you|yours faithfully)[,.\s]*\n+(.{2,200})", body)
    if sig:
        lines = [l.strip(" ,") for l in sig.group(2).split("\n") if l.strip()][:3]
        if lines and len(lines[0]) < 60 and not re.search(r"disclaimer|confidential", lines[0], re.I):
            name = lines[0]
            if len(lines) > 1 and len(lines[1]) < 60:
                desig = lines[1]
    disp = mail.get("from_name") or ""
    if not name and disp:
        first = re.split(r"\s+-\s+|\s+\|\s+", disp)[0].strip()
        name = first
        if re.search(r"(?i)controller|registrar|dean|director|principal|officer|head|secretary|examination", first):
            desig = first
    return {"name": name, "designation": desig, "email": mail.get("from_email", "")}
