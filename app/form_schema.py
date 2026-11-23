"""HVOPS Education closure form — labels/sections mirror HVOPS.html and HVOSP_HTML.pdf.
Option lists contain values seen in the HTML/PDF plus obvious siblings (real lists may be longer)."""

YES_NO = ["Yes", "No"]
COUNTRIES = ["India", "United Arab Emirates", "Pakistan", "Philippines", "Egypt", "United Kingdom", "Other"]
COUNTRY_NAMES = ["Republic of India", "United Arab Emirates", "Islamic Republic of Pakistan",
                 "Republic of the Philippines", "Arab Republic of Egypt", "United Kingdom"]
INST_TYPE = ["University Only", "Institute Only", "University & Institute"]
STUDY_LEVEL = ["Secondary", "Higher Secondary", "Diploma", "Bachelor", "Master", "Doctorate", "Post Graduate Diploma"]
ARAB = ["Arab University", "Other Country (If required raise insufficiency for marksheet/transcript)"]
DURATION = ["1 Year", "2 Year", "3 Year", "4 Year", "5 Year", "6 Year"]
TRANSFER = ["Regular Student (Not Transfer Student)", "Transfer Student"]
MATCH = ["Yes- Name is matching on documents", "Partially matching", "No- Name is not matching on documents"]
PURSUIT = ["Engineering Qualification", "Academic Qualification", "Medical Qualification", "Management Qualification",
           "Technical / Vocational Qualification"]
STUDY_MODE = ["Full Time - On Campus", "Part Time", "Distance / Online", "Hybrid"]
STUDY_MODE_STATUS = ["Mentioned in Verified response", "Mentioned on Document", "Not Mentioned"]
SUBJECTS = ["Electrical and Electronic Engineering", "Mechanical Engineering", "Computer Science",
            "Computer Science and Engineering", "Information Technology", "Electronics and Communication Engineering",
            "Civil Engineering", "Chemical Engineering", "Business Administration", "Commerce", "Science", "Arts",
            "Others"]
NQF = ["Level 4 – Secondary/Certificate", "Level 5 – Diploma or Equivalent", "Level 6 – Bachelor or Equivalent",
       "Level 7 – Master or Equivalent", "Level 8 – Doctorate or Equivalent"]
COMPAT = ["Diploma", "Bachelor", "Master", "Doctorate"]
COND_STATUS = ["Found in Verification Revert", "Found on University Website", "Not Found"]
RESPONSE_TYPE = ["Full response received", "Partial response received", "No response"]
EMAIL_TYPE = ["Official", "Public"]
DEGREE_TYPE = ["Academic", "Professional", "Vocational", "Honorary"]
LANG = ["English", "Arabic", "Hindi", "Other"]
ACC_STATUS = ["Accredited", "Non-Accredited"]
ACC_BODY = ["University Grants Commission", "All India Council for Technical Education", "NOT DISCLOSED"]
RESULT = ["Pass", "Fail", "Discrepancy", "Unable to Verify"]
GENUINE = ["Document Genuine", "Document Not Genuine - Forged/Manipulated", "Unable to confirm"]
TRANSFER_CREDIT = ["Not Applicable - Not transfer student", "Transfer credits verified", "Transfer credits not verified"]
YEARS = [str(y) for y in range(2026, 1979, -1)]


def F(key, label, type_="text", options=None, req=False, ro=False, col=6, nd=False):
    return {"key": key, "label": label, "type": type_, "options": options or [], "required": req,
            "readonly": ro, "col": col, "not_disclosed": nd}


SECTIONS = [
    {"id": "mohre", "title": "1. MOHRE API Details", "fields": [
        F("m_applicant_full_name", "Applicant Full Name", req=True, ro=True, col=12),
        F("m_institute_id", "Institute ID", req=True, ro=True, col=12),
        F("m_institute_details", "Institute Details", ro=True, col=12),
        F("m_institute_name", "Institute Name", ro=True, col=12),
        F("m_country_code", "Institution Country (Code)", ro=True, col=12),
        F("m_country_name", "Institution Country Name", req=True, ro=True, col=12),
        F("m_study_level", "Degree / Study Level", "select", STUDY_LEVEL, req=True, ro=True),
        F("m_cert_title", "Qualification Certificate Title", ro=True, col=12),
        F("m_study_start", "Study Start Date (MM-YYYY)", req=True, ro=True),
        F("m_study_end", "Study End Date (MM-YYYY)", req=True, ro=True),
        F("m_subject_id", "Subject/Major ID", ro=True, col=12),
        F("m_subjects", "Subjects/Major", req=True, ro=True),
    ]},
    {"id": "qual", "title": "2. Qualification Document Details (Entered by HV)", "fields": [
        F("q_country", "Country", "select", COUNTRIES, req=True, col=12),
        F("q_inst_type", "Educational Institution Type", "select", INST_TYPE, req=True, col=12),
        F("q_university", "University Name/Board Name", req=True, col=12),
        F("q_college", "College/Institute Name", col=12),
        F("q_applicant_name", "Applicant Name (As per degree/diploma document)(English)", req=True, col=12),
        F("q_year", "Year of Passing", "select", YEARS, req=True, col=12),
        F("q_cert_title", "Qualification Certificate Title at Document", req=True, col=12),
        F("q_study_level", "Study Level", "select", STUDY_LEVEL, req=True),
        F("q_arab", "Is this an Arab university?", "select", ARAB, req=True, col=12),
        F("q_duration", "Transcript Details Duration", "select", DURATION, req=True, col=12),
        F("q_transfer", "Is this transfer student?", "select", TRANSFER, col=12),
        F("q_lang", "Are the transcripts and degrees in English or Arabic?", "select", YES_NO, req=True, col=12),
    ]},
    {"id": "name", "title": "3. Name check qualification & Passport", "fields": [
        F("n_doc_name", "Applicant Name (As on document)", req=True, col=12),
        F("n_passport_name", "Full Name on Passport", req=True, ro=True, col=12),
        F("n_match", "Match Status (Passport name & Name on Certificate)", "select", MATCH, req=True, col=12),
        F("n_enrollment", "Enrollment/Registration No/Seat Number", col=12),
        F("n_audit", "Audit Case", "select", YES_NO, col=12),
    ]},
    {"id": "cvd", "title": "Certification Verification Details", "fields": [
        F("v_institute", "Institute Name", col=12),
        F("v_country_name", "Institution Country Name", "select", COUNTRY_NAMES, req=True, col=12),
        F("v_cert_title", "Qualification Certificate Title", col=12),
        F("v_start", "Study Start Date (MM-YYYY)", req=True, nd=True),
        F("v_end", "Study End Date (MM-YYYY)", req=True, nd=True),
        F("v_pursuit", "Applicant Degree Pursuit", "select", PURSUIT, req=True, col=12),
        F("v_mode", "Study Mode", "select", STUDY_MODE, req=True, col=12, nd=True),
        F("v_mode_status", "Study Mode Response Status", "select", STUDY_MODE_STATUS, req=True, col=12),
        F("v_branch", "Branch Name (If Applicable)", req=True, col=12),
        F("v_exam_location", "Examination Location", req=True, col=12),
        F("v_country_study", "Country of Study", "select", COUNTRY_NAMES, req=True, col=12),
        F("v_award", "Award Date", "select", YEARS, req=True, col=12),
        F("v_subjects", "Subjects/Major", "select", SUBJECTS, req=True),
        F("v_country", "Country", "select", COUNTRIES, req=True, col=12),
        F("v_inst_type", "Educational Institution Type", "select", INST_TYPE, req=True, col=12),
        F("v_applicant_name", "Applicant Name (As per degree/diploma document)(English)", req=True, col=12),
    ]},
    {"id": "acad", "title": "ACADEMIC PROGRAM INFORMATION", "fields": [
        F("v_nqf", "Level as per UAE NQFR(national qualification frame work) if applicable", "select", NQF, col=12),
        F("v_compat", "Combability in the country of issuance", "select", COMPAT),
        F("v_duration", "Transcript Details Duration", "select", DURATION, req=True, col=12),
        F("v_arab", "Is this an Arab university?", "select", ARAB, req=True, col=12),
        F("v_transfer", "Is this transfer student?", "select", TRANSFER, col=12),
        F("v_cond_status", "Condition for obtaining the degree status", "select", COND_STATUS, col=12),
        F("v_cond", "Condition for obtaining the degree", "textarea", col=12),
        F("v_response_type", "Response Type", "select", RESPONSE_TYPE, req=True, col=12),
        F("v_source", "Verification source", req=True, col=12),
        F("v_university", "University Name/Board Name", req=True, col=12),
        F("v_college", "College/Institute Name", col=12),
        F("v_study_level", "Study Level", "select", STUDY_LEVEL),
        F("v_email_type", "Authenticity of source Email Type (Public/Official).", "select", EMAIL_TYPE, req=True, col=12),
        F("v_domain", "Company Domain", req=True, col=12),
        F("v_degree_type", "Degree Type", "select", DEGREE_TYPE, req=True, col=12, nd=True),
        F("v_ia_lang", "IA Response Language", "select", LANG, req=True, col=12),
        F("v_degree_lang", "Degree Language", "select", LANG, req=True, col=12),
    ]},
    {"id": "acc", "title": "Accreditation Status", "fields": [
        F("a_status", "Accreditation Status (HV/ENIC)", "select", ACC_STATUS, req=True, col=12),
        F("a_country", "Accreditation Country", "select", COUNTRIES, req=True, col=12),
        F("a_url", "Accreditation URL", req=True, col=12),
        F("a_body", "Accreditation Body", "select", ACC_BODY, req=True, col=12, nd=True),
        F("a_proof", "Accreditation Body Status Proof", "file", col=12),
        F("a_year", "Accreditation Year", "select", YEARS, req=True, col=12),
    ]},
    {"id": "quality", "title": "Quality Questions", "fields": [
        F("o_remarks", "OPS Remarks", "textarea", col=12),
        F("o_result", "Result Status", "select", RESULT, req=True, col=12),
        F("o_genuine", "Are the Attached Documents Genuine? (If No, please specify the reason – for e.g. is the "
                       "document forged, manipulated or any other reason)", "select", GENUINE, req=True, col=12),
        F("o_date", "Date of Verification", req=True, col=12),
        F("o_enrollment", "Enrollment/Registration No/Seat Number", col=12),
        F("o_lang", "Are your degree and transcripts in English or Arabic?", "select", YES_NO, col=12),
        F("o_resp_name", "Respondent Name", col=12),
        F("o_resp_email", "Respondent's Email Id", col=12),
        F("o_resp_desig", "Respondent Designation", col=12),
        F("o_payment", "Any payment done for obtain verification?", "select", YES_NO, req=True, col=12),
        F("o_son_of", "Son of/Sof is is mentioned on degree", "select", YES_NO, col=12),
        F("o_transfer_credit", "Transfer credit hours (Transfer student)", "select", TRANSFER_CREDIT, col=12),
    ]},
]

DOC_SLOTS = [
    {"group": "Verification", "slots": [
        {"key": "payment_proof", "label": "Payment Proof(If Applicable)", "required": False},
        {"key": "verification_proof", "label": "Verification Proof(Initiation Email/Roll number submission)", "required": False},
        {"key": "revert_1", "label": "Verification Revert 1(Incoming email/Online screenshot)", "required": True},
        {"key": "revert_2", "label": "Verification Revert 2(Email attachment/Other online document)", "required": False},
    ]},
    {"group": "Accreditation", "slots": [
        {"key": "accreditation", "label": "Accreditation Document", "required": False},
        {"key": "passing_criteria", "label": "Passing Criteria", "required": False},
    ]},
    {"group": "Other", "slots": [
        {"key": "other", "label": "Other Additional Document", "required": False},
    ]},
]

ALL_FIELDS = {f["key"]: f for s in SECTIONS for f in s["fields"]}


def schema():
    return {"sections": SECTIONS, "doc_slots": DOC_SLOTS}
