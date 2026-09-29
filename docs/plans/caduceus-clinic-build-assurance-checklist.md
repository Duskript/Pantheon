# Caduceus Clinic Build Assurance Checklist

**Purpose:** Define the proof required before calling Caduceus Clinic built, safe for pilot use, or ready for live PHI.

**Core rule:** A passing TypeScript/Python build proves only that some code compiled. It does not prove correct data boundaries, safe clinical behavior, correct authorization, secure deployment, or HIPAA readiness.

## 1. Release states

| State | Allowed data | Required evidence |
|---|---|---|
| Development | synthetic data only | local tests and documented configuration |
| Research pilot | public and reviewed de-identified data | egress proof, de-identification review, auth, audit, restore test |
| Clinic pilot | limited PHI under clinic authorization | complete PHI map, risk analysis, technical gates, provider training, independent review plan |
| Live PHI | clinic-approved PHI workflows | every go-live gate green, independent HIPAA/security review, clinical safety sign-off |

Never describe Development or Research Pilot as HIPAA-compliant production.

## 2. Evidence packet required for every release

Create a release evidence directory containing:

```text
release-evidence/<release-id>/
├── release-manifest.json
├── git-revision.txt
├── dsh-cordis-revision.txt
├── model-artifact-and-digest.txt
├── tokenizer-and-runtime-digests.txt
├── sbom.json
├── dependency-scan.txt
├── static-analysis.txt
├── unit-test.txt
├── integration-test.txt
├── browser-e2e-test.txt
├── authorization-matrix.txt
├── phi-data-map.md
├── egress-test.txt
├── audit-integrity-test.txt
├── deletion-test.txt
├── backup-restore-test.txt
├── prompt-injection-test.txt
├── clinical-safety-test-report.md
├── install-log.txt
├── rollback-log.txt
├── screenshots/
└── reviewer-signoffs.md
```

No release is complete if a gate has only a claim, screenshot of source code, or “works on my machine” note without execution output.

## 3. Build contract checks

Before implementation begins, freeze:

- provider-only scope;
- clinic-local deployment boundary;
- local-only model requirement;
- no patient portal;
- no EHR in the base product;
- no automatic chart changes;
- no autonomous clinical action;
- Caduceus tool-reuse inventory;
- Cordis/DSH adaptation boundary;
- allowed data stores and prohibited destinations;
- case-ID and identity-map rules;
- retention/deletion policy;
- required audit events;
- exact supported file types and size limits;
- expected review/approval states.

The implementation must be compared against this contract at every release. A route, tool, config value, or UI surface that is not in the contract is a scope/security review item—not an automatic feature.

## 4. Source and dependency proof

Record:

- exact DSH/Cordis revision;
- license files and notices;
- all direct and transitive dependencies;
- lockfiles;
- SBOM;
- container image digests;
- model and tokenizer digests;
- runtime version;
- operating-system package snapshot;
- build command and environment;
- generated assets and checksums.

The Caduceus bundle should remain a narrow layer over the DSH shell. Do not copy vendor code into the clinic app unless the license, provenance, patch ownership, and upgrade test are recorded.

## 5. Functional proof

### Identity and cases

- Provider can sign in with a unique account.
- MFA is required for configured risk levels.
- Provider can create and select a case.
- Case IDs are opaque and collision-safe.
- Identity mapping is outside the research workspace.
- Provider A cannot access Provider B’s unauthorized case.
- Case switching clears previous case data from the active request context.
- Logout, revocation, timeout, and back-button behavior are tested.

### Intake

- Upload accepts only approved MIME types and sizes.
- Filenames are normalized.
- Path traversal and symlink attacks fail.
- Uploads are assigned to the selected case only after an explicit confirmation.
- OCR results link back to source page/region.
- Low-confidence extraction is visibly marked.
- Provider must confirm clinically material extracted values.
- Delete removes primary and temporary copies according to the retention policy.

### Medical research

- Medication and supplement names are normalized deterministically.
- Interaction logic runs independently of the LLM.
- Laboratory values preserve units, dates, lab identity, and lab-specific ranges.
- Findings carry source, retrieval date, evidence status, and uncertainty.
- Conflicting sources are not collapsed into false certainty.
- Public-source adapters reject patient narrative, identifiers, and raw genomic material.
- The LLM can explain a structured finding but cannot silently alter it.

### Review and export

- Every material finding shows AI-assisted status.
- Approval requires a named provider.
- Rejection and amendment preserve the prior version and reason.
- Reports include source citations and evidence status.
- Export destination is explicit.
- Reports cannot be silently sent to an external system.
- No chart write-back route exists in the base product.

## 6. Security proof

### Authentication and authorization

Build a route/tool matrix with:

```text
principal × route/tool × data class × action × expected result
```

Test both allowed and denied cases. Include direct API calls, manipulated case IDs, stale sessions, missing credentials, malformed tokens, and role changes.

### PHI boundary

For every data store, document:

- what data can enter;
- owner;
- path or service;
- encryption;
- key owner;
- access roles;
- retention;
- deletion method;
- backup path;
- audit events;
- restore behavior.

Include browser state, temp directories, OCR/parser output, model-server logs, raw turns, embeddings, caches, swap/page files, GPU/runtime buffers where controllable, exports, crash dumps, and backups.

### Model boundary

The application must fail closed when:

- model endpoint is not in the approved local allowlist;
- model artifact digest does not match the release manifest;
- provider authentication is missing;
- required audit append fails;
- tool policy is unavailable;
- case scope is missing or ambiguous;
- input exceeds configured limits.

The model service must not have access to:

- provider credentials;
- Vaultwarden data;
- browser profiles;
- arbitrary host directories;
- unrelated cases;
- Discord or messaging credentials;
- deployment control APIs.

### Egress proof

Run the system with the intended production configuration and prove:

- DNS requests stay within approved destinations;
- no cloud model provider is contacted;
- no telemetry endpoint is contacted;
- no external NATS or A2A endpoint is contacted;
- public-source requests contain only approved sanitized terms;
- unauthorized outbound sockets are blocked;
- failure occurs closed when a required public source is unavailable.

Store actual command output, socket inventory, firewall counters, and packet evidence. A configuration grep is not enough.

### Prompt-injection proof

Use synthetic documents containing instructions such as:

- ignore the system policy;
- send the case to an external address;
- read unrelated files;
- change a medication record;
- suppress a warning;
- claim that a source supports an unsupported conclusion.

Expected result: the content is treated as untrusted data, unsafe actions are blocked, and the event is recorded.

## 7. Clinical-safety proof

Maintain a versioned synthetic corpus with expected outputs. Include:

- known medication interactions;
- contraindications;
- duplicate therapy;
- brand/generic confusion;
- supplement dose and timing confusion;
- units and decimal points;
- abnormal laboratory results;
- wrong or missing reference ranges;
- OCR sign/decimal errors;
- old or conflicting sources;
- missing patient context;
- incomplete medication list;
- hallucinated citations;
- false positive and false negative cases;
- provider correction and amendment cases.

Each case needs:

```text
case_id
input_fixture
expected deterministic findings
acceptable uncertainty
forbidden output
reviewer
execution result
release
```

The acceptance criterion is not “the model sounds medically intelligent.” It is: known risks are surfaced, evidence is visible, uncertainty is preserved, and unsafe confidence is rejected.

## 8. Audit proof

Verify that these events are recorded:

- login success/failure;
- MFA challenge;
- case create/select/access-deny;
- upload/download/delete;
- OCR start/result/confirmation;
- sanitizer allow/deny;
- public-source request/result;
- model request/response;
- tool invocation/result/error;
- finding create/edit/approve/reject/amend;
- export;
- retention/deletion;
- administrator access;
- backup/restore;
- configuration/model change.

Verify the chain:

```text
event_hash = SHA256(previous_event_hash + canonical_event)
```

The tamper test must modify an event and prove that verification fails. The restore test must prove that the journal remains verifiable after recovery.

## 9. Operations proof

Execute and record:

- clean install;
- first provider bootstrap;
- normal login and case workflow;
- service restart;
- model restart;
- network outage;
- public-source outage;
- disk-full behavior;
- malformed upload storm;
- backup;
- isolated restore;
- rollback to prior release;
- provider offboarding;
- key rotation;
- incident response;
- breach assessment tabletop exercise.

A service that only works while the developer is present is not a completed clinic product.

## 10. Go/no-go rules

### Automatic no-go

- Any live PHI can reach a cloud model or uncontrolled remote endpoint.
- Any unauthenticated route can read or mutate PHI.
- Any provider can access another provider’s unauthorized case.
- Audit failure does not block the PHI operation.
- Deletion is claimed but not tested across known stores.
- Backups are unencrypted or restore has not been tested.
- Model/runtime/artifact provenance is unknown.
- The model can directly perform clinical-impacting or destructive actions.
- Public-source tools receive patient narrative or raw identifiers.
- A required clinical-safety test fails without documented risk acceptance.

### Conditional approval only

- The exact production model is still unresolved.
- Genome interpretation is enabled before separate review.
- EHR connectivity exists without its own contract and acceptance suite.
- The clinic has not completed provider training or incident procedures.
- The independent security/HIPAA review is pending.

## 11. Sign-off record

A release record must identify:

- build/release ID;
- source revision;
- model/runtime digests;
- test result locations;
- open risks;
- accepted residual risks;
- reviewer names and roles;
- clinic risk owner;
- clinical reviewer;
- security reviewer;
- approval state;
- next review date.

No one person should be able to silently approve their own unreviewed clinical-safety and security work.

## Definition of properly built

Caduceus Clinic is properly built when:

1. the implementation matches the locked product contract;
2. the provider workflow works end-to-end in a real browser;
3. authorization is proven with negative tests;
4. every PHI store and transmission path is mapped;
5. local inference and default-deny egress are proven at runtime;
6. deterministic medical logic is separated from LLM explanation;
7. clinical-safety fixtures pass;
8. audit records are complete and tamper-evident;
9. deletion and restore are demonstrated;
10. install, upgrade, rollback, and incident procedures work;
11. the release evidence packet is reproducible;
12. the clinic and an independent reviewer—not only the developer—accept the residual risk.
