"""University revert parsing.

1. Deterministic label/value parser for tabular verification reports (text-layer PDFs) — free, exact.
2. LLM fallback for free-text replies (e.g. "We confirm Mr X passed B.Tech in 2019…").
"""
import re

from .. import config, llm

LABELS = {
    "app no": "app_no", "application no": "app_no", "ref no & applied date": "ref_no", "status": "status",
    "verified date": "verified_date", "registration number": "registration_no", "register number": "registration_no",
    "register no": "registration_no", "enrollment no": "registration_no", "roll no": "registration_no",
    "name": "name", "name of the candidate": "name", "branch": "branch", "course": "branch", "programme": "branch",
    "degree": "degree", "institution": "institution", "college": "institution", "class": "class",
    "classification": "class", "cgpa": "cgpa", "year of passing": "year_of_passing", "month & year of passing":
        "year_of_passing", "university": "university", "mode of college": "mode_of_college",
    "verifier details": "verifier", "date of birth": "dob", "result": "result",
}
STOP = re.compile(r"(?i)^(note\s*:|scan & verify|disclaimer)")


def parse_report_text(text: str) -> dict:
    lines = [l.strip() for l in text.replace("\r", "").split("\n")]
    out, cur, title = {}, None, []
    for l in lines:
        if not l:
            continue
        if STOP.match(l):
            cur = None
            continue
        key = LABELS.get(re.sub(r"\s+", " ", l.lower().rstrip(":")))
        if key:
            cur = key
            out.setdefault(cur, "")
            continue
        if cur:
            out[cur] = (out[cur] + " " + l).strip()
        elif len(out) == 0:
            title.append(l)
    out = {k: re.sub(r"\s+", " ", v).strip() for k, v in out.items() if v}
    out["_title"] = " ".join(title[:4])
    return out


REVERT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {k: {"type": "string"} for k in [
        "status", "name", "registration_no", "degree", "branch", "institution", "university", "class",
        "year_of_passing", "verified_date", "mode_of_study", "respondent_name", "respondent_designation",
        "payment_mentioned", "remarks"]},
    "required": ["status", "name", "registration_no", "degree", "branch", "institution", "university", "class",
                 "year_of_passing", "verified_date", "mode_of_study", "respondent_name", "respondent_designation",
                 "payment_mentioned", "remarks"],
}


def parse_revert(mail: dict | None, report_docs: list[dict]) -> dict:
    """Returns {'fields':{...}, 'method': 'table'|'llm'|'none', 'source': doc name, 'meta':{}}"""
    for d in sorted(report_docs, key=lambda d: not d.get("text_layer")):
        f = parse_report_text(d["text"])
        core = [k for k in ("status", "name", "registration_no", "branch", "year_of_passing", "university") if k in f]
        if len(core) >= 4:
            return {"fields": f, "method": "table" if d.get("text_layer") else "table-ocr", "source": d["name"],
                    "meta": {}}
    corpus = ""
    if mail:
        corpus += f"EMAIL FROM: {mail['from_name']} <{mail['from_email']}>\nSUBJECT: {mail['subject']}\n" \
                  f"DATE: {mail['date']}\nBODY:\n{mail['body_text'][:6000]}\n"
    for d in report_docs:
        corpus += f"\nATTACHMENT {d['name']}:\n{d['text'][:6000]}\n"
    if not corpus.strip() or not llm.available() or not config.CANDIDATE_LLM:
        return {"fields": {}, "method": "none", "source": "", "meta": {}}
    data, meta = llm.extract_json(
        "You read a university's reply to a background-verification request. Extract ONLY what is explicitly "
        "stated; use empty string when absent. status = Genuine / Not Genuine / Unclear. respondent_* = the person "
        "who signed the reply. payment_mentioned = yes/no. year_of_passing = month and year exactly as stated "
        "(e.g. 'May 2019'). verified_date = only a date the institution explicitly gives for its verification "
        "(NOT the date of our request).\n\n" + corpus, schema=REVERT_SCHEMA)
    data = {k: v for k, v in data.items() if v}
    return {"fields": data, "method": "llm", "source": "revert mail", "meta": meta}


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
