// HVOPS replica — case page logic
const CID = location.pathname.split("/").pop();
let SCHEMA = null, CASE = null, POLL = null, CLOCK = null, FILLED_ONCE = false;
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const api = (u, o = {}) => fetch(u, o).then(async r => { if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText); return r.json(); });

async function init() {
  [SCHEMA, CASE] = await Promise.all([api("/api/schema"), api(`/api/cases/${CID}`)]);
  api("/api/status").then(s => $("#llmState").textContent = s.llm ? `LLM: ${s.extract_model}` : "offline mode (no LLM key)");
  renderStatic();
  renderForm();
  applyCase(CASE, false);
  renderUploads();
  if (CASE.status === "processing") startPolling();
  if (CASE.engine) { renderEngine(CASE.engine, true); }
  setupDrop();
}

// ---------------- static parts ----------------
function renderStatic() {
  const m = CASE.mohre;
  $("#banner").innerHTML = `<b>${esc(CASE.client)}</b> | Default | Default | <b>${esc(m.applicant_full_name)}</b>| ${esc(CASE.case_ref)} | <b>Mohre-api</b> | <b>workflow:</b>`;
  const ins = CASE.insuff || [];
  $("#insuff").innerHTML = `<tr><th>Raise date</th><th>Insuff Raise By</th><th>Insuff Type</th><th>Insuff Status</th><th>Insuff Pushed</th><th>Insuff Pushed Date</th><th>Insuff Remark ID</th><th style="width:38%">Insuff Tag Remark</th></tr>` +
    (ins.length ? ins.map(i => `<tr><td>${esc(i.date)}</td><td>${esc(i.by)}</td><td>${esc(i.type)}</td><td>${esc(i.status)}</td><td></td><td></td><td>${esc(i.id)}</td><td style="text-align:center">${esc(i.remark)}</td></tr>`).join("")
      : `<tr><td colspan="8" style="text-align:center;color:#888">No insufficiency raised</td></tr>`);
  document.querySelectorAll(".pvh-name").forEach(el => el.textContent = m.institute_name || "");
  document.querySelectorAll("#vtabs .t[data-tab]").forEach(t => t.addEventListener("click", () => showTab(t.dataset.tab)));
  $("#cs-id").value = CASE.case_ref; $("#cs-recv").value = CASE.received_on || "";
  document.title = `${CASE.case_ref} · Helloverify`;
}

// ---------------- form ----------------
function renderForm() {
  for (const sec of SCHEMA.sections) {
    const host = $(`#sec-${sec.id}`);
    if (!host) continue;
    host.innerHTML = `<div class="sec"><div class="h">${esc(sec.title)}</div><hr></div><div class="row">${sec.fields.map(fieldHtml).join("")}</div>`;
  }
  document.querySelectorAll("[data-key]").forEach(el => el.addEventListener("change", () => markEdited(el.dataset.key)));
  document.querySelectorAll(".switch").forEach(sw => sw.addEventListener("click", () => {
    const key = sw.dataset.nd, el = document.querySelector(`[data-key="${key}"]`);
    sw.classList.toggle("on");
    if (sw.classList.contains("on")) { el.value = "Not Disclosed"; el.readOnly = true; } else { el.value = ""; el.readOnly = false; }
    markEdited(key);
  }));
}

function fieldHtml(f) {
  const req = f.required ? '<span class="req">*</span>' : "";
  const nd = f.not_disclosed ? `<div class="nd"><span class="switch" data-nd="${f.key}"></span>Not Disclosed</div>` : "";
  let input;
  if (f.type === "select") {
    input = `<select class="fc" data-key="${f.key}" ${f.readonly ? "disabled" : ""}><option value=""></option>${f.options.map(o => `<option>${esc(o)}</option>`).join("")}</select>`;
  } else if (f.type === "textarea") {
    input = `<textarea class="fc" data-key="${f.key}" rows="3"></textarea>`;
  } else if (f.type === "file") {
    input = `<div class="file-link" data-file="${f.key}"><span class="choose">Choose File</span><span class="fname">No file chosen</span></div><input type="hidden" data-key="${f.key}">`;
  } else {
    input = `<input class="fc" type="text" data-key="${f.key}" ${f.readonly ? "readonly" : ""} autocomplete="off">`;
  }
  return `<div class="fg col-${f.col} ${f.readonly ? "ro" : ""}" id="fg-${f.key}"><label>${esc(f.label)} ${req}</label>${nd}${input}<span class="src"></span></div>`;
}

function setValue(key, v, meta, animate) {
  const el = document.querySelector(`[data-key="${key}"]`);
  if (!el) return;
  const fg = $(`#fg-${key}`);
  if (el.tagName === "SELECT" && v && ![...el.options].some(o => o.value === v)) {
    const o = document.createElement("option"); o.textContent = v; el.appendChild(o);
  }
  el.value = v ?? "";
  const sw = document.querySelector(`.switch[data-nd="${key}"]`);
  if (sw) { sw.classList.toggle("on", v === "Not Disclosed"); el.readOnly = v === "Not Disclosed"; }
  if (key === "a_proof") {
    const a = (CASE.documents?.accreditation || [])[0];
    const box = document.querySelector(`[data-file="a_proof"] .fname`);
    if (box) box.innerHTML = a ? `<a href="${a.url}" target="_blank">${esc(a.name)}</a>` : "No file chosen";
  }
  if (!meta || !fg) return;
  fg.classList.remove("filled", "flag", "edited");
  const edited = (meta.source || "").startsWith("Edited");
  fg.classList.add(edited ? "edited" : (meta.flag ? "flag" : "filled"));
  const src = fg.querySelector(".src");
  src.textContent = (meta.flag ? "⚠ " : "ⓘ ") + meta.source;
  src.title = `Source: ${meta.source}${meta.note ? "\nNote: " + meta.note : ""}`;
  if (animate) { fg.classList.remove("flash"); void fg.offsetWidth; fg.classList.add("flash"); }
}

function markEdited(key) {
  const fg = $(`#fg-${key}`); if (!fg) return;
  fg.classList.remove("filled", "flag"); fg.classList.add("edited");
  const src = fg.querySelector(".src"); src.textContent = "✎ edited — save to keep"; src.title = "";
}

function collectFields() {
  const out = {};
  document.querySelectorAll("[data-key]").forEach(el => { if (!el.closest(".ro")) out[el.dataset.key] = el.value; });
  return out;
}

function applyCase(c, animate) {
  const fields = c.fields || {};
  const keys = Object.keys(fields);
  if (animate) {
    keys.forEach((k, i) => setTimeout(() => setValue(k, fields[k].value, fields[k], true), i * 18));
  } else keys.forEach(k => setValue(k, fields[k].value, fields[k], false));
  $("#resultFound").checked = !!fields.o_genuine;
  const online = c.verification_mode === "online" || (fields.v_source || {}).value === "ONLINE";
  if (fields.v_source) document.querySelector(`#cs-sub input[value="${online ? "online" : "email"}"]`).checked = true;
  renderDocs(c.documents || {});
  renderMails(c.mails || []);
  renderOnline(c.online || [], ((c.engine || {}).facts || {}).online || {});
  if (c.verification_mode) showTab(online ? "online" : "email");
}

function showTab(id) {
  document.querySelectorAll("#vtabs .t[data-tab]").forEach(t => t.classList.toggle("on", t.dataset.tab === id));
  document.querySelectorAll(".tp").forEach(p => p.hidden = p.id !== `tab-${id}`);
}

// Online Database tab — one row per portal screenshot, like the e-mail table; facts card = what was fetched
function renderOnline(rows, on) {
  $("#cnt-online").textContent = rows.length;
  const head = `<tr><th>Check Id</th><th>Status</th><th>Portal</th><th>URL</th><th>Record Type</th><th>Enrolment No</th><th>Name</th><th>Programme</th><th>Status as on</th><th>Show</th><th>Response Recieved</th></tr>`;
  $("#onlinetbl").innerHTML = head + (rows.length ? rows.map((r, i) => {
    const f = r.fields || {}, c = r.courses || {};
    const done = r.type === "result" ? (c.total ? `${c.completed}/${c.total} COMPLETED` : "Record found") :
      (f.admission_year ? `Admission ${esc(f.admission_year)}` : "Record found");
    return `<tr><td>EDU-1/O${i + 1}</td><td>${f.enrollment_no || f.roll_no ? "Fetched" : "Not readable"}</td><td>${esc(r.host || "—")}</td>
      <td style="min-width:240px;max-width:320px;word-break:break-all;font-size:11px">${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener" title="${esc(r.url)}">${esc(r.url.replace(/^https?:\/\//, ""))}</a>` : "—"}</td>
      <td>${esc(r.label)}</td><td>${esc(f.enrollment_no || f.roll_no || "")}</td><td>${esc(f.welcome_name || f.name || "")}</td>
      <td>${esc(f.programme || "")}</td><td>${esc(f.status_as_on || f.current_date || "")}</td>
      <td style="white-space:nowrap">${r.pdf ? `<a href="${r.pdf}" target="_blank">PDF</a>` : ""}${r.shot ? ` · <a href="${r.shot}" target="_blank">screenshot</a>` : ""}</td>
      <td>Yes (${done})</td></tr>`;
  }).join("") : `<tr><td colspan="11" style="text-align:center;color:#888">No online portal screenshots — drop them in the Auto-Close panel</td></tr>`);
  const hosts = [...new Set(rows.map(r => r.url).filter(Boolean))];
  $("#pvh-portals").textContent = hosts.slice(0, 3).join(" , ");
  $("#pvh-portal-ok").textContent = rows.length ? "Yes" : "—";
  const of = on.fields || {}, cr = of._courses || {};
  if (!rows.length || !Object.keys(of).length) { $("#onlineFacts").innerHTML = ""; return; }
  const kv = [["Enrolment / Roll No", of.registration_no], ["Name", of.name], ["Programme", of.programme],
    ["University", of.university], ["Study start (Admission Year)", of.admission ? `${of.admission} → ${of.start_mm_yyyy || ""}` : ""],
    ["Admission valid upto", of.valid_upto], ["Year of passing", of.year_of_passing],
    ["Courses", cr.total ? `${cr.completed} of ${cr.total} COMPLETED${(cr.not_completed || []).length ? " · not completed: " + cr.not_completed.join(", ") : ""}` : ""],
    ["Result", of.result], ["Mode of study", of.mode_of_study ? `${of.mode_of_study} (${of._mode_how || ""})` : ""],
    ["Regional / Study Centre", [of.regional_centre, of.study_centre].filter(Boolean).join(" / ")],
    ["Verification date (status as on)", of.verified_date], ["Portal domain", (on.domains || []).join(", ")]].filter(([, v]) => v);
  $("#onlineFacts").innerHTML = `<div class="of-h">Details fetched from the online portal <span class="pill ${on.found ? "up" : ""}">${on.found ? "Record found" : "Record not confirmed"}</span></div>
    <div class="of-grid">${kv.map(([k, v]) => `<div><label>${esc(k)}</label><span>${esc(v)}</span></div>`).join("")}</div>
    <div class="of-note">${rows.some(r => r.method === "vision-llm") ? "Read from the screenshots with the OpenAI vision model" : "Read locally (OCR) from the screenshots — nothing sent to external services"}. Fields below are filled from these values (look for the “Online portal” source label).</div>`;
}

function renderMails(mails) {
  $("#cnt-email").textContent = mails.length;
  const head = `<tr><th>Check Id</th><th>Status</th><th>Mail To</th><th>Mail From</th><th>Mail Type</th><th>Send date</th><th>Revert date</th><th>Show</th><th>Response Recieved</th></tr>`;
  const fmt = d => { try { return new Date(d).toLocaleString("en-GB", {day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit"}); } catch { return d; } };
  $("#mailtbl").innerHTML = head + mails.map((m, i) => `<tr><td>EDU-1/${i + 1}</td><td>${m.role === "revert" ? "Received" : "Sent"}</td><td>${esc(m.to)}</td><td>${esc(m.from)}</td>
    <td>${m.role === "revert" ? "Revert" : "Initiation"}</td><td>${m.role === "initiation" ? fmt(m.date) : ""}</td><td>${m.role === "revert" ? fmt(m.date) : ""}</td>
    <td>${esc(m.subject)}</td><td>${m.role === "revert" ? "Yes" + (m.attachments.length ? ` (${m.attachments.map(esc).join(", ")})` : "") : ""}</td></tr>`).join("");
  const rev = mails.find(m => m.role === "revert");
  if (rev) $("#pvh-sender").textContent = rev.from.replace(/.*</, "").replace(">", "");
}

function renderDocs(docs) {
  let html = "";
  for (const g of SCHEMA.doc_slots) {
    html += `<div class="docs-group">${esc(g.group)}</div><table class="docs"><tr><th>Document</th><th>Status</th><th>File Name</th><th>Action</th></tr>`;
    for (const s of g.slots) {
      const files = docs[s.key] || [];
      html += `<tr><td class="d"><b>${esc(s.label)}${s.required ? ' <span style="color:var(--red)">*</span>' : ""}</b><small>You can upload multiple files; each upload adds to the list.</small></td>
        <td><span class="pill ${files.length ? "up" : ""}">${files.length ? "Uploaded" : "Pending"}</span></td>
        <td class="flist">${files.length ? files.map(f => `<a href="${f.url}" target="_blank" title="${esc(f.source)}">${esc(f.name)}${f.generated ? '<span class="gen">auto</span>' : ""}</a>`).join("") : "—"}</td>
        <td><button class="upbtn" onclick="slotUpload('${s.key}')">⬆ ${files.length ? "Add more" : "Upload"}</button></td></tr>`;
    }
    html += `</table>`;
  }
  $("#docs").innerHTML = html;
}

function slotUpload(slot) {
  const inp = document.createElement("input"); inp.type = "file"; inp.multiple = true;
  inp.onchange = async () => {
    const fd = new FormData(); [...inp.files].forEach(f => fd.append("files", f));
    const c = await api(`/api/cases/${CID}/slot/${slot}`, {method: "POST", body: fd});
    CASE.documents = c.documents; renderDocs(c.documents);
  };
  inp.click();
}

// ---------------- uploads / engine ----------------
function setupDrop() {
  const d = $("#drop"), inp = $("#fileIn");
  d.onclick = () => inp.click();
  inp.onchange = () => uploadFiles(inp.files);
  ["dragenter", "dragover"].forEach(ev => d.addEventListener(ev, e => { e.preventDefault(); d.classList.add("over"); }));
  ["dragleave", "drop"].forEach(ev => d.addEventListener(ev, e => { e.preventDefault(); d.classList.remove("over"); }));
  d.addEventListener("drop", e => uploadFiles(e.dataTransfer.files));
}

async function uploadFiles(list) {
  if (!list.length) return;
  const fd = new FormData(); [...list].forEach(f => fd.append("files", f));
  await api(`/api/cases/${CID}/upload`, {method: "POST", body: fd});
  await refresh(); renderUploads();
}

async function loadSample(kind = "anna") { await api(`/api/cases/${CID}/sample-docs?kind=${kind}`, {method: "POST"}); await refresh(); renderUploads(); }

async function delUpload(n) { await api(`/api/cases/${CID}/uploads/${encodeURIComponent(n)}`, {method: "DELETE"}); await refresh(); renderUploads(); }

async function refresh() { CASE = await api(`/api/cases/${CID}`); }

function renderUploads() {
  const kinds = {};
  ((CASE.engine || {}).docs || []).forEach(d => kinds[d.name] = d.kind);
  const icon = n => /\.(msg|eml)$/i.test(n) ? "✉" : /\.pdf$/i.test(n) ? "📄" : "🖼";
  $("#ulist").innerHTML = (CASE.uploads || []).map(u => `<div class="u"><span>${icon(u.name)}</span><a class="n" href="${u.url}" target="_blank">${esc(u.name)}</a>
    ${kinds[u.name] ? `<span class="k">${esc(kinds[u.name].replace("_", " "))}</span>` : ""}<span class="del" title="remove" onclick="delUpload('${esc(u.name).replace(/'/g, "\\'")}')">✕</span></div>`).join("")
    || `<div class="eh-sub" style="padding:4px 0">No documents yet.</div>`;
  $("#runBtn").disabled = !(CASE.uploads || []).length;
}

async function runEngine() {
  $("#runBtn").disabled = true; $("#runBtn").textContent = "Working…";
  FILLED_ONCE = false;
  clearForm();
  try { await api(`/api/cases/${CID}/run`, {method: "POST"}); } catch (e) { alert(e.message); $("#runBtn").disabled = false; $("#runBtn").textContent = "▶ Auto-close this case"; return; }
  const t0 = Date.now();
  clearInterval(CLOCK);
  CLOCK = setInterval(() => $("#clock").textContent = ((Date.now() - t0) / 1000).toFixed(1) + "s", 100);
  startPolling();
}

function clearForm() {
  document.querySelectorAll('.fg[id^="fg-"]').forEach(fg => { if (fg.classList.contains("ro")) return; fg.classList.remove("filled", "flag", "edited"); fg.querySelector(".src").textContent = ""; const el = fg.querySelector("[data-key]"); if (el) el.value = ""; });
  $("#flags").innerHTML = ""; $("#kpis").style.display = "none"; $("#flagsTitle").style.display = "none";
  renderDocs({}); renderOnline([], {}); renderMails([]);
}

// Progress polling: one request every 1.5 s while a run is in progress, never two at once,
// paused while the tab is hidden, stopped as soon as the run finishes.
const POLL_MS = 1500;
let POLLING = false;

function startPolling() {
  POLLING = true;
  clearTimeout(POLL);
  POLL = setTimeout(pollOnce, 300);          // first update quickly, then every POLL_MS
}

function stopPolling() { POLLING = false; clearTimeout(POLL); }

async function pollOnce() {
  if (!POLLING) return;
  if (document.hidden) return;                // resumed by the visibilitychange handler
  try { await refresh(); } catch (e) { POLL = setTimeout(pollOnce, POLL_MS * 2); return; }
  if (CASE.run) renderEngine(CASE.run, false);
  const finished = CASE.run ? CASE.run.status !== "running" : CASE.status !== "processing";
  if (!finished) { POLL = setTimeout(pollOnce, POLL_MS); return; }
  stopPolling(); clearInterval(CLOCK);
  if ((CASE.run || {}).status === "done" && !FILLED_ONCE) {
    FILLED_ONCE = true;
    renderEngine(CASE.engine, true);
    applyCase(CASE, true);
    renderUploads();
  }
  $("#runBtn").disabled = false; $("#runBtn").textContent = "↻ Re-run engine";
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && POLLING) { clearTimeout(POLL); pollOnce(); }
});

function renderEngine(e, final) {
  $("#steps").innerHTML = e.steps.map(s => `<li class="${s.status}"><span class="st"></span><span class="lb"><b>${esc(s.label)}</b>${s.detail ? `<small>${esc(s.detail)}</small>` : ""}</span><span class="sec2">${s.seconds != null ? s.seconds + "s" : ""}</span></li>`).join("");
  $("#log").textContent = (e.log || []).map(l => `${String(l.t).padStart(5)}s  ${l.msg}`).join("\n") || "…";
  $("#log").scrollTop = 1e6;
  if (final && e.finished) {
    const secs = e.seconds ?? Math.round((e.finished - e.started) * 10) / 10;
    $("#clock").textContent = secs + "s"; $("#clockLbl").textContent = "engine time (last run)";
    const filled = Object.keys(CASE.fields || {}).length;
    const docs = Object.values(CASE.documents || {}).reduce((a, b) => a + b.length, 0);
    $("#kpis").style.display = "grid";
    $("#kpis").innerHTML = `<div class="kpi"><b>${filled}</b><span>fields filled</span></div><div class="kpi"><b>${docs}</b><span>docs attached</span></div><div class="kpi"><b>$${(e.cost_usd || 0).toFixed(3)}</b><span>LLM cost</span></div>`;
    const flags = CASE.flags || [];
    $("#flagsTitle").style.display = flags.length ? "block" : "none";
    $("#flags").innerHTML = flags.map(f => `<div class="f ${f.level}" onclick="goTo('${f.field}')">${f.level === "error" ? "✗" : "⚠"} ${esc(f.msg)}</div>`).join("");
  }
}

function goTo(key) {
  const el = $(`#fg-${key}`) || [...document.querySelectorAll(".docs td.d b")].find(b => b.textContent.toLowerCase().includes(key.replace(/_/g, " ").split(" ")[0]));
  if (el) { el.scrollIntoView({behavior: "smooth", block: "center"}); el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash"); }
}

// ---------------- save / submit ----------------
async function saveFields() {
  CASE = await api(`/api/cases/${CID}/fields`, {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify({fields: collectFields()})});
  applyCase(CASE, false);
  toast("Saved.");
}

async function finalSubmit() {
  if (!Object.keys(CASE.fields || {}).length) { alert("Nothing to submit yet — run the engine or fill the form."); return; }
  const missing = [];
  for (const s of SCHEMA.sections) for (const f of s.fields) {
    const el = document.querySelector(`[data-key="${f.key}"]`);
    if (f.required && el && !el.value && !f.readonly) missing.push(f.label);
  }
  if (missing.length && !confirm(`${missing.length} required field(s) are empty:\n• ${missing.slice(0, 8).join("\n• ")}\n\nSubmit anyway?`)) return;
  const c = await api(`/api/cases/${CID}/submit`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({fields: collectFields()})});
  CASE = c;
  const secs = c.closure_seconds, eng = (c.engine || {}).seconds;
  const mm = s => { s = Math.round(s * 10) / 10; return s >= 60 ? `${Math.floor(s / 60)}m ${Math.round(s % 60)}s` : `${s}s`; };
  $("#modalBody").innerHTML = `<h3>Case closed ✔</h3><div>${esc(c.case_ref)} — ${esc(c.mohre.applicant_full_name)}</div>
    <div class="big-win">${secs ? mm(secs) : "—"}</div><div>from document drop to final submit (engine: ${eng}s, review: ${secs && eng ? mm(Math.max(0, secs - eng)) : "—"})</div>
    <p style="color:#666">Manual baseline: 15–20 minutes per case. Reviewer edits recorded: ${Object.keys(c.edits || {}).length}.</p>
    <div style="display:flex;gap:10px;margin-top:14px"><a class="btn-red" href="/" style="text-decoration:none">Back to cases</a><button class="btn-light" onclick="$('#modal').classList.remove('on')">Stay</button></div>`;
  $("#modal").classList.add("on");
}

function toast(msg) {
  const t = document.createElement("div");
  t.textContent = msg; Object.assign(t.style, {position: "fixed", bottom: "20px", left: "50%", transform: "translateX(-50%)", background: "#333", color: "#fff", padding: "8px 16px", borderRadius: "6px", zIndex: 200, fontSize: "12px"});
  document.body.appendChild(t); setTimeout(() => t.remove(), 1800);
}

init();
