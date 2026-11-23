---
name: hv-closure-prototype
description: "HelloVerify education-closure automation prototype (HVOPS replica + engine) — goal, status notes location, open questions"
metadata:
  node_type: memory
  type: project
  originSessionId: 41494c4e-ace1-4248-9c88-02b4ede0026d
  modified: 2026-11-20T04:16:41.185Z
---

The user is building a founder demo at HelloVerify (background verification): a local replica of the HVOPS education
"closure" screen plus an engine that fills it from degree, transcript, initiation mail and revert mail in under 2 minutes
(manual baseline 15–20 min). v1 built 2026-11-20 in this folder (FastAPI `app/`, vanilla JS `web/`, `./run.sh`).

**Why:** the user told the founder the manual closure work could be automated; the demo must be a real working system, not slides.
**How to apply:** the user asked for progress notes as markdown in `status/` (research, architecture, decisions, plan, tasks, changes)
and wants no invented facts in them — keep those files updated with verified facts only. Cost matters: deterministic first, LLM only
where needed. Open items to confirm with ops are listed in `status/tasks.md`.
