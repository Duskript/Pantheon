# Codex-PriorAuth INDEX.md
# ───────────────────────────────────────────────────────────────────
# This Codex holds all prior authorization knowledge for Clara.
# It is the reference she reaches for when filling forms, checking
# interactions, and tracking patients.
#
# Structure:
#   payers/       — Per-payer requirements, form links, contact info, FHIR endpoints
#   medications/  — Per-medication criteria (by class or specific drug)
#   interactions/ — Drug-drug interaction data cache
#   templates/    — Form templates, field mappings, saved copy-paste language
#   guides/       — General guidance documents (the criteria doc lives here)
#   patient-crm/  — Storage schema and business rules

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
│   │   ├── criteria.md         ← state-specific Medicaid criteria
│   │   └── fhir-endpoint.md    ← CMS-0057-F FHIR PA API if available
│   ├── medicare/
│   │   ├── index.md
│   │   ├── criteria.md
│   │   └── fhir-endpoint.md
│   ├── cigna/
│   │   ├── criteria.md
│   │   └── fhir-endpoint.md
│   ├── priority-health/
│   │   └── criteria.md
│   └── blue-cross-blue-shield/
│       └── criteria.md
├── medications/
│   ├── glp1-agonists.md        ← Ozempic, Mounjaro, Wegovy, etc.
│   ├── stimulants.md           ← Adderall, Vyvanse, etc.
│   ├── specialty-biologics.md  ← Humira, Stelara, etc.
│   └── controlled-substances.md
├── interactions/
│   ├── known-pairs.md          ← Cached drug-drug interaction results
│   └── interaction-api-config.md ← OpenFDA / DrugsAPI endpoint config
├── templates/
│   ├── covermymeds-field-map.md
│   ├── saved-phrases/          ← MED MANAGER'S COPY-PASTE LANGUAGE
│   │   ├── clinical-justification.md
│   │   ├── appeal-letter-openers.md
│   │   ├── formulary-exception.md
│   │   ├── denial-overturn.md
│   │   └── general-letters.md
│   ├── prior-auth-forms/
│   │   ├── uhc-commercial-template.md
│   │   ├── cigna-specialty-template.md
│   │   └── medicaid-template.md
│   └── state-specific-forms/
│       └── [state]-pa-form-fields.md
└── patient-crm/
    ├── schema.md               ← Ichor storage schema for patients, meds, visits
    └── refill-alert-rules.md   ← Business rules for refill timing & visit recency
```

## Ingestion Process

1. **Criteria doc:** Place the client's approval criteria document(s) at `guides/approval-criteria.md`
2. **Saved phrases:** Ingest the med manager's copy-paste language into `templates/saved-phrases/` — organized by use case. These are her voice; Clara should default to them before generating original text.
3. **Payer FHIR endpoints:** As payers activate CMS-0057-F PA APIs, document the endpoint URL, auth method, and FHIR resource requirements in each payer's `fhir-endpoint.md`
4. **Interaction data:** Drug interaction pairs are cached in `interactions/known-pairs.md` to reduce API calls. Periodic refresh as needed.
5. **Patient CRM:** Schema is defined in `patient-crm/schema.md`. Actual patient data lives in Ichor, not in flat files.

## Data Sources

| Data | Source | Cost |
|------|--------|------|
| Drug interactions (prototype) | OpenFDA `/drug/label` endpoint | Free |
| Drug interactions (production) | DrugsAPI or DrugBank | ~$99+/mo or enterprise |
| Claims submission (Phase 2) | Stedi JSON API (clearinghouse) | Per-transaction |
| Prior Auth API (Phase 2) | CMS-0057-F FHIR endpoints per payer | Free (mandated) |
| Patient CRM | Ichor (FTS5 + Graph) | — |
