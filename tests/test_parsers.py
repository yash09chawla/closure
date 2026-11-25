"""Revert + degree parsing — local rules, synthetic texts modelled on the real formats in Cases/."""
from app.extract import certs, revert


def doc(text, name="revert.pdf"):
    return {"name": name, "text": text, "lines": [], "text_layer": True}


def test_prose_letter_revert():
    text = ("EXAMPLE INTERNATIONAL (DEEMED UNIVERSITY)\nSir/Madam,\nThis is with reference regarding verification of "
            "Ravi Kumar.\nRavi Kumar, PRN-99887766554, is a bonafide student of Example Institute of Management, Pune, "
            "a constituent of Example International (Deemed University), Pune. He/She has completed Master of Business "
            "Administration (Finance), a regular degree programme in April 2015. He/She has secured CGPA 3.1 out of 4.")
    f = revert.parse_revert(None, [doc(text)], ["RAVI KUMAR"])["fields"]
    assert f["status"] == "Genuine"
    assert f["registration_no"] == "99887766554"
    assert f["degree"] == "Master of Business Administration (Finance)"
    assert f["year_of_passing"] == "April 2015"
    assert f["mode_of_study"] == "Regular"
    assert f["cgpa"] == "3.1 / 4"
    assert f["institution"] == "Example Institute of Management, Pune"
    assert f["name"].lower() == "ravi kumar"


def test_numbered_table_letter_revert():
    text = ("With reference to the cited above, the candidate has qualified for the degree as per the following details:\n"
            "1\tName\tRAVI KUMAR\n2\tRegister Number\t224ABC81513\n3\tDegree Qualified\tBachelor of Technology in "
            "Civil Engineering\n4\tYear of Passing\tJANUARY 2024\n5\tClass\tSECOND CLASS\n6\tMode of Study\tFULL TIME\n"
            "Further, the copy of Certificate is GENUINE and found correct as per our office records")
    f = revert.parse_revert(None, [doc(text)], ["RAVI KUMAR"])["fields"]
    assert f["status"] == "Genuine"
    assert f["registration_no"] == "224ABC81513"
    assert f["degree"].startswith("Bachelor of Technology")
    assert f["year_of_passing"] == "JANUARY 2024"
    assert f["mode_of_study"].upper() == "FULL TIME"


def test_negative_revert_is_never_genuine():
    text = "We regret to inform you that the certificate is NOT GENUINE and was not issued by this university."
    assert revert.parse_revert(None, [doc(text)], [])["fields"]["status"] == "Not Genuine"


def test_online_verification_is_not_a_study_mode():
    f = revert.parse_prose("COE / Online Verification portal. Status Genuine.", [])
    assert "mode_of_study" not in f


def test_name_found_in_any_order():
    assert revert._find_name("Name: SHARMA RAVI KUMAR Programme Code: X", ["Ravi Kumar Sharma"]) == "SHARMA RAVI KUMAR"


def test_degree_certificate_sentences():
    text = ("The Syndicate of the Example University hereby makes known that\nRAVI KUMAR S has been admitted to the "
            "DEGREE OF BACHELOR\nOF ENGINEERING in CIVIL ENGINEERINGunder the Faculty of\nCivil Engineering, having "
            "completed the prescribed programme, and has been placed in FIRST CLASS at the Examination held in\n"
            "NOVEMBER 2024.\nReg.No. 123456789/RG")
    lines = [{"text": t, "score": 0.99, "box": [0, i * 20, 500, i * 20 + 15], "page": 0}
             for i, t in enumerate(text.split("\n"))]
    f, _ = certs.read_degree([{"text": text, "lines": lines}])
    assert f["candidate_name"] == "RAVI KUMAR S"
    assert f["degree_title"] == "Bachelor of Engineering in Civil Engineering"
    assert f["degree_short"] == "B.E."
    assert f["class_awarded"] == "First Class"
    assert f["exam_month_year"] == "November 2024"
    assert f["register_no"] == "123456789/RG"
    assert f["university"] == "Example University"


def test_gothic_font_ocr_confusions_are_repaired():
    text = "this Unibersity hereby make knoun that RAVI KUMAR has been admitted to the Degree of Bachelor of Technology"
    f, _ = certs.read_degree([{"text": text, "lines": []}])
    assert f["candidate_name"] == "RAVI KUMAR"
