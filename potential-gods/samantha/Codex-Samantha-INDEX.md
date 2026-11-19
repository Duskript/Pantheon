# Codex-Samantha — [CLIENT_BUSINESS]

> Living knowledge base for Samantha. Hades-excluded.
> This is the moat: the god is generic, this directory is not.

## Structure

```
Codex-Samantha/
├── INDEX.md            ← this file
├── memory.md           ← active context, open loops, session handoff
├── preferences.md      ← her answers to repeated questions (never re-ask)
├── voice-guide.md      ← how she writes; tone, signoff, banned phrases
├── workflows.md        ← actual inquiry → quote → booked → returned steps
├── travelers/          ← one file per household
├── suppliers/          ← hotels, DMCs, partners: contacts, perks, quirks
├── destinations/       ← destination cheat sheets she already trusts
├── templates/          ← draft skeletons: inquiry reply, quote follow-up, etc.
└── reports/            ← weekly + quarterly business reviews
```

## Seeding checklist (do at deployment, with her in the room)

- [ ] `voice-guide.md` — 20-30 of her sent emails as source. This is the single
      highest-leverage file in the Codex. Without it, drafts sound like an AI.
- [ ] `workflows.md` — walk through one real trip end to end, out loud, recording
      every step. Do not accept "it depends" — get the actual sequence.
- [ ] `preferences.md` — airline, seat, hotel style, meeting length, communication
      channel, signature block, working hours
- [ ] `travelers/` — top 10 active households, one file each
- [ ] `suppliers/` — Fora-preferred properties she actually books, with the perks
      she quotes to clients
- [ ] `destinations/` — anything she already maintains (Google Docs, notes app,
      spreadsheets) gets imported, not rewritten

## traveler file schema

```markdown
# {Household name}
- Travelers: names, ages, relationships
- Home city / airport
- Passport: on file (expiry ref only — never the number)
- Preferences: airline, seat, hotel style, pace, dietary
- History: trips booked, dates, properties, spend band
- Open items: what we owe them, what they owe us
- Notes: anniversaries, kids' names, the thing they always ask for
```

## memory.md schema

```markdown
# Active Memory — updated {date}

## Current focus
## Open loops (owner + due)
## Decisions and why
## Corrections she made (so I don't repeat them)
## Next session should start by
```
