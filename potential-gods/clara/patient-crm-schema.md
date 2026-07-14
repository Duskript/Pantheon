# Patient CRM — Ichor Storage Schema

## Overview

Patient data does NOT live in flat files. It lives in **Ichor** (FTS5 + Graph) so Clara can query it fast, cache it, and update it incrementally. This document defines the schema conventions.

## Ichor FTS5 Keys

### Patient Record
```
key:   patient:{slug}
value: {
  name: "Jane Jones",
  dob: "1975-03-14",
  insurance: {
    payer: "Cigna",
    member_id: "CIG123456789",
    group: "GRP-789",
    plan: "Open Access Plus"
  },
  primary_dx: ["E11.9", "I10"],
  last_visit_date: "2026-03-20",
  notes: ""
}
```

### Medication Record
```
key:   refill:{slug}:{med-slug}
value: {
  med_name: "Eliquis",
  dose: "5mg",
  frequency: "BID",
  days_supply: 30,
  last_refill_date: "2026-05-01",
  next_refill_date: "2026-05-31",   ← auto-calculated
  status: "active",                  ← active | discontinued | on_hold
  prescriber: "Dr. Smith",
  pharmacy: "CVS #4281",
  prior_auth_required: true,
  pa_status: "approved",             ← none | pending | approved | denied
  pa_expiry: "2026-11-30"
}
```

### Prior Auth Log
```
key:   prior-auth:{slug}:{med-slug}:{submitted-date}
value: {
  med_name: "Eliquis",
  payer: "Cigna",
  form_type: "commercial",
  submitted_date: "2026-05-15",
  response_date: "2026-05-22",
  status: "approved",                ← pending | approved | denied | appeal
  denial_reason: "",
  car_codes: "",                     ← Claim Adjustment Reason Codes
  notes: ""
}
```

### Visit Record
```
key:   visit:{slug}:{visit-date}
value: {
  visit_date: "2026-03-20",
  visit_type: "follow-up",           ← new_patient | follow-up | annual | other
  provider: "Dr. Smith",
  notes: ""
}
```

## Auto-Calculated Fields (not stored, computed on read)

| Field | Formula | Alert Threshold |
|-------|---------|-----------------|
| `days_since_last_visit` | `today - max(visit[*].visit_date)` | > 90 days |
| `days_until_refill_due` | `next_refill_date - today` | <= 3 days |
| `refill_overdue` | `today > next_refill_date` | Any overdue |
| `pa_expiring_soon` | `pa_expiry - today` | <= 30 days |

## Ichor Graph Relationships

```
Patient --PRESCRIBED--> Medication
Patient --HAS_INSURANCE--> Payer
Medication --INTERACTS_WITH--> Medication     (cached from interaction API)
PriorAuth --FOR--> Patient
PriorAuth --SUBMITTED_TO--> Payer
PriorAuth --COVERS--> Medication
Visit --OF--> Patient
Visit --WITH--> Provider
```

## Business Rules

### Refill Alert Logic
```
IF days_until_refill_due <= 3 AND days_since_last_visit <= 90:
  → ALERT: "Refill due for {med}. Last visit {days_since_last_visit} days ago — OK to refill."

IF days_until_refill_due <= 3 AND days_since_last_visit > 90:
  → ALERT: "Refill due for {med}. BUT last visit was {days_since_last_visit} days ago — needs appointment first."

IF refill_overdue AND days_since_last_visit > 90:
  → ALERT: "Refill OVERDUE by {days}. Patient needs appointment — last seen {days_since_last_visit} days ago."
```

### Prior Auth Refresh Logic
```
IF pa_expiry <= 30 days AND status == "approved":
  → ALERT: "{med} PA expires in {days} days. Start renewal process."

IF pa_status == "pending" AND submitted_date + 7 days < today:
  → ALERT: "{med} PA submitted {days_ago} days ago — no response. Follow up?"
```

### Interaction Check Trigger
```
Trigger: Before every PA submission OR manual "check interactions" request
Action: Gather all active meds for patient → send to interaction API → cache result
Output: List flagged pairs with severity → present to med manager
```
