"""Outlook .msg / RFC822 .eml parsing, recursive (a forwarded .msg often carries the real mail as .eml)."""
import base64
import email
import re
from email import policy
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from pathlib import Path

HV_DOMAINS = ("helloverify.com", "helloverify.ae", "helloverify.in")
FREE_MAIL = ("gmail.com", "yahoo.com", "yahoo.co.in", "hotmail.com", "outlook.com", "live.com", "rediffmail.com",
             "icloud.com", "aol.com", "protonmail.com", "ymail.com")


def _safe(name: str) -> str:
    return re.sub(r"[^\w.\- ()]+", "_", name or "file").strip() or "file"


def _addr_list(value) -> list[dict]:
    if not value:
        return []
    return [{"name": n.strip(), "email": e.strip()} for n, e in getaddresses([str(value)]) if e or n]


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|head).*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", html)
    txt = re.sub(r"<[^>]+>", " ", html)
    txt = re.sub(r"&nbsp;", " ", txt)
    import html as _h
    txt = _h.unescape(txt)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", txt)).strip()


def _new(source: str) -> dict:
    return {"subject": "", "from_name": "", "from_email": "", "to": [], "cc": [], "date": "", "reply_to": "",
            "body_text": "", "body_html": "", "attachments": [], "children": [], "source": source}


def parse_file(path: Path, outdir: Path) -> dict:
    path = Path(path)
    outdir.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".msg":
        return parse_msg(path, outdir)
    return parse_eml_bytes(path.read_bytes(), outdir, path.name)


def parse_msg(path: Path, outdir: Path) -> dict:
    import extract_msg
    m = extract_msg.Message(str(path))
    return _from_msg_obj(m, outdir, path.name)


def _from_msg_obj(m, outdir: Path, source: str) -> dict:
    d = _new(source)
    d["subject"] = m.subject or ""
    n, e = parseaddr(m.sender or "")
    d["from_name"], d["from_email"] = n, e
    d["to"] = _addr_list(m.to)
    d["cc"] = _addr_list(m.cc)
    try:
        d["date"] = m.date.isoformat() if m.date else ""
    except Exception:
        d["date"] = str(m.date or "")
    html = m.htmlBody
    d["body_html"] = html.decode("utf-8", "ignore") if isinstance(html, bytes) else (html or "")
    d["body_text"] = (m.body or "").strip() or _html_to_text(d["body_html"])
    inline = {}
    for i, a in enumerate(m.attachments):
        name = _safe(getattr(a, "longFilename", None) or getattr(a, "shortFilename", None) or f"attachment{i}")
        data = a.data
        if hasattr(data, "subject") and hasattr(data, "attachments"):  # embedded .msg
            d["children"].append(_from_msg_obj(data, outdir / f"child{i}", name))
            continue
        if not isinstance(data, (bytes, bytearray)):
            continue
        head = bytes(data[:4000]).lower()
        if name.lower().endswith(".eml") or ("." not in name and b"subject:" in head and b"from:" in head):
            d["children"].append(parse_eml_bytes(bytes(data), outdir / f"child{i}", name))
            continue
        cid = getattr(a, "cid", None) or getattr(a, "contentId", None)
        p = outdir / name
        p.write_bytes(data)
        if cid:
            inline[cid.strip("<>")] = (p, getattr(a, "mimetype", None) or "image/png")
            if getattr(a, "hidden", False):
                continue
        d["attachments"].append({"name": name, "path": str(p), "size": len(data)})
    d["body_html"] = _inline_cids(d["body_html"], inline)
    return d


def parse_eml_bytes(raw: bytes, outdir: Path, source: str) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    e = email.message_from_bytes(raw, policy=policy.default)
    d = _new(source)
    d["subject"] = str(e["Subject"] or "")
    n, a = parseaddr(str(e["From"] or ""))
    d["from_name"], d["from_email"] = n, a
    d["to"] = _addr_list(e["To"])
    d["cc"] = _addr_list(e["Cc"])
    d["reply_to"] = str(e["Reply-To"] or "")
    try:
        d["date"] = parsedate_to_datetime(str(e["Date"])).isoformat()
    except Exception:
        d["date"] = str(e["Date"] or "")
    inline = {}
    for i, part in enumerate(e.walk()):
        ctype = part.get_content_type()
        disp = (part.get_content_disposition() or "")
        fname = part.get_filename()
        if ctype == "message/rfc822":
            payload = part.get_payload()
            inner = payload[0] if isinstance(payload, list) else payload
            d["children"].append(parse_eml_bytes(inner.as_bytes(), outdir / f"child{i}", fname or "forwarded.eml"))
            continue
        if part.is_multipart():
            continue
        if ctype == "text/plain" and not fname and disp != "attachment" and not d["body_text"]:
            d["body_text"] = part.get_content()
        elif ctype == "text/html" and not fname and disp != "attachment" and not d["body_html"]:
            d["body_html"] = part.get_content()
        elif fname or disp in ("attachment", "inline"):
            data = part.get_payload(decode=True) or b""
            name = _safe(fname or f"inline{i}")
            p = outdir / name
            p.write_bytes(data)
            cid = (part.get("Content-ID") or "").strip("<> ")
            if cid and disp != "attachment" and ctype.startswith("image/"):
                inline[cid] = (p, ctype)
                continue
            if name.lower().endswith(".eml"):
                d["children"].append(parse_eml_bytes(data, outdir / f"child{i}", name))
                continue
            d["attachments"].append({"name": name, "path": str(p), "size": len(data)})
    if not d["body_text"] and d["body_html"]:
        d["body_text"] = _html_to_text(d["body_html"])
    d["body_html"] = _inline_cids(d["body_html"], inline)
    return d


def _inline_cids(html: str, inline: dict) -> str:
    if not html or not inline:
        return html
    for cid, (p, ctype) in inline.items():
        b64 = base64.b64encode(Path(p).read_bytes()).decode()
        html = html.replace(f"cid:{cid}", f"data:{ctype};base64,{b64}")
    return html


def domain_of(addr: str) -> str:
    return addr.split("@")[-1].lower().strip() if "@" in (addr or "") else ""


def registrable_domain(host: str) -> str:
    host = (host or "").lower().strip().strip(".")
    host = re.sub(r"^https?://", "", host).split("/")[0].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("ac", "edu", "co", "gov", "org", "net", "res", "nic") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def is_hv(addr: str) -> bool:
    return domain_of(addr).endswith(HV_DOMAINS)


def is_forward_wrapper(m: dict) -> bool:
    """A forward that only transports another mail (FW: + embedded mail + (almost) empty own text)."""
    own = re.sub(r"(?i)regards,?|thanks,?|\s+", " ", m["body_text"]).strip()
    return bool(m["children"]) and (re.match(r"(?i)\s*(fw|fwd)\s*:", m["subject"] or "") is not None or len(own) < 80)


def effective_mails(m: dict) -> list[dict]:
    """Flatten: drop transport-only forwards, keep the real mails (with which file they came from)."""
    out = []
    if not is_forward_wrapper(m):
        out.append(m)
    for c in m["children"]:
        out.extend(effective_mails(c))
    return out


def role_of(m: dict) -> str:
    """initiation = sent by HelloVerify to the institution; revert = sent by the institution."""
    if is_hv(m["from_email"]):
        # HV mail that quotes the university reply inline (forward of a reply) -> revert content
        if re.search(r"(?im)^\s*from:\s*.*@(?!helloverify)", m["body_text"] or "") and \
                re.match(r"(?i)\s*(fw|fwd)\s*:", m["subject"] or ""):
            return "revert"
        return "initiation"
    return "revert"


def quoted_original_sender(m: dict) -> tuple[str, str]:
    mm = re.search(r"(?im)^\s*from:\s*(.+?)\s*<([^>]+@[^>]+)>", m["body_text"] or "")
    return (mm.group(1).strip(), mm.group(2).strip()) if mm else ("", "")
