---
name: hv-closure-prototype
description: "HelloVerify education-closure automation (HVOPS replica + engine) — goal, status notes location, environment quirks"
metadata:
  node_type: memory
  type: project
  originSessionId: 1fad8a76-60a4-4fbd-aa32-ff09937c0e86
  modified: 2026-11-25T05:09:34.492Z
---

The user is building, at HelloVerify (background verification), a local replica of the HVOPS education "closure"
screen plus an engine that fills it from degree, transcript, initiation mail and revert mail (manual baseline
15–20 min). v1 demo built 2026-11-20 (FastAPI `app/`, vanilla JS `web/`); since 2026-11-23 being hardened toward
production step by step (see [[production-hardening-goal]]).

**Why:** the user told the founder the manual closure work could be automated; it must be a real working system.
**How to apply:** the user wants progress notes as markdown in `status/` (research, architecture, decisions, plan,
tasks, changes, handoff) with verified facts only — update them with every change. Cost matters: deterministic
first. Environment (Windows machine): venv is Python 3.14; start with `run.ps1`. OCR has been OpenAI vision since
2026-11-25 (local RapidOCR removed). Python edits run through a Bash heredoc mangle backslash escapes
(backslash-b, backslash-n): use the Edit/Write tools for code with escapes, and set PYTHONIOENCODING=utf-8 when printing.
Real samples live in `Cases/Case1…6`. See [[no-candidate-data-external]].
