# Codex-PriorAuth INDEX.md
# ───────────────────────────────────────────────────────────────────
# This Codex holds all prior authorization knowledge for Clara.
# It is the reference she reaches for when filling forms.
#
# Structure:
#   payers/       — Per-payer requirements, form links, contact info
#   medications/  — Per-medication criteria (by class or specific drug)
#   templates/    — Form templates and field mappings
#   guides/       — General guidance documents (the criteria doc lives here)

## Quick Structure

```
Codex-PriorAuth/
├── INDEX.md                    ← this file
├── guides/
│   ├── approval-criteria.md    ← THE master criteria doc (from client)
│   ├── payer-contact-info.md   ← phone, fax, portal URLs for each payer
│   └── common-denial-reasons.md
├── payers/
│   ├── medicaid/
│   │   ├── index.md            ← general Medicaid rules for this state
│   │   ├── form-templates.md   ← form field mapping
│   │   └── criteria.md         ← state-specific Medicaid criteria
│   ├── medicare/
│   │   ├── index.md
│   │   └── criteria.md
│   ├── cigna/
│   │   └── criteria.md
│   ├── priority-health/
│   │   └── criteria.md
│   └── blue-cross-blue-shield/
│       └── criteria.md
├── medications/
│   ├── glp1-agonists.md        ← Ozempic, Mounjaro, Wegovy, etc.
│   ├── stimulants.md           ← Adderall, Vyvanse, etc.
│   ├── specialty-biologics.md  ← Humira, Stelara, etc.
│   └── controlled-substances.md
└── templates/
    ├── covermymeds-field-map.md
    └── state-specific-forms/
        └── [state]-pa-form-fields.md
```

## Ingestion Process

1. Place the client's approval criteria document(s) at `guides/approval-criteria.md`
2. Clara reads this on first session and indexes by payer + medication category
3. For each new medication encountered, Clara writes a reference entry to the appropriate file
4. Field mappings are learned through use — Clara observes form fields and documents them in `templates/`
