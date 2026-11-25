"""Label → value extraction from positioned text lines (OCR output or PDF text layer).

Works for the layouts seen in real cases:
  * label and value on the same row            "Status        Genuine"
  * value stacked under the label              "NAME OF THE CANDIDATE" / "SREE KARTHIK A"
  * inline with a separator                    "Register No: 224EEM81513", "Reg. No.224EEM81513"
  * numbered letter tables                     "2   Register Number   224EEM81513"
  * values wrapped over several lines          "Institution   STELLA MARY'S COLLEGE OF" / "ENGINEERING ..."
"""
import re

from rapidfuzz import fuzz

from ..ocr import rows


def norm_label(s: str) -> str:
    s = (s or "").upper().replace("&", " & ")
    s = re.sub(r"^\s*\d{1,2}\s*[.)]?\s+", "", s)          # "2 Register Number" / "2. Name"
    s = re.sub(r"[^A-Z0-9& ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _h(l):
    return max(1.0, l["box"][3] - l["box"][1])


def _vover(a, b):
    lo, hi = max(a["box"][1], b["box"][1]), min(a["box"][3], b["box"][3])
    return max(0.0, hi - lo) / min(_h(a), _h(b))


class LabelSet:
    def __init__(self, labels: dict[str, str]):
        self.map = {norm_label(k): v for k, v in labels.items()}
        # prefix patterns for labels glued to their value ("Reg. No.224EEM81513"); short labels like "NAME"
        # are only accepted with an explicit ":" separator (too ambiguous otherwise)
        self.prefix = [(re.compile(r"^\s*" + r"[\W_]*".join(re.escape(w) for w in lab.split()) +
                                   r"(?![A-Za-z])[\W_]*(.+)$", re.I), v)
                       for lab, v in sorted(self.map.items(), key=lambda kv: -len(kv[0])) if len(lab) >= 5]

    def exact(self, text: str, fuzzy: bool = True) -> str | None:
        n = norm_label(text)
        hit = self.map.get(n)
        if hit is None and fuzzy and 8 <= len(n) <= 45:   # OCR-damaged labels: "COLLEGELINSTITUTE" ~ "COLLEGE INSTITUTE"
            best = max(self.map, key=lambda lab: fuzz.ratio(lab, n))
            if len(best) >= 8 and fuzz.ratio(best, n) >= 90:
                hit = self.map[best]
        return hit

    def inline(self, text: str) -> tuple[str, str] | None:
        """'Register No: 224EEM81513' / 'Reg. No.224EEM81513' → (key, value)."""
        raw = re.sub(r"^\s*\d{1,2}\s*[.)]?\s+", "", text or "")
        m = re.match(r"^\s*([A-Za-z][A-Za-z.&/ ]{1,40}?)\s*[:\-–]\s*(.+)$", raw)
        if m and self.exact(m.group(1)) is not None:
            return self.exact(m.group(1)), m.group(2).strip()
        for pat, key in self.prefix:
            m = pat.match(raw)
            if m and m.group(1).strip():
                return key, m.group(1).strip()
        return None

    def is_label(self, text: str) -> bool:
        return self.exact(text) is not None


def kv(lines: list[dict], labels: dict[str, str], multiline: set[str] = frozenset(),
       validate: dict | None = None, join_row: set[str] = frozenset()) -> dict[str, dict]:
    """Returns {key: {"value": str, "score": float, "lines": [line, ...]}}; first occurrence of a key wins.
    multiline: values that may wrap over several lines (and cells); join_row: values split over cells of one row."""
    L = LabelSet(labels)
    validate = validate or {}
    out: dict[str, dict] = {}
    label_rows = set()
    rws = rows(lines)
    row_of = {}
    for ri, row in enumerate(rws):
        for l in row:
            row_of[id(l)] = ri
            if L.is_label(l["text"]):
                label_rows.add(ri)

    def ok(key, val):
        if key.startswith("_"):           # stop-labels (GENDER, SEMESTER …) only end other values
            return False
        v = validate.get(key)
        return bool(val) and (v is None or bool(re.search(v, val)))

    def put(key, val, used):
        val = re.sub(r"\s+", " ", val).strip(" :-–|")
        if key in out or not ok(key, val):
            return False
        out[key] = {"value": val, "score": round(sum(u["score"] for u in used) / len(used), 3), "lines": used}
        return True

    for lab in sorted(lines, key=lambda l: (l.get("page", 0), l["box"][1], l["box"][0])):
        key = L.exact(lab["text"], fuzzy=False)
        h = _h(lab)
        same_page = [l for l in lines if l is not lab and l.get("page", 0) == lab.get("page", 0)]
        right_all = sorted((l for l in same_page if _vover(l, lab) >= 0.5 and l["box"][0] >= lab["box"][2] - 0.6 * h
                            and l["text"].strip(" :") != ""), key=lambda l: l["box"][0])

        def row_tail(start_idx):
            """For multi-word values split into several cells of the same row: join until the next label."""
            used, txt = [], ""
            for l in right_all[start_idx:]:
                if L.is_label(l["text"]) or L.inline(l["text"]):
                    break
                used.append(l)
                txt += " " + l["text"]
            return used, txt
        hit = L.inline(lab["text"]) if key is None else None
        if key is None and not hit:
            key = L.exact(lab["text"])          # fuzzy (OCR-damaged) bare label
        if key is None:
            if hit:
                used, txt = ([lab], hit[1])
                if hit[0] in multiline or hit[0] in join_row:
                    more, extra = row_tail(0)
                    used, txt = used + more, txt + extra
                put(hit[0], txt, used)
            continue
        if key in out:
            continue
        val, used, text = None, [], ""
        if right_all and not L.is_label(right_all[0]["text"]):
            # 1) same row, to the right (bare ":" cells already skipped)
            val = right_all[0]
            used, text = row_tail(0) if (key in multiline or key in join_row) else ([val], val["text"])
        else:
            # 2) directly below, overlapping the label column
            below = sorted((l for l in same_page if l["box"][1] >= lab["box"][3] - 2
                            and l["box"][1] - lab["box"][3] < 2.2 * h
                            and min(l["box"][2], lab["box"][2]) - max(l["box"][0], lab["box"][0]) > -h),
                           key=lambda l: l["box"][1])
            if below:   # nearest row first; within that row, the cell overlapping the label column most
                first = [l for l in below if l["box"][1] - below[0]["box"][1] < 0.5 * h]
                below[0] = max(first, key=lambda l: min(l["box"][2], lab["box"][2]) - max(l["box"][0], lab["box"][0]))
            if below and not L.is_label(below[0]["text"]):
                val = below[0]
                used, text = [val], val["text"]
        if val is None:
            continue
        if key in multiline:
            # a wrapped value is often centred on its label → its first line sits ABOVE the label row.
            # Same column + tight line spacing (< half a line) = same cell.
            prev = val
            for l in sorted((l for l in same_page if l["box"][1] < val["box"][1] - 2 and l not in used),
                            key=lambda l: -l["box"][3]):
                if len(used) >= 4:
                    break
                if abs(l["box"][0] - val["box"][0]) > 2.5 * h:
                    continue
                if prev["box"][1] - l["box"][3] > 0.5 * h or L.is_label(l["text"]) or row_of.get(id(l)) in label_rows:
                    break
                used.insert(0, l)
                text = l["text"] + " " + text
                prev = l
            # continuation lines below in the same column, rows without a label
            prev = val
            for l in sorted((l for l in same_page if l["box"][1] > val["box"][1] + 2 and l not in used
                             and _vover(l, val) < 0.5), key=lambda l: l["box"][1]):
                if len(used) >= 4 or l["box"][1] - prev["box"][3] > 0.6 * h:   # wrapped lines sit tight
                    break
                if abs(l["box"][0] - val["box"][0]) > 2.5 * h or row_of.get(id(l)) in label_rows:
                    continue
                if L.is_label(l["text"]):
                    break
                used.append(l)
                text += " " + l["text"]
                prev = l
        put(key, text, used)
    return out


def values(d: dict[str, dict]) -> dict[str, str]:
    return {k: v["value"] for k, v in d.items()}


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()
