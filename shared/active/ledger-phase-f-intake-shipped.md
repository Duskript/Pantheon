# Phase F — Client Intake MVP (kanban t_ceace6ce)

**Shipped:** commit `6977536` on branch `feature/phase-f-client-intake`.
**Parent of:** `t_da92fd2c` (Tier-1 verify, hephaestus), `t_2d64d0dc` (Ponytail Tier-2, hephaestus).

## What shipped

21 source files under `src/ledger_intake/` + 4 test files + 1 build spec:

- **Email forwarding** — `api/email_intake.py` + `inbound/email_handler.py` + DocType JSON
- **Portal upload** — `api/portal_upload.py` + `public/portal/{index.html,portal.css,portal.js}`
- **SMS reminders** — `api/sms_reminder.py` + `twilio/client.py` + `twilio/templates/missing_docs.txt`
- **Scaffolding** — `hooks.py`, `pyproject.toml`, `patches.txt`
- **Tests** — 54 tests, 84% coverage, all green

## Gate verification (in this dev env)

- `tests/test_email_intake.py::test_email_intake_creates_communication` — passes
- `tests/test_portal_upload.py::test_portal_upload_happy_path` — passes
- `tests/test_sms_reminder.py::test_twilio_dry_run_writes_to_tmp` — passes

## Gate verification (in a live firm)

- Forward real email to `intake+{slug}@theoforge.app` → check `Customer.communications`
- Open `https://{firm}.theoforge.app/c/{slug}` on phone → upload → check `Client Intake Request` list
- `bench execute ledger_intake.api.sms_reminder.run_missing_docs_sms` → verify SMS via Twilio dashboard

## Konan's queue (NOT in this card)

- Twilio account + 10DLC brand/campaign registration per firm
- Postmark inbound stream config + `POSTMARK_INBOUND_SECRET`
- DNS for `intake.{firm}.theoforge.app`
- `provision-firm.sh` extension to drop the app into `frappe_apps/` (F.1.9)

## Out of scope (deferred F.1.x)

- F.1.6 OCR
- F.1.7 LLM classifier (basic keyword ships in v1)
- F.1.8 Gmail filter rule
- F.1.9 Per-founder rollout automation
- `ledger_admin` app (separate spec)