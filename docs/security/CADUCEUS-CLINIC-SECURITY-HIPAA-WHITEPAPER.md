# Caduceus Clinic Security and HIPAA Readiness White Paper

**Review date:** 2026-08-26  
**Product:** Caduceus Clinic  
**Assessment type:** Engineering, architecture, and operational-readiness review. This is not a penetration test, HIPAA certification, legal opinion, medical-device determination, or substitute for independent counsel/security review.

## Executive decision

### Current status: **FAIL for live PHI**

The proposed Caduceus Clinic design is a reasonable foundation for a provider-only, clinic-local medical research assistant, but it is **not currently ready to process live patient data**. The system should be treated as **HIPAA-sensitive research infrastructure** until the controls and clinic operating program described here are implemented and independently reviewed.

### Conditional status

The design can be conditionally used for public-source research and carefully governed de-identified research only after the deployment proves:

- no cloud or uncontrolled remote model route;
- no PHI in Discord, external NATS, broad A2A, or uncontrolled webhooks;
- mandatory authentication and authorization;
- complete data-flow and retention mapping;
- local encrypted storage;
- restricted tools and default-deny egress;
- testable deletion and backup-restore procedures;
- human review of de-identification;
- synthetic-data safety testing;
- evidence that prompts, tool results, logs, caches, and backups stay inside the approved boundary.

### What this means in plain English

Self-hosting the model is helpful, but it does not make the application HIPAA compliant. HHS describes the Security Rule as requiring administrative, physical, and technical safeguards, including risk analysis, access control, incident response, contingency planning, audit controls, authentication, and transmission security.[15] HHS also states that risk analysis covers all ePHI the organization creates, receives, maintains, or transmits—not merely the final database.[16]

The clinic, not the software author, must own the risk analysis, policies, workforce procedures, incident response, breach decisions, contracts, physical safeguards, and final go-live decision.

## 1. Product boundary under review

### Included

Caduceus Clinic is a provider-only research and clinical decision-support workspace:

- providers sign in;
- providers create or select an opaque case ID;
- providers manually enter or upload medication, supplement, laboratory, history, and research material;
- the system performs structured extraction and source-backed research;
- the local model explains and organizes findings;
- a provider reviews, edits, approves, rejects, or amends findings;
- the provider exports a reviewed report locally;
- every material operation is auditable.

The base product does not write to an EHR, message a patient, schedule care, prescribe, diagnose autonomously, or change a chart.

### Excluded from the base product

- patient portal or patient accounts;
- patient messaging;
- autonomous treatment decisions;
- autonomous medication changes or scheduling;
- EHR, FHIR, SMART, HL7, or vendor-specific integration;
- automatic chart write-back;
- Discord as a PHI channel;
- cloud inference or cloud fallback;
- unrestricted browser automation;
- unrestricted shell, filesystem, or MCP access.

EHR connectivity is a separately scoped paid custom project. It needs its own vendor/API review, security assessment, testing, contracts, and maintenance boundary.

## 2. Clinical and regulatory posture

Caduceus should be positioned as a **provider research assistant with human review**, not as an autonomous clinician.

The model may:

- organize supplied information;
- summarize source material;
- identify possible questions for provider review;
- connect findings to citations;
- explain why a deterministic rule or source may matter;
- show uncertainty, missing context, and conflicting evidence.

The model must not be the sole medication-interaction engine, reference-range engine, diagnosis engine, or treatment-authority engine. Deterministic source-backed logic must produce structured findings first; the language model may explain those findings but must not silently invent or override them.

The FDA’s current CDS materials say that determining whether a software function is regulated requires function-by-function analysis, and that the CDS guidance should not be the sole reference.[25] The Caduceus classification therefore remains unresolved until the exact product functions, claims, intended use, labeling, and workflow are reviewed by a qualified regulatory specialist.

The safe product claim is:

> “Caduceus Clinic helps healthcare professionals organize local case information, research medical evidence, and review cited findings. It does not make autonomous clinical decisions.”

That claim reduces risk; it does not eliminate it.

## 3. PHI and de-identification position

A case ID such as `CASE-2026-00184` is an opaque identifier and a useful minimization control. It is **not automatically anonymization**. If the clinic can map that case back to a person, the associated health information remains sensitive in the clinic environment.

HHS recognizes two formal HIPAA de-identification methods: **Safe Harbor** and **Expert Determination**.[21] A provider-held mapping must be kept in a separate, more restricted identity vault. The Caduceus workspace must not contain names, dates of birth, addresses, phone numbers, email addresses, medical-record numbers, or raw identity mappings unless the specific clinic workflow requires them.

A de-identification preview is not a legal guarantee. The application must:

1. show what identifiers it detected;
2. show what it removed or transformed;
3. show what it could not confidently classify;
4. require provider confirmation;
5. retain the de-identification method and reviewer;
6. prevent export into research mode until the review is complete;
7. keep the re-identification key outside the research workspace.

HHS specifically warns that disclosure of a code intended to enable re-identification is a disclosure of PHI.[21] Therefore, case-ID generation, mapping, lookup, export, and destruction must all be access-controlled and audited.

## 4. Trust zones and data flow

```text
┌────────────────────────────────────────────────────────────┐
│ Clinic trust zone                                          │
│                                                            │
│ Provider browser                                           │
│   │ HTTPS + MFA + session controls                         │
│   ▼                                                        │
│ Caduceus Clinic WebUI/API                                  │
│   │                                                        │
│   ├── Case Registry                                         │
│   ├── Encrypted PHI Vault                                   │
│   ├── Audit Journal                                         │
│   ├── OCR / parser sandbox                                  │
│   ├── Deterministic clinical rule services                 │
│   ├── Sanitized public-source adapter                      │
│   └── Provider review/export service                        │
│                                                            │
│   └── authenticated loopback/private link                  │
│          ▼                                                 │
│      Local model server                                    │
│      no access to raw host state or credentials             │
└────────────────────────────────────────────────────────────┘

Approved public-source egress, if enabled:
  sanitizer → medication/variant/source query only → approved source

Prohibited PHI destinations:
  cloud model providers, Discord, external NATS, arbitrary webhooks,
  uncontrolled MCP servers, third-party telemetry, browser profiles,
  unmanaged backups, crash collectors, and support bundles.
```

### Tool classes

| Class | Examples | Policy |
|---|---|---|
| Safe local | case DB, encrypted files, OCR, deterministic rules, audit journal | allowed only with case/user scope and audit event |
| Sanitized public research | FDA, DailyMed, RxNorm, RxClass, PubMed, ClinicalTrials.gov, NIH ODS | receive only minimized terms such as a medication or variant; never patient narrative or raw genome |
| Restricted | browser automation, shell, arbitrary filesystem, general MCP, messaging, external webhooks | disabled in clinic mode unless separately approved and sandboxed |

A query such as `Medication: lisinopril` may be acceptable for a public source. A complete patient history containing the medication is not an acceptable public-source payload.

## 5. Current high-risk findings

### CRITICAL — No live-PHI approval exists

There is no verified clinic risk analysis, PHI inventory, retention schedule, access-review record, breach procedure, workforce training record, backup-restore evidence, or independent review package. This alone blocks production PHI use. HHS identifies risk analysis as the first step and includes all ePHI created, received, maintained, or transmitted.[16]

**Fix:** create the clinic operating program before onboarding real patients.

### CRITICAL — Existing Pantheon routes are broader than a clinic PHI boundary

The current Pantheon review identified cloud/remote provider routes, external NATS, optional WebUI authentication, fail-open Conductor/webhook behavior, shared A2A credentials, Discord availability, and raw-turn persistence. Those are unacceptable assumptions for a clinic PHI path.

**Fix:** create a separate clinic profile/deployment with local-only inference, no Discord, no external event bus, mandatory auth, unique identities, isolated storage, and startup failures for unsafe configuration.

### CRITICAL — PHI lifecycle is larger than the case database

Potential PHI locations include:

- browser request and response bodies;
- uploads and OCR temporary files;
- parser error logs;
- prompts and model responses;
- model-server request logs and caches;
- tool calls and tool results;
- generated reports and exports;
- audit metadata and encrypted payload references;
- raw-turn/session databases;
- embeddings and search indexes;
- swap/page files;
- crash dumps and diagnostic bundles;
- backups and removable media;
- browser storage and downloads;
- GPU memory and runtime KV caches;
- developer test fixtures and screenshots.

**Fix:** build a data inventory with owner, location, retention, encryption, access role, deletion procedure, backup path, and verification evidence for every store.

### CRITICAL — A local model can still disclose PHI

Local inference blocks one cloud-provider path. It does not stop:

- malicious documents from injecting instructions;
- a model from attempting an unsafe tool call;
- a plugin or MCP server from exfiltrating data;
- a compromised runtime or model artifact from reading data;
- a local administrator or stolen backup from accessing data;
- logs and temporary files from retaining prompts;
- a provider from copying a report to an unmanaged device.

**Fix:** isolate the model, restrict tools, enforce egress, log model-visible data, and test malicious documents and prompt injection.

### HIGH — Caduceus tools need a clinic-safe adapter

Existing medical research capability should be reused, not duplicated. But every tool must be reviewed for where it sends data, what it stores, whether it follows redirects, what credentials it uses, and whether its result is deterministic and cited.

**Fix:** expose only typed clinic-safe adapters. The adapter must reject raw patient history, names, DOBs, addresses, narratives, and raw genomic files for public-source requests.

### HIGH — OCR and laboratory analysis can produce clinically dangerous errors

OCR can confuse decimal points, units, analyte names, dates, reference ranges, and negative signs. Laboratory ranges vary by lab, method, age, sex, and collection context. An apparently abnormal value may be a parsing error or an inapplicable reference range.

**Fix:** show source image/PDF beside extracted values, require provider confirmation for uncertain fields, preserve units and collection dates, retain the laboratory’s own range, and fail closed when required context is missing.

### HIGH — Medication safety cannot be delegated to the language model

The model may miss contraindications, misunderstand timing, confuse brand/generic names, fail to distinguish supplement strength, or produce a plausible but unsupported interaction. A citation does not prove that the conclusion is correct for the patient.

**Fix:** build deterministic medication normalization and interaction logic first. The model only explains structured results and must distinguish “source says,” “rule indicates,” and “provider review required.”

### HIGH — Genomic data has elevated re-identification and interpretation risk

Genomic files can be identifying, family-linked, and difficult to de-identify. Pathogenicity and clinical actionability are different questions. Evidence may conflict or be population/context dependent.

**Fix:** defer genome interpretation until the base system is stable; isolate the module; require stronger access control; display evidence conflicts; never provide autonomous treatment instructions; require specialist escalation.

### HIGH — DSH-style auditability is necessary but not sufficient

An append-only, hash-chained journal improves accountability, but it does not make the system HIPAA compliant. Audit data can itself contain PHI, and a hash chain does not stop an authorized user from entering incorrect information.

**Fix:** log every material event, store sensitive payloads separately, restrict journal access, test tamper detection, and connect the audit record to provider review and correction workflows.

### HIGH — Cordis/DSH supply-chain and fork risk

Cordis gives Caduceus a strong existing WebUI foundation, but adapting open-source code introduces dependency, patch, license, build-reproducibility, and upstream-change risks.

**Fix:** pin the DSH/Cordis revision, record licenses, generate an SBOM, scan dependencies, preserve an upstream remote, keep Caduceus changes in a dedicated bundle/plugin layer, and test every upstream upgrade against clinic acceptance tests.

### HIGH — Backups can silently defeat deletion

Deleting a case from the primary database does not prove deletion from snapshots, WAL files, object storage, encrypted backup sets, exports, or support bundles.

**Fix:** define retention and legal-hold behavior, document backup expiry, encrypt backups, separate keys, test restore, and prove how deletion propagates or how retained copies are controlled.

### MEDIUM — Availability and recovery risk

A clinic-local appliance can fail from power loss, filesystem corruption, model/runtime upgrades, overheating, disk failure, or a broken package update.

**Fix:** UPS-backed operation, tested backups, documented emergency mode, rollback artifacts, health checks, resource quotas, and a recovery runbook that does not require sending PHI to the developer.

### MEDIUM — Human workflow risk

Providers may over-trust fluent output, copy findings into a chart without review, upload the wrong case, or export a report to an unmanaged location.

**Fix:** clear AI-assisted labels, case confirmation before upload, side-by-side citations, mandatory approval for clinical findings, export warnings, provider training, and periodic access/output review.

## 6. HIPAA safeguard readiness

### Administrative safeguards — currently incomplete

Required clinic controls:

- designated security/privacy responsibility;
- accurate risk analysis and risk-management plan;
- PHI/ePHI data map;
- workforce authorization and training;
- sanctions and acceptable-use policy;
- minimum-necessary access rules;
- incident and breach-response procedure;
- contingency and emergency-mode procedure;
- periodic technical and non-technical evaluation;
- vendor/business-associate register;
- written business-associate agreements where applicable;
- change control and release approval;
- retention and secure-disposal policy.

HHS places responsibility for risk management, incident documentation, contingency planning, evaluation, and business-associate arrangements in the Security Rule safeguards.[15]

### Physical safeguards — deployment-dependent

Required evidence:

- M5 located in a controlled clinic area;
- locked or access-controlled room/cabinet;
- screen-lock policy;
- full-disk encryption with recovery-key custody;
- secure boot and firmware update process;
- protected removable media;
- controlled disposal and re-use procedure;
- UPS and graceful shutdown;
- encrypted off-device backup storage;
- asset inventory and tamper inspection.

The software cannot verify all physical safeguards. The clinic must provide the evidence.

### Technical safeguards — implementation gates

Required controls:

- unique provider identities;
- MFA for administrative and PHI access;
- role-based case authorization;
- session expiration and revocation;
- CSRF and origin protection;
- TLS for browser and cross-host links;
- encryption at rest and managed key lifecycle;
- audit controls with tamper detection;
- input/body-size limits and rate limits;
- path containment and safe file names;
- parser/OCR sandboxing;
- local-only model endpoint;
- tool allowlist and least-privilege credentials;
- default-deny egress;
- authenticated webhooks with replay protection;
- protected logs and crash handling;
- backup encryption and restore testing.

## 7. Build assurance: how to know it is properly built

A green build is necessary but nowhere near sufficient. Every wave must produce four kinds of proof:

1. **Contract proof:** the implementation matches the written specification.
2. **Behavior proof:** unit, integration, and end-to-end tests pass.
3. **Security proof:** unsafe routes, egress, access, storage, and tool paths fail as designed.
4. **Operational proof:** install, upgrade, backup, restore, rollback, and incident procedures work on the target deployment.

### Wave 0 — Scope, threat model, and build contract

Deliver:

- locked product boundary;
- explicit non-goals;
- data classification;
- PHI data-flow diagram;
- threat model;
- tool inventory;
- model identity record;
- regulatory questions register;
- DSH/Cordis adaptation decision;
- repository and DOX/AGENTS contracts.

Gate:

- no unresolved requirement can change the PHI boundary silently;
- exact model artifact is identified or explicitly blocked;
- every external connector has a destination and data-policy record.

### Wave 1 — Cordis shell and clinic profile

Deliver:

- pinned DSH/Cordis revision;
- Caduceus Clinic bundle/plugin;
- provider-only routing;
- clinic-mode guard;
- local-only provider selection;
- no patient-facing routes;
- no Discord route;
- no cloud fallback;
- error boundary and safe loading states.

Gate:

- clinic mode refuses unsafe configuration at startup;
- a browser can authenticate and reach only clinic-approved surfaces;
- a static route inventory shows no patient portal or chart-write endpoint.

### Wave 2 — Identity, case registry, and authorization

Deliver:

- unique provider accounts;
- MFA;
- roles;
- case-level authorization;
- opaque case IDs;
- separate identity map;
- session revocation;
- access review events.

Gate:

- provider A cannot read provider B’s unauthorized case;
- revoked sessions fail immediately or within the documented bound;
- changing a URL, case ID, or API payload cannot cross the authorization boundary;
- every allow/deny decision is logged.

### Wave 3 — Encrypted intake and PHI vault

Deliver:

- PDF/image/CSV upload;
- MIME and size validation;
- encrypted storage;
- OCR/parser sandbox;
- temporary-file cleanup;
- source-document provenance;
- de-identification preview;
- provider confirmation.

Gate:

- malicious filenames and paths cannot escape the case vault;
- malformed PDFs/images/CSVs cannot execute code or exhaust the service;
- rejected uploads leave no recoverable temporary copy;
- extracted values link to source pages/regions;
- uncertain OCR fields are visibly marked.

### Wave 4 — Deterministic medical research adapters

Deliver:

- medication normalization;
- supplement normalization;
- interaction rules;
- timing/reconciliation structures;
- lab normalization and trend model;
- source hierarchy;
- citations and evidence status;
- sanitized public-source adapter.

Gate:

- public adapters reject patient narrative and raw identifiers;
- known synthetic interaction cases produce expected findings;
- conflicting or missing evidence is displayed as uncertainty;
- the LLM cannot mutate deterministic findings.

### Wave 5 — Local model integration

Deliver:

- pinned model/tokenizer/runtime;
- authenticated local endpoint;
- prompt envelope with case scope;
- model-visible-data audit event;
- context and payload limits;
- resource quotas;
- inference timeout/cancellation;
- safe failure behavior.

Gate:

- the application fails closed if the endpoint is remote or unauthorized;
- model requests contain only the approved case scope;
- model server cannot read application secrets or arbitrary host paths;
- canary tests show no unauthorized DNS/socket/HTTP egress.

### Wave 6 — Review, approval, and reports

Deliver:

- finding cards;
- source/citation panel;
- AI-assisted label;
- provider approve/reject/edit/amend flow;
- report export;
- export destination warning;
- report versioning.

Gate:

- no finding appears as provider-approved without an identified reviewer;
- edits preserve the prior version and reason;
- exports show source dates, evidence status, AI-assistance label, and reviewer state;
- provider can distinguish source evidence from model explanation.

### Wave 7 — DSH-style audit journal

Deliver:

- append-only event schema;
- chained event hashes;
- encrypted payload references;
- journal verification command;
- audit search by case/provider/run;
- tamper detection;
- retention controls.

Recommended event fields:

```text
event_id
session_id
run_id
actor_id
workspace_id
case_id
patient_scope
timestamp
event_type
model_id
model_digest
tool_id
approval_state
payload_digest
encrypted_payload_reference
previous_event_hash
event_hash
```

Gate:

- a model request, tool call, tool result, approval, export, deletion, and access denial each generate the required event;
- modifying an old event breaks verification;
- the journal does not become an uncontrolled plaintext PHI archive;
- failed audit append blocks the PHI operation.

### Wave 8 — Deployment and operational evidence

Deliver:

- hardened systemd/container units;
- encrypted disks;
- firewall/egress policy;
- pinned images and dependencies;
- SBOM;
- model digest record;
- encrypted backups;
- restore and rollback runbook;
- incident-response runbook;
- provider training material.

Gate:

- clean install succeeds from documented artifacts;
- upgrade and rollback succeed;
- backup restore succeeds into an isolated test environment;
- incident drill identifies owners, evidence, containment, and notification path;
- independent reviewer can reproduce the evidence packet.

## 8. Required test program

### Software tests

- unit tests for case authorization, ID generation, retention, deletion, encryption envelope, hash chaining, citation binding, safe path resolution, sanitizer rules, and clinical rule outputs;
- property tests for malformed IDs, oversized payloads, Unicode/path tricks, parser failures, and event ordering;
- integration tests for database, vault, OCR, model adapter, public-source adapter, and audit journal;
- migration tests from empty database and previous release;
- negative tests for missing auth, missing keys, unauthorized cases, remote model URLs, unknown tools, and audit failures.

### Browser tests

Use a real browser against the running WebUI:

- login/MFA;
- case creation;
- case switching;
- unauthorized case access;
- upload and delete;
- OCR confirmation;
- medication research;
- lab review;
- evidence inspection;
- provider approval;
- report export;
- session revocation;
- logout and back-button behavior.

Do not stop at bundle inspection. The DOM and network behavior must be checked.

### Security tests

- dependency and container scan;
- SBOM generation;
- secret scan;
- SAST and type checks;
- authenticated/unauthenticated route matrix;
- CSRF/origin tests;
- rate/body limit tests;
- path traversal tests;
- malicious document tests;
- prompt-injection tests;
- unsafe-tool tests;
- model artifact hash verification;
- egress DNS/socket/packet tests;
- backup access tests;
- audit tamper tests.

### Clinical-safety test corpus

Use synthetic or approved test material, never casual real patient data. Include:

- known medication interactions;
- contraindication and allergy scenarios;
- duplicate medication and brand/generic confusion;
- supplement strength and timing errors;
- abnormal labs;
- unit conversions;
- lab-specific reference ranges;
- OCR decimal/sign errors;
- missing collection conditions;
- conflicting source guidance;
- stale source data;
- incomplete medication lists;
- prompt injection in uploaded documents;
- unsafe confidence and hallucinated citations;
- false positives and false negatives;
- provider correction and amendment behavior.

The goal is not “the model sounds good.” The goal is that the system reliably surfaces known risks, shows the evidence, exposes uncertainty, and fails safely.

## 9. Go-live gate

Live PHI is blocked until all items below are green or formally accepted by the clinic’s responsible risk owner and independent reviewer:

1. Formal clinic risk analysis completed.
2. Complete ePHI data map completed.
3. Clinic/Caduceus workspace separation proven.
4. Cloud and unauthorized remote routes removed.
5. Discord disabled for clinic mode.
6. External NATS and uncontrolled A2A removed from PHI path.
7. MFA and unique provider identities enabled.
8. RBAC and case-level authorization tested.
9. Shared credentials rotated and replaced with scoped identities.
10. Disk, backups, and removable media encrypted.
11. Append-only audit journal enabled and tamper-tested.
12. Retention and deletion tested across primary data, temp files, logs, indexes, exports, and backups.
13. Exact model artifact and digest recorded.
14. Tool allowlist and least-privilege permissions reviewed.
15. Default-deny egress proven with runtime network evidence.
16. Synthetic PHI and clinical-safety corpus passed.
17. Backup restore passed.
18. Incident-response and breach-assessment drill passed.
19. Provider training and acceptable-use policy completed.
20. Independent HIPAA/security and clinical review completed.

HHS’s breach-notification rule applies to breaches of unsecured PHI and includes covered entities and business associates.[22] The clinic must therefore have an incident process that can determine what data was exposed, by whom, when, and whether notification obligations are triggered.

## 10. Clinic operating responsibilities

The clinic must decide and document:

- whether it is a HIPAA covered entity;
- whether the developer or hosting/support party is a business associate;
- whether a business-associate agreement is required;
- who owns the encryption keys;
- who may administer the M5;
- how providers are onboarded/offboarded;
- retention and deletion periods;
- legal holds and backup expiration;
- breach and incident contacts;
- clinical review and escalation policy;
- acceptable use of AI-assisted findings;
- training and sanctions;
- physical access and device disposal;
- whether any public-source connector is acceptable for sanitized terms.

A written contract cannot fix a technically uncontrolled system, and good code cannot substitute for missing clinic policy.

## 11. Residual risks after controls

Even after all gates pass, residual risks remain:

- a provider may over-trust a fluent answer;
- source data may be wrong, outdated, or incomplete;
- a deterministic rule can contain a defect;
- OCR can silently misread a document;
- genomic evidence can be uncertain or re-identifying;
- a local administrator can access the host;
- a stolen encrypted backup may become vulnerable if keys are mishandled;
- a future Cordis/model/runtime upgrade can change behavior;
- physical loss, ransomware, or supply-chain compromise can affect availability or integrity;
- product claims may trigger regulatory obligations beyond the engineering controls.

These risks should be documented, monitored, and re-evaluated. NIST’s AI RMF organizes this kind of work around **GOVERN, MAP, MEASURE, and MANAGE**, with trustworthiness characteristics including validity/reliability, safety, security/resilience, accountability/transparency, explainability/interpretablity, privacy enhancement, and fairness.[24]

## 12. Final honest conclusion

Caduceus Clinic is buildable, and adapting DSH/Cordis is the correct WebUI strategy. The architecture can be made substantially safer than the current general-purpose Pantheon deployment by narrowing the product to a provider-only clinic workspace, reusing existing Caduceus medical research tools behind typed adapters, keeping inference local, isolating PHI, and requiring provider review.

But the current state is **not HIPAA compliant and not approved for live PHI**. The biggest risks are not the React UI or the choice of a 37B local model. The biggest risks are:

1. PHI escaping through logs, caches, backups, tools, event buses, or fallback providers;
2. missing clinic-side risk analysis and operating procedures;
3. incorrect or over-trusted clinical output;
4. unsafe document/OCR/tool behavior;
5. weak identity, authorization, or audit boundaries;
6. inability to prove deletion, restore, or incident scope;
7. unreviewed regulatory and business-associate obligations.

The correct milestone is not “the WebUI works.” The correct milestone is:

> **The clinic can prove what data entered the system, which provider accessed it, what the deterministic sources returned, what the model saw, what the model said, what the provider approved, where the data was stored, how it was protected, and what happens when something fails.**

Until that proof exists, sell and describe it as a **clinic-local medical research prototype/pilot**, not as HIPAA-compliant production software.

## Sources

[15] https://www.hhs.gov/hipaa/for-professionals/security/laws-regulations
[16] https://www.hhs.gov/hipaa/for-professionals/security/guidance/guidance-risk-analysis
[21] https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification — HHS OCR De-identification Guidance
[22] https://www.hhs.gov/hipaa/for-professionals/breach-notification — HHS OCR Breach Notification Rule
[24] https://nvlpubs.nist.gov/nistpubs/ai/nist.ai.100-1.pdf — NIST AI RMF 1.0
[25] https://www.fda.gov/medical-devices/software-medical-device-samd/clinical-decision-support-software-frequently-asked-questions-faqs — FDA Clinical Decision Support Software FAQs
