"""Label → value extraction on positioned lines (the shapes seen on real reverts and marksheets)."""
from app.extract import layout


def L(text, x0, y0, x1, y1, score=0.99):
    return {"text": text, "box": [x0, y0, x1, y1], "score": score, "page": 0}


LABELS = {"NAME": "name", "REGISTER NO": "reg", "INSTITUTION": "inst", "STATUS": "status", "GENDER": "_",
          "COLLEGE OF STUDY": "college", "PROGRAMME NAME": "prog"}


def test_same_row_value():
    lines = [L("Status", 10, 100, 70, 120), L("Genuine", 200, 100, 280, 120)]
    assert layout.values(layout.kv(lines, LABELS)) == {"status": "Genuine"}


def test_value_stacked_under_label():
    lines = [L("NAME", 10, 100, 60, 115), L("RAVI KUMAR", 10, 120, 120, 135)]
    assert layout.values(layout.kv(lines, LABELS))["name"] == "RAVI KUMAR"


def test_inline_and_glued_values():
    lines = [L("Register No: 12345AB", 10, 100, 200, 120)]
    assert layout.values(layout.kv(lines, LABELS))["reg"] == "12345AB"
    lines = [L("Register No.12345AB", 10, 100, 200, 120)]
    assert layout.values(layout.kv(lines, LABELS))["reg"] == "12345AB"


def test_wrapped_value_centred_on_label_is_joined_in_order():
    # first value line sits slightly ABOVE the label row (as on the Anna University report)
    lines = [L("Institution", 700, 500, 790, 522),
             L("EXAMPLE COLLEGE OF", 950, 481, 1160, 503),
             L("ENGINEERING [Somewhere] -", 947, 498, 1175, 524),
             L("INDIA", 949, 519, 998, 543)]
    v = layout.values(layout.kv(lines, LABELS, multiline={"inst"}))
    assert v["inst"] == "EXAMPLE COLLEGE OF ENGINEERING [Somewhere] - INDIA"


def test_stop_label_ends_a_row_value():
    lines = [L("COLLEGE OF STUDY", 145, 199, 237, 213), L("EXAMPLE COLLEGE", 264, 195, 500, 214),
             L("GENDER", 691, 195, 730, 212), L("MALE", 777, 195, 810, 212)]
    v = layout.values(layout.kv(lines, LABELS, multiline={"college"}))
    assert v == {"college": "EXAMPLE COLLEGE"}


def test_value_split_over_cells_of_one_row():
    lines = [L("PROGRAMME NAME", 10, 100, 150, 120), L("MASTER OF", 200, 100, 290, 120),
             L("BUSINESS", 320, 100, 400, 120), L("ADMINISTRATION", 430, 100, 560, 120)]
    v = layout.values(layout.kv(lines, LABELS, multiline={"prog"}))
    assert v["prog"] == "MASTER OF BUSINESS ADMINISTRATION"


def test_ocr_damaged_label_matches_fuzzily():
    lines = [L("COLLEGE OF STUDV", 10, 100, 150, 120), L("EXAMPLE COLLEGE", 200, 100, 380, 120)]
    assert layout.values(layout.kv(lines, LABELS))["college"] == "EXAMPLE COLLEGE"


def test_value_below_prefers_cell_under_the_label():
    # table header + first data row, columns touching (OCR row/cell geometry): STATUS → the cell under it, not "-"
    hdr = [L("COURSE", 0, 100, 190, 136), L("TERM END PRACTICAL", 200, 100, 390, 136), L("STATUS", 400, 100, 590, 136)]
    row = [L("101A", 0, 145, 190, 181), L("-", 200, 145, 390, 181), L("COMPLETED", 400, 145, 590, 181)]
    assert layout.values(layout.kv(hdr + row, LABELS))["status"] == "COMPLETED"
