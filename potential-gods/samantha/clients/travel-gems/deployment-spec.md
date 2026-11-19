# Samantha Deployment Spec — Travel Gems (Erica)

> Status: DRAFT — populated from Konan's 2026-10-17 brief. Fields marked ❓ need Erica.

---

## Client Profile

- **Business name:** Travel Gems
- **Owner / primary user:** Erica
- **Role:** Travel planner / advisor
- **Host agency:** Fora (assumed — Fora MCP requested)
- **Team size:** ❓ (solo, or does she have an assistant?)
- **Client volume:** ❓ active travelers; ❓ new inquiries/month
- **Timezone:** ❓
- **Working hours:** ❓ (drives cron scheduling)

## Tech Stack

- **Email:** ❓ Gmail / Google Workspace / Microsoft 365 / other
- **Calendar:** ❓ Google Calendar / Outlook / other
- **Booking platform:** Fora advisor platform
- **Fora MCP:** ❓ endpoint + auth method (advisor token? OAuth against Fora?)
- **CRM / trip tracking today:** ❓ spreadsheet / Fora only / nothing
- **Website / inquiry form:** ❓ (where do new leads land?)

## Pain Points (needs Erica's ranking)

1. ❓
2. ❓
3. ❓

**Working hypothesis** (from Konan's brief): the pain is *preparation cost* — every
meeting requires reconstructing the client's file from memory, email, and the Fora
portal. Samantha's job is to make that reconstruction instant and complete.

## MVP Scope — Phase 1

- [ ] Inbox triage with urgency tiers (client trip change / supplier / money / inquiry / noise)
- [ ] Important-email push within minutes
- [ ] Calendar read + write, conflict detection, prep-block insertion
- [ ] Pre-meeting briefing generated T-60 with traveler file + open items + ask list
- [ ] Daily morning brief at fixed local time
- [ ] Draft-only email replies (Erica approves)

## Phase 2

- [ ] Fora MCP: live bookings, commissions, hotel/partner inventory
- [ ] Supplier payment & cancellation deadline watch
- [ ] Commission reconciliation reminders
- [ ] Quote follow-up cadence for stalled inquiries

## Phase 3

- [ ] Per-traveler lifecycle state machine (inquiry → quote → booked → pre-trip → in-trip → post-trip)
- [ ] Post-trip review request + repeat-booking prompt
- [ ] Quarterly revenue review

## Cron Schedule (draft — pending hours/timezone)

- **05:30** build morning brief (silent)
- **07:00** deliver morning brief
- **every 15 min (working hours)** urgent email scan
- **T-60 before each meeting** pre-meeting brief
- **Fri 16:00** weekly pipeline + revenue snapshot

## Knowledge Base (`Codex-Samantha/`)

- [ ] Supplier & hotel partner notes (Fora-preferred properties, perks)
- [ ] Erica's voice samples — 20-30 sent emails, for draft-matching tone
- [ ] Destination cheat sheets she already maintains
- [ ] Client roster notes (traveler preferences, passports, anniversaries)
- [ ] Commission structure + payment calendar
- [ ] Standard trip-planning workflow she actually follows

## Credentials Needed

- [ ] Google Workspace (or M365) OAuth — Gmail + Calendar scopes
- [ ] Fora advisor credentials / MCP token
- [ ] Website inquiry webhook (if applicable)
- [ ] Messaging channel token for briefings (Discord bot or Telegram)

## Primary User

- **Name:** Erica
- **Tech comfort (1-10):** ❓
- **Preferred briefing channel:** ❓
- **Tone preference:** Samantha Jones energy approved by client? ❓

## Deployment

- **Host:** ❓ Erica's machine / VPS provisioned by TheoForge
- **Pantheon base:** fresh install, core-only (no fleet gods, no Conductor)
- **Inference:** ❓ whose provider key
- **Data residency:** ❓ is traveler PII allowed in local Ichor DB, or does it stay in Gmail/Fora only
- **Support model:** ❓ how Erica gets help when Samantha misbehaves

## Commercial

- **Setup fee:** ❓
- **Monthly retainer:** ❓
- **Scope boundary:** which of the above is included at that price
