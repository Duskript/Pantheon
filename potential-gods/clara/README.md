# potential-gods/clara/

Working directory for Clara (potential god, not yet activated).

## What Clara Does

A medical practice operations god purpose-built for **Lisa Miller** (solo med manager). Clara handles:

### Phase 1 — MVP (Current)
| Capability | Status | Backend |
|---|---|---|
| Email triage (Gmail) | Built in SOUL.md | Google Workspace MCP |
| Prior auth pre-fill & form filling | Built in SOUL.md | Browser automation + portal |
| 15-day renewal tracking | Built in SOUL.md | Cron + Ichor |
| Prior auth status tracking | Built in SOUL.md | Ichor FTS5 |
| Patient outreach tracking | Built in SOUL.md | Ichor FTS5 |

### Phase 1.1 — Added 2026-06-29
| Capability | Added | Details |
|---|---|---|
| Drug interaction checking | ✅ New | OpenFDA (prototype) → DrugsAPI (production) |
| Refill date auto-calculation | ✅ New | days_supply math → Ichor |
| Client visit recency tracking | ✅ New | Auto-flag >90 days since last visit |
| Saved copy-paste template ingestion | ✅ New | Her language → Codex-PriorAuth/templates/saved-phrases/ |
| Patient CRM schema | ✅ New | Ichor FTS5 + Graph (see patient-crm-schema.md) |

### Phase 2 — Planned
| Capability | Details |
|---|---|
| CMS-0057-F FHIR Prior Auth API | Electronic PA submission via payer APIs |
| Claim submission (insurance billing) | Stedi or Office Ally clearinghouse |

## Files

| File | Description |
|---|---|
| `SOUL.md` | Clara's identity, domain, capabilities, protocols |
| `persona.md` | Clara's voice, speech patterns, character |
| `god.json` | Pantheon god registry entry |
| `config.yaml.template` | Hermes profile config template |
| `Codex-PriorAuth-INDEX.md` | Domain knowledge base structure |
| `patient-crm-schema.md` | Ichor storage schema for patients/meds/visits |
| `interaction-api-config.md` | Drug interaction API configuration |
| `provision-clara.sh` | Provisioning script (legacy) |

## When Clara Is Summoned

Her profile will live at `~/.hermes/profiles/clara/`.

### Setup Checklist
1. [ ] Run `sudo ./provision-clara.sh lisa-miller <gmail>` to create the profile
2. [ ] Set up Google Workspace MCP credentials (Gmail read/modify, Calendar)
3. [ ] Ingest Lisa's approval criteria doc → `Codex-PriorAuth/guides/approval-criteria.md`
4. [ ] Ingest Lisa's saved copy-paste language → `Codex-PriorAuth/templates/saved-phrases/`
5. [ ] Configure drug interaction API (start with OpenFDA, upgrade to DrugsAPI)
6. [ ] Import initial patient list → Ichor patient records
7. [ ] Set up cron jobs: inbox scan (8AM), refill check (10AM), weekly briefing (Fri 4PM)
8. [ ] Walk through 3 real prior auths together as pilot
