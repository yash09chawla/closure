---
name: azure-doc-intelligence
description: "Company Azure Document Intelligence resource (from seniors) — private-endpoint only, blocked from dev laptop as of 2026-11-24"
metadata:
  node_type: memory
  type: project
  originSessionId: 1fad8a76-60a4-4fbd-aa32-ff09937c0e86
  modified: 2026-11-24T06:41:07.045Z
---

Seniors gave an Azure Document Intelligence resource for OCR: `hvops-doc-intel-uae` (region UAE North). Values in `.env` as
`AZURE_OCR_END_POINT` / `AZURE_OCR_KEY` (84-char key). The earlier `EDUCATION_OCR_API_TOKEN` was dropped.

2026-11-24 test: every call returns 403 "Public access is disabled. Please configure private endpoint." The DNS has a
privatelink CNAME, but the laptop (home/office Wi-Fi, no VPN, public IP 223.30.232.93) resolves the public IP, so the
resource is only reachable from inside the company VNet / VPN. Key validity is unverified because the network check fails first.
User (2026-11-24): paid tier; the company already uses it for UAE clients, whose data must stay in the UAE, so UAE residency is fine. Colleagues use it today, most likely from inside the company VNet/VPN.
Retest 2026-11-24 with GlobalProtect VPN up (adapter 'Ethernet 2', VPN DNS 192.168.10.249, egress IP 182.156.0.66): VPN DNS still returns the public IP 20.74.197.139, so it is still 403. The VPN does not route to the private endpoint; IT needs private DNS + route, or a colleague's private IP + hosts entry.
Probe script: scratchpad `azure_di_probe.py` (synthetic image first, then `--real` files).

**Why:** The user wants to evaluate Azure DI against the local OCR. Sending candidate documents there departs from the
[[no-candidate-data-external]] rule, and the user explicitly asked for it (a company-owned resource; data goes to the UAE region).
**How to apply:** Do not retry until the user confirms VPN access or an IP allow-list. Keep local OCR as the default
until Azure is proven and approved.
