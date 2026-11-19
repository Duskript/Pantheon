# Client Kit — Seed Interview (the question set)

**Date:** 2026-11-15 · **Author:** Hermes · **Status:** draft for Konan's review — this is the "what questions should we be asking" deliverable
**Consumed by:** Phase 1 of SPEC-CONTRACT.md (the `soul_forge.py` engine), and by the tarball's interview runner.

---

## Design rules

1. **Two layers.** Layer 0 runs *once per install* (the tenant). Layer 1 runs *once per god* (×6). Nothing in Layer 1 asks what Layer 0 already knows.
2. **Identity trio first.** Per your call, each god's interview leads with **name → personality → responsibilities**. Everything else is secondary and skippable.
3. **Describe, don't pick.** Personality is asked open-ended. If the client stalls, *then* offer three drafted voices generated from whatever they did say and let them pick/patch one. Offering a menu first produces averaged-out gods.
4. **Every question names the artifact it feeds.** A question with no destination is a question to cut. (Table at the bottom.)
5. **Unknowns are recorded as unknowns.** Never invent an answer to make the spec look complete — write `❓ open` plus an owner.
6. **The interview is conversational, not a form.** It runs as a god (Hephaestus-style forging engine), so it can follow up: "you said X — does that mean Y?" A 40-field form gets abandoned at field 6.

---

## Layer 0 — Tenant intake (once per install)

| # | Question | Why it's asked / what it feeds |
|---|----------|-------------------------------|
| **T1** | What's the business called, and what does it actually do — in two or three sentences, like you'd say it out loud? | `tenant.json` + the *Shared Context* block in every god's SOUL.md. This is the single fact every god answers from. |
| **T2** | Who talks to the gods? Names, roles, and email/phone. Who is the **approver** for anything that goes out into the world? | Person Roots (`~/athenaeum/Codex-User/relationships/*`), `DISCORD_ALLOWED_USERS` / `TELEGRAM_ALLOWED_USERS`, and the escalation target in every SOUL.md. |
| **T3** | What platform IDs should be granted? (Discord user IDs / Telegram user IDs, per person.) | Allowlist writes. **Ask for these explicitly** — a person without an ID is a person who can't reach a god. |
| **T4** | Timezone, and the hours work actually happens in? | Cron schedules — briefings, digests, and anything that should *not* fire at 3am. |
| **T5** | How should the Pantheon sound when it writes for you? Three adjectives. And what must it **never** sound like? | Rheta + Kairos personas; the *humanizer* tune; brand-voice governance. |
| **T6** | What are the handful of things you'd want solved on day one? (Not a wishlist — the 3–5 real recurring jobs.) | Chooses which gods get the deepest treatment and what their first cron jobs are. Also the honest scoping answer. |
| **T7** | What must they **never** do? (Legal, compliance, brand, "don't ever email a client without asking me".) | Guardrails block in every SOUL.md; review-first gates. |
| **T8** | Where do you want to talk to them — Telegram, Discord, or both? | Platform adoption → gateway config in Phase 3. **Note:** Telegram is the only path where the bots create themselves and set their own avatars; Discord needs one portal click per god. State that trade plainly here. |
| **T9** | Anything the gods should already know how to do? (Existing docs, processes, brand guides, a folder to ingest.) | Codex seeding + ingested knowledge. Drives install-day value instead of a blank slate. |

---

## Layer 1 — Per god (×6) — identity trio first

### A. Identity (asked first, always — this is the primary content)

| # | Question | Feeds |
|---|----------|-------|
| **G1 · Name** | Keep **{Thoth}**, or give it your own name? (Also: emoji + accent color — or we'll pick one that fits.) | `god.json` (`display_name`, `icon`, `color`, `domain`); the bot's platform display name; every UI surface. Default = keep the mythology name. |
| **G2 · Personality** | Describe how this one should come across — two or three sentences in your own words. *(If stuck: "here are three voices drawn from what you said — pick one or edit it.")* | `persona.md` (the `soul_forge.py` engine already produces this from a conversation). Sets voice, warmth, formality, humor. |
| **G3 · Responsibilities** | What are the **3–5 things this god owns** — and what should it **route elsewhere** rather than attempt? | SOUL.md *Domain* + the routing map. The "routes elsewhere" half is what makes the mesh work instead of six gods all doing everything badly. |

### B. Surface + reach (mostly defaulted — confirm, don't interrogate)

| # | Question | Feeds |
|---|----------|-------|
| **G4** | Which channel/topic does it live in? Answer **freely** there, or only when named? | `allowed_channels` / `free_response_channels` (Discord) or `allowed_topics` / `free_response_topics` (Telegram). Default: own lane only, free response. |
| **G5** | Who may it send work to, and who may send work to it? (Default: the whole mesh.) | `PHONEBOOK.json` + Conductor handoff `routing.reply_to_channel`. This is the god→god handoff lane. |
| **G6** | Does it need to reach the outside world — email, calendar, social, a CRM? | MCP server config + credential intake for that god. **Ask before wiring automations**, not after. |

### C. Image

| # | Question | Feeds |
|---|----------|-------|
| **G7** | Want an avatar for its bot? Upload an image, have us generate one from the description in G2, or keep the default totem. | Bot profile photo (`/setuserpic` on Telegram — scriptable; Discord bot avatar at create time — manual). Also the WebUI god card. |

### D. Seed (this is what becomes the starter memory)

| # | Question | Feeds |
|---|----------|-------|
| **G8** | What 3–5 facts should this god already know on day one? | Seeded `MEMORY.md`. The "fresh memory but not amnesiac" requirement. |
| **G9** | Any recurring job you want it to run without being asked? (A daily digest, a weekly check, a Monday brief.) | Cron job creation, with schedule from T4. |
| **G10** | What needs a human's approval before it leaves the building? | Review-first block in SOUL.md. Default for anything external: **yes, always ask**. |

---

## What the seed pass writes at the end

Per install:
- `tenant.json` — T1–T9.
- Person Roots for every human named in T2/T3, with platform IDs in `PERMISSIONS.md` and an index row (the tree validator fails a folder without one).

Per god:
- `SOUL.md` — domain (G3), guardrails (T7 + G10), routing map (G5), Shared Context (T1).
- `persona.md` — voice (G2).
- `god.json` — name/emoji/color/domain (G1).
- `MEMORY.md` — seeded from T1, G3, G5, G8, G9, **plus explicit `❓ open` placeholders** for anything unanswered. Not invented.
- `Codex-God-{name}/INDEX.md` — scaffold with the client's real categories from T6/T9.
- Platform `.env` + `config.yaml` — token, lane, allowlists.

---

## Question → artifact map (the cut list)

If a question isn't on this table, it doesn't get asked.

| Question | Writes to |
|----------|-----------|
| T1 | `tenant.json`, all SOUL.md *Shared Context* |
| T2, T3 | Person Roots, allowlists, escalation target |
| T4 | cron schedules |
| T5 | Rheta/Kairos persona, brand-voice governance |
| T6 | god depth allocation, first cron jobs |
| T7 | guardrails block, review-first gates |
| T8 | platform adoption, gateway config |
| T9 | Codex seeding, ingest queue |
| G1 | `god.json`, platform display name |
| G2 | `persona.md` |
| G3 | SOUL.md *Domain* + routing map |
| G4 | lane config (`allowed_*`, `free_response_*`) |
| G5 | `PHONEBOOK.json`, handoff routing |
| G6 | MCP config + credentials |
| G7 | bot avatar + WebUI card |
| G8 | seeded `MEMORY.md` |
| G9 | cron jobs |
| G10 | review-first block |

**Deliberately not asked:** anything the installer can detect (hardware, model providers, existing keys — `onboarding.py` already probes these), anything the roster already defines (a god's core capability set), and anything that can be defaulted and changed later (thread archive duration, notification cadence).
