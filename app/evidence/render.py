"""HTML templates for evidence PDFs: Outlook-style mail view and browser-framed screenshots."""
import base64
import html as H
import re
from datetime import datetime
from pathlib import Path


def data_url(path: str | Path) -> str:
    p = Path(path)
    ext = p.suffix.lower().lstrip(".")
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif", "webp": "webp"}.get(ext, "png")
    return f"data:image/{mime};base64," + base64.b64encode(p.read_bytes()).decode()


def e(s) -> str:
    return H.escape(str(s or ""))


def _fmt_date(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso)
        if d.tzinfo:
            d = d.astimezone()  # Outlook shows the reader's local time
        return d.strftime("%a %d-%m-%Y %H:%M")
    except Exception:
        return iso or ""


def _initials(name: str) -> str:
    parts = [p for p in re.split(r"[\s\-]+", name or "") if p[:1].isalpha()]
    return ((parts[0][:1] + (parts[1][:1] if len(parts) > 1 else "")) if parts else "?").upper()


def _sanitize(html: str) -> str:
    html = re.sub(r"(?is)<(script|iframe|object|embed)[^>]*>.*?</\1>", "", html or "")
    html = re.sub(r"(?is)<meta[^>]*>|<base[^>]*>", "", html)
    html = re.sub(r"(?i)\son\w+\s*=\s*(\"[^\"]*\"|'[^']*')", "", html)
    return html


def mail_html(m: dict, role_label: str) -> str:
    to = "; ".join(f"{a['name']} &lt;{e(a['email'])}&gt;" if a["name"] else e(a["email"]) for a in m["to"]) or ""
    cc = "; ".join(f"{a['name']} &lt;{e(a['email'])}&gt;" if a["name"] else e(a["email"]) for a in m["cc"]) or ""
    atts = "".join(
        f'<div class="att"><div class="pdf">{e(Path(a["name"]).suffix.upper().lstrip(".") or "FILE")}</div>'
        f'<div><div class="an">{e(a["name"])}</div><div class="as">{max(1, a["size"] // 1024)} KB</div></div></div>'
        for a in m["attachments"])
    body = _sanitize(m["body_html"]) if m["body_html"].strip() else f"<pre>{e(m['body_text'])}</pre>"
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box}} body{{margin:0;font-family:'Segoe UI',-apple-system,Helvetica,Arial,sans-serif;color:#242424;background:#fff}}
.bar{{background:#0f6cbd;color:#fff;font-size:12px;padding:6px 18px;display:flex;justify-content:space-between}}
.wrap{{padding:18px 22px 26px}} h1{{font-size:20px;font-weight:600;margin:0 0 16px}}
.hdr{{display:flex;gap:12px;align-items:flex-start}} .av{{width:44px;height:44px;border-radius:50%;background:#d6d6d6;color:#555;
display:flex;align-items:center;justify-content:center;font-size:16px;flex:none}}
.who{{flex:1;font-size:14px}} .who b{{font-weight:600}} .meta{{font-size:12.5px;color:#555;margin-top:3px}}
.acts{{display:flex;gap:6px;font-size:12.5px}} .acts span{{border:1px solid #d1d1d1;border-radius:4px;padding:5px 10px;color:#444}}
.date{{text-align:right;font-size:12px;color:#555;margin-top:8px}}
.atts{{display:flex;gap:10px;margin:14px 0 4px 56px;flex-wrap:wrap}} .att{{display:flex;gap:8px;align-items:center;border:1px solid #c7d7ee;
background:#d9e6f7;border-radius:3px;padding:6px 12px 6px 8px;min-width:190px}}
.pdf{{background:#c4314b;color:#fff;font-size:9px;font-weight:700;padding:6px 4px;border-radius:2px}} .an{{font-size:13px}} .as{{font-size:11px;color:#555}}
.body{{margin:18px 0 0 0;font-size:14.5px;line-height:1.45;overflow-wrap:anywhere}} .body img{{max-width:100%}} .body table{{max-width:100%}}
pre{{white-space:pre-wrap;font-family:inherit}}
.foot{{margin-top:22px;border-top:1px solid #eee;padding-top:8px;font-size:10.5px;color:#888}}
</style></head><body>
<div class="bar"><span>Outlook — {e(role_label)}</span><span>Source file: {e(m.get('file') or m.get('source'))}</span></div>
<div class="wrap"><h1>{e(m['subject'])}</h1>
<div class="hdr"><div class="av">{e(_initials(m['from_name'] or m['from_email']))}</div>
<div class="who"><b>{e(m['from_name'])}</b> &lt;{e(m['from_email'])}&gt;
<div class="meta">To&nbsp;&nbsp;{to}</div>{f'<div class="meta">Cc&nbsp;&nbsp;{cc}</div>' if cc else ''}
{f'<div class="meta">Reply-To&nbsp;&nbsp;{e(m["reply_to"])}</div>' if m.get('reply_to') else ''}</div>
<div><div class="acts"><span>↩ Reply</span><span>↩↩ Reply All</span><span>→ Forward</span></div>
<div class="date">{e(_fmt_date(m['date']))}</div></div></div>
{f'<div class="atts">{atts}</div>' if atts else ''}
<div class="body">{body}</div>
<div class="foot">Rendered from the original e-mail file by HV Closure Engine on {datetime.now().strftime('%d-%m-%Y %H:%M')}. Headers and body are reproduced unaltered.</div>
</div></body></html>"""


def browser_frame(url: str, img_src: str, kind: str = "web", title: str = "", page_info: str = "",
                  find_text: str = "") -> str:
    """kind='web' → Chrome tab + address bar; kind='pdf' → Chrome address bar + PDF viewer toolbar."""
    short = re.sub(r"^https?://", "", url)
    pdfbar = ""
    if kind == "pdf":
        pdfbar = f"""<div class="pv"><span>☰&nbsp;&nbsp;{e(title)}</span><span class="pg">{e(page_info)}&nbsp;&nbsp;|&nbsp;&nbsp;−&nbsp; 100% &nbsp;+</span>
<span>{f'<span class="find">🔍 {e(find_text)}</span>' if find_text else ''}⤓ &nbsp;🖶</span></div>"""
    return f"""<div class="bf"><div class="tb"><span class="nav">←&nbsp; →&nbsp; ⟳</span>
<div class="addr"><span class="lock">🔒</span><span class="u">{e(short)}</span></div><span class="nav">☆ ⋮</span></div>
{pdfbar}<div class="shot{' dark' if kind == 'pdf' else ''}"><img src="{img_src}"></div></div>"""


FRAME_CSS = """
.bf{border:1px solid #c9c9c9;border-radius:8px;overflow:hidden;margin:8px 0 18px;box-shadow:0 1px 4px rgba(0,0,0,.12)}
.tb{background:#f1f3f4;display:flex;align-items:center;gap:10px;padding:7px 10px;border-bottom:1px solid #ddd}
.nav{color:#5f6368;font-size:13px;white-space:nowrap}
.addr{flex:1;background:#fff;border:2px solid #1a73e8;border-radius:16px;padding:3px 12px;font-size:12px;display:flex;gap:6px;
align-items:center;overflow:hidden} .addr .u{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;background:#cfe0fc}
.pv{background:#323639;color:#f1f1f1;font-size:11.5px;display:flex;justify-content:space-between;padding:7px 12px}
.find{background:#fff;color:#222;border-radius:3px;padding:1px 8px;margin-right:12px}
.shot{background:#fff;text-align:center;line-height:0} .shot.dark{background:#525659;padding:8px 0}
.shot img{max-width:100%;max-height:600px;object-fit:contain}
"""


def evidence_html(header: list[tuple[str, str]], blocks: list[dict], footer: str) -> str:
    """header: [(label, value-or-url)]; blocks: [{heading, url, frame_html, caption, quote}]"""
    def val(v):
        return f'<a href="{e(v)}">{e(v)}</a>' if str(v).startswith("http") else e(v)

    head = "".join(f"<p><b>{e(k)}:</b> {val(v)}</p>" for k, v in header)
    body = ""
    for b in blocks:
        body += f'<div class="blk">{f"<h3>{e(b["heading"])}</h3>" if b.get("heading") else ""}'
        if b.get("url"):
            body += f'<p class="lnk"><a href="{e(b["url"])}">{e(b["url"])}</a></p>'
        body += b.get("frame_html", "")
        if b.get("quote"):
            body += f'<blockquote>{e(b["quote"])}</blockquote>'
        if b.get("caption"):
            body += f'<p class="cap">{e(b["caption"])}</p>'
        body += "</div>"
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
body{{font-family:Calibri,'Segoe UI',Helvetica,Arial,sans-serif;color:#1f1f1f;margin:0;font-size:14px}}
p{{margin:6px 0}} a{{color:#0563c1}} h3{{font-size:15px;margin:18px 0 4px}} .lnk{{font-size:13px;word-break:break-all}}
.blk{{}} .bf{{page-break-inside:avoid}} blockquote{{border-left:4px solid #f0b400;background:#fff8e1;margin:6px 0 10px;padding:8px 12px;
font-size:12.5px;white-space:pre-wrap}} .cap{{font-size:11.5px;color:#555}}
.foot{{margin-top:14px;font-size:10.5px;color:#777;border-top:1px solid #ddd;padding-top:6px}}
{FRAME_CSS}</style></head><body>{head}{body}<div class="foot">{e(footer)}</div></body></html>"""
