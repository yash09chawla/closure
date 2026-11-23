"""Degree + transcript extraction. One vision call for both documents (Tesseract text as hint);
regex fallback on Tesseract text when no API key."""
import re

from .. import llm

FIELDS = ["candidate_name", "degree_title", "degree_level", "degree_short", "major", "faculty", "university",
          "college", "register_no", "class_awarded", "exam_month_year", "issue_date", "cgpa",
          "medium_of_instruction", "date_of_birth", "regulation", "first_semester", "last_semester",
          "earliest_exam_month_year", "last_appearance", "son_of_mentioned", "document_language", "notes"]
SCHEMA = {"type": "object", "additionalProperties": False,
          "properties": {k: {"type": "string"} for k in FIELDS}, "required": FIELDS}

PROMPT = """You are reading an Indian (or other) education DEGREE certificate and its TRANSCRIPT / marksheet.
Copy values exactly as printed. Never guess — use "" when a value is not visible.
- candidate_name: as printed on the degree (fallback transcript)
- degree_title: full title as printed, e.g. "Bachelor of Engineering in Civil Engineering"
- degree_level: one of Diploma | Bachelor | Master | Doctorate | Other
- degree_short: abbreviation e.g. B.E., B.Tech, M.Sc, MBA
- major: specialisation/branch e.g. "Civil Engineering"
- university: awarding university/board; college: college/institution name on transcript
- register_no: registration/register/enrolment number (as printed, keep suffixes)
- class_awarded: e.g. First Class, First Class with Distinction
- exam_month_year: examination month & year on the degree e.g. "November 2024"
- issue_date: date/month the degree was issued
- cgpa: cumulative GPA/percentage on transcript
- regulation: regulation/scheme on transcript e.g. "2017 (CBCS)"
- first_semester / last_semester: lowest and highest semester numbers listed on the transcript (digits only)
- earliest_exam_month_year: earliest "month & year of passing" in the transcript table
- last_appearance: the printed "month & year of last appearance" (header field) if present
- son_of_mentioned: "yes" if S/o, D/o, son of, daughter of, or father's name appears on the degree, else "no"
- document_language: language the documents are printed in
- notes: anything a verifier should notice (lateral entry, name differences, missing semesters), short
"""


def extract(degree_docs: list[dict], transcript_docs: list[dict]) -> dict:
    hint = ""
    for label, ds in (("DEGREE", degree_docs), ("TRANSCRIPT", transcript_docs)):
        for d in ds:
            hint += f"\n--- OCR of {label} ({d['name']}), may contain errors ---\n{d['text'][:2500]}\n"
    images = [p for d in degree_docs for p in d["pages"][:2]] + [p for d in transcript_docs for p in d["pages"][:2]]
    if llm.available() and images:
        data, meta = llm.extract_json(PROMPT + hint, images=images[:4], schema=SCHEMA)
        return {"fields": data, "method": "vision-llm", "meta": meta}
    return {"fields": regex_extract(degree_docs, transcript_docs), "method": "ocr-regex", "meta": {}}


def regex_extract(degree_docs, transcript_docs) -> dict:
    deg = " ".join(d["text"] for d in degree_docs)
    tr = " ".join(d["text"] for d in transcript_docs)
    flat = re.sub(r"\s+", " ", deg)
    f = {k: "" for k in FIELDS}
    m = re.search(r"([A-Z][A-Z .]{2,60}?)\s+(?:has|fas|bas)\s+been\s+(?:admitted|awarded|conferred)", flat)
    if m:
        f["candidate_name"] = m.group(1).strip()
    m = re.search(r"DEGREE OF ([A-Z ]+?)\s+in\s+([A-Z &]+?)\s+(?:under|having|with)", flat, re.I)
    if m:
        lvl, maj = m.group(1).strip(), m.group(2).strip()
        f["degree_title"] = f"{lvl.title()} in {maj.title()}".replace(" Of ", " of ")
        f["major"] = maj.title()
        f["degree_level"] = next((x for x in ("Bachelor", "Master", "Doctor") if x.lower() in lvl.lower()), "")
        if f["degree_level"] == "Doctor":
            f["degree_level"] = "Doctorate"
        if "ENGINEERING" in lvl.upper():
            f["degree_short"] = "B.E." if f["degree_level"] == "Bachelor" else "M.E."
        elif "TECHNOLOGY" in lvl.upper():
            f["degree_short"] = "B.Tech" if f["degree_level"] == "Bachelor" else "M.Tech"
    m = re.search(r"placed in ([A-Z ]+?CLASS(?: WITH [A-Z]+)?)", flat, re.I)
    if m:
        f["class_awarded"] = m.group(1).title()
    m = re.search(r"held in\s+([A-Z]+ \d{4})", flat, re.I)
    if m:
        f["exam_month_year"] = m.group(1).title()
    m = re.search(r"Reg\.?\s*No\.?\s*[:.]?\s*([A-Z0-9/]+)", flat, re.I)
    if m:
        f["register_no"] = m.group(1)
    m = re.search(r"(?:the|of)\s+([A-Z][A-Za-z ]+University)", flat)
    if m:
        f["university"] = m.group(1).strip()
    f["son_of_mentioned"] = "yes" if re.search(r"\b(S/o|D/o|son of|daughter of)\b", deg, re.I) else "no"
    f["document_language"] = "English"
    m = re.search(r"REGULATIONS?\s*[:\s]*([0-9]{4}[^\n]{0,8})", tr, re.I)
    if m:
        f["regulation"] = m.group(1).strip()
    return f
