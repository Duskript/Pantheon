# Caduceus Clinic Consolidated Build Plan

**Status:** Execution-ready build specification; implementation has not started.
**Review basis:** Caduceus Clinic HIPAA/security white paper and build assurance checklist, reconciled against the live DeepSeek Harness repository.
**Product:** Caduceus Clinic.
**Primary codebase:** `/home/konan/workspace/deepseek-harness`.
**Deployment target:** Provider-operated, clinic-local host; BOSGAME M5-class inference host remains a hardware acceptance target, not an assumed capability.
**Foundation:** DeepSeek Harness (DSH) over vendored Cordis.
**First release target:** Research Pilot using public and reviewed de-identified data.
**Live-PHI posture:** FAIL until every release gate and independent review requirement passes.

---

## 1. Executive build decision

Build Caduceus Clinic as a clinic-specific DSH profile and bundle over the existing Cordis WebUI.

Do not create a second React application, copy the DSH shell, patch vendored Cordis, or modify the generic DSH agent loop for clinic behavior.

The live DSH source confirms the composition model:

- Browser entry: `apps/web/src/main.ts`.
- Web boot kernel: `packages/client/web/src/boot.tsx`.
- Shell assembly: `packages/client/web/src/app-shell.ts` and `app.tsx`.
- Browser runtime objects: `packages/client/runtime`.
- Slot registry and prop derivation: `packages/client/ui-slots`.
- React binding machinery: `packages/client/web-react`.
- Host API gateway: `packages/host/apiproxy`.
- Bundle patch layer: `packages/bundle/web-app/cordis.patch.yml`.
- Shared base composition: `packages/bundle/base/cordis.patch.yml`.

Caduceus supplies the clinic domain, secure storage, clinical workflows, policy, and review surfaces. DSH/Cordis supplies the plugin tree, transport, session machinery, browser shell, and reversible composition.

The medical source hierarchy and existing Caduceus research methodology remain authoritative. The build must adapt those capabilities behind typed, auditable adapters rather than duplicate the medical logic inside the WebUI.

---

## 2. Product thesis

Caduceus Clinic is a provider-only medical research and clinical decision-support workspace.

A provider can:

1. Sign in with a unique clinic identity.
2. Create or select an opaque case.
3. Upload medical documents and structured inputs.
4. Review local OCR and extraction results.
5. Ask Caduceus to organize supplied information and research approved sources.
6. Receive cited, structured findings with evidence grades and uncertainty.
7. Approve, reject, amend, or mark findings uncertain.
8. Export an approved local report.
9. Reconstruct the model, tool, evidence, review, and export history.

The system does not diagnose, prescribe, change medication orders, write to an EHR, message patients, or autonomously make treatment decisions.

The first commercial product is a **provider-only, clinic-local Caduceus research workspace**, not an EHR assistant.

---

## 3. Locked scope

### 3.1 Included in the base product

- Provider-only WebUI.
- Clinic-local deployment.
- Opaque, non-sequential case IDs.
- Case-scoped sessions and documents.
- Provider identity, role, session expiry, revocation, and MFA policy.
- Medication and supplement entry.
- Existing Caduceus medication research and source hierarchy through reviewed adapters.
- PDF, image, CSV, and text intake with explicit limits.
- Local OCR for scanned records.
- Extraction drafts with source locations and provider confirmation.
- Optional de-identification preview.
- Laboratory organization, normalization, and trend review.
- Cited research findings with evidence grades and freshness metadata.
- Provider review and amendment state.
- Controlled local report export.
- Append-only, hash-chained audit journal.
- Encrypted PHI payload storage separated from searchable audit metadata.
- Tested backup, restore, deletion, and retention execution.
- Deny-by-default outbound policy for PHI components.
- Synthetic-PHI, prompt-injection, unsafe-tool, authorization, and egress testing.

### 3.2 Explicitly excluded from the base product

- EHR, FHIR, SMART on FHIR, HL7, DICOM, or vendor-specific integration.
- Automatic chart write-back.
- Patient accounts, patient portal, and patient messaging.
- Autonomous diagnosis, prescribing, ordering, triage, or treatment changes.
- Automatic medication-list modification.
- Discord, Telegram, or other chat-platform PHI workflows.
- Cloud inference or cloud fallback in PHI mode.
- Remote Ollama or third-party inference fallback in PHI mode.
- External event buses in the PHI path.
- General-purpose browser automation over PHI.
- Unrestricted shell, filesystem, terminal, subagent, A2A, or MCP access.
- Genome/pharmacogenomic analysis in the first Research Pilot release.

EHR connectivity is a separately scoped, separately priced project. Read-only import is the first possible integration milestone; write-back is a distinct high-risk milestone.

---

## 4. Release states

| State | Allowed data | Product claim | Required evidence |
|---|---|---|---|
| Development | Synthetic data only | Development build | Local tests, configuration proof, no real records |
| Research Pilot | Public and reviewed de-identified data | Clinic-local research prototype/pilot | Auth, case isolation, egress proof, de-identification review, audit, restore |
| Clinic Pilot | Limited PHI under clinic authorization | Controlled clinic pilot | Complete PHI map, risk analysis, technical gates, training, review plan |
| Live PHI | Clinic-approved PHI workflows | Ready for independent review only after all gates; never software-only certification | All 20 gates green, clinical sign-off, independent HIPAA/security review |

Development and Research Pilot must never be described as HIPAA-compliant production software.

The application must refuse a higher-risk mode when its required authentication, storage, audit, deletion, or egress controls are unavailable.

---

## 5. Current repository facts and constraints

The DSH repository is a real pnpm workspace using Node `^22.19.0 || >=24.0.0`, TypeScript 6, ESM, Cordis plugins, separate host/client compiler aggregates, and generated package/catalog checks.

The current DSH working tree contains unrelated local modifications. Do not clean, reset, stash, or overwrite them. Build Caduceus in a dedicated worktree or branch created from the selected DSH baseline.

The DSH root rules require:

- Read `docs/architecture.md` before changing `packages/`.
- Walk `AGENTS.md` from repository root to every edited subtree.
- Use plugin extension points rather than loop changes.
- Keep model-visible data reconstructable from durable session events.
- Keep client components pure and framework-free.
- Use `ctx.slots.register` for UI composition.
- Use real Loader-composition tests for product-visible plugins.
- Add package invariants, package README contracts, and an Agent Note for non-trivial changes.
- Run the narrowest relevant checks, then the assembled browser test for visible changes.
- Never commit credentials or raw PHI.

The DSH generic base currently contains remote-model adapters, session persistence, telemetry, shell/filesystem capabilities, tools, and other broad surfaces. Caduceus must compose a narrowed clinic profile that explicitly proves the final active graph rather than assuming disabled defaults are sufficient.

The existing Caduceus Hermes profile currently contains remote provider configuration, raw-turn persistence, A2A, and Discord configuration. It is not the clinic runtime and must not be used as evidence of PHI readiness.

---

## 6. Architecture

```text
Provider browser
      |
      | HTTPS + secure session cookie + clinic identity
      v
Caduceus Clinic WebUI
      |
      +-- DSH/Cordis client tree
      |     +-- case navigation
      |     +-- case workspace
      |     +-- conversation
      |     +-- intake and extraction
      |     +-- findings and review
      |     +-- audit inspection
      |     +-- controlled export
      |
      v
Clinic host services
      |
      +-- provider identity and RBAC
      +-- clinic policy and mode gate
      +-- case registry
      +-- encrypted PHI vault
      +-- structured clinical-data store
      +-- local OCR/extraction worker
      +-- Caduceus medical-tool adapter
      +-- evidence connector policy
      +-- audit journal and replay
      +-- retention, deletion, backup, and restore
      |
      +-------------------+-------------------+
      |                   |                   |
      v                   v                   v
Encrypted clinic store  Local model runtime  Approved evidence connectors
and key provider        on clinic host       with minimized queries only
```

### 6.1 DSH responsibilities

Reuse:

- `packages/client/web` for boot and shell lifecycle.
- `packages/client/runtime` for React-free session objects and snapshots.
- `packages/client/ui-slots` for typed plugin composition.
- `packages/client/web-react` for the single ctx-to-React binding layer.
- `packages/client/ui-layout` for the three-column frame and panel state.
- `packages/client/ui-sidebar` as the structural basis for case navigation.
- `packages/client/ui-conversation` as the conversation basis.
- `packages/client/ui-attachment` for attachment presentation.
- `packages/client/ui-tool` for tool-call rendering patterns.
- `packages/client/ui-deliverables` for controlled output patterns.
- `packages/host/apiproxy` for the transport-agnostic host API gateway.
- `packages/host/webserver` and `packages/host/frontend-static` for clinic-local serving.
- `packages/session/session-persistence` as the persistence interface, not as an automatically approved PHI backend.
- `packages/interaction/user-approval` for fail-closed approval behavior.
- `packages/interaction/permission-presets` as a reference for bounded permission composition.
- `packages/storage/storage-domain` for schema-validated domains where its storage guarantees are sufficient.

### 6.2 Caduceus responsibilities

Add clinic-specific packages only after the Phase 0 source-plane review confirms final names and dependencies:

```text
packages/clinic/clinic-domain/
  package.json
  tsconfig.json
  src/types.ts
  src/schemas.ts
  src/case-id.ts
  src/case-record.ts
  src/document-record.ts
  src/clinical-inputs.ts
  src/finding.ts
  src/review.ts
  src/retention.ts
  src/invariant.ts
  tests/

packages/clinic/clinic-policy/
  package.json
  tsconfig.json
  src/mode.ts
  src/tool-policy.ts
  src/egress-policy.ts
  src/retention-policy.ts
  src/invariant.ts
  tests/

packages/clinic/clinic-storage/
  package.json
  tsconfig.json
  src/crypto-provider.ts
  src/key-reference.ts
  src/encrypted-blob-store.ts
  src/clinic-metadata-store.ts
  src/deletion.ts
  src/invariant.ts
  tests/

packages/clinic/clinic-session-persistence/
  package.json
  tsconfig.json
  src/index.ts
  src/encrypted-session-persistence.ts
  src/format.ts
  src/replay.ts
  src/invariant.ts
  tests/

packages/clinic/clinic-audit/
  package.json
  tsconfig.json
  src/journal.ts
  src/hash-chain.ts
  src/event-types.ts
  src/payload-vault.ts
  src/replay.ts
  src/export.ts
  src/invariant.ts
  tests/

packages/clinic/clinic-auth/
  package.json
  tsconfig.json
  src/identity.ts
  src/passwords.ts
  src/mfa.ts
  src/sessions.ts
  src/rbac.ts
  src/invariant.ts
  tests/

packages/clinic/clinic-research/
  package.json
  tsconfig.json
  src/adapter.ts
  src/tool-manifest.ts
  src/source-policy.ts
  src/minimization.ts
  src/findings.ts
  src/invariant.ts
  tests/

packages/clinic/clinic-ocr/
  package.json
  tsconfig.json
  src/worker.ts
  src/extraction.ts
  src/source-locations.ts
  src/limits.ts
  src/invariant.ts
  tests/

packages/clinic/clinic-api/
  package.json
  tsconfig.json
  src/service.ts
  src/routes.ts
  src/schema.ts
  src/authorization.ts
  src/invariant.ts
  tests/

packages/client/ui-caduceus/
  package.json
  tsconfig.json
  tsdown.config.ts
  src/index.ts
  src/invariant.ts
  src/client/apply.ts
  src/client/contract/
  src/client/case-sidebar/
  src/client/case-workspace/
  src/client/intake/
  src/client/findings/
  src/client/review/
  src/client/audit/
  src/client/export/
  src/client/styles/
  tests/

packages/bundle/caduceus-clinic/
  package.json
  tsconfig.json
  cordis.patch.yml
  src/index.ts
  src/policy.ts
  src/profile.ts
  README.md
  tests/
```

These are proposed ownership boundaries, not permission to invent package APIs during implementation. A package is created only when a current consumer and capability seam justify it.

### 6.3 Host API strategy

The browser must not call clinic storage, model, or tool internals directly.

The clinic API must expose typed request/response contracts through the existing DSH host gateway pattern. The Phase 0 API spike must decide whether the final implementation:

1. Extends the existing `ApiProxy` declaration and generated remote methods in `packages/host/apiproxy`; or
2. Adds a separate clinic host capability that is mounted beside `ApiProxy` and registers its own typed routes through the host webserver.

Default: extend the existing API gateway only for request/response transport and keep clinic domain logic in `packages/clinic/clinic-api`. Do not place PHI policy or storage logic inside generic transport code.

Every API operation must authorize actor, role, case scope, operation, and mode inside the operation executor. Hiding a method from the UI is not authorization.

---

## 7. Data boundary contract

### 7.1 Approved stores

| Store | Contents | Required protection |
|---|---|---|
| Clinic metadata DB | Opaque case metadata, roles, states, digests, references | Access control, encrypted storage, backup/restore, deletion semantics |
| Encrypted PHI vault | Original files, OCR text, extracted fields, sensitive findings | Envelope encryption, key lifecycle, strict permissions, retention/deletion |
| Audit journal | Searchable metadata, digests, hashes, encrypted payload references | Append-only writes, hash chain, integrity verification |
| Encrypted session persistence | Model-visible conversation/events needed for replay | Encrypted at rest, case-scoped access, retention/deletion |
| Search/index store | Only approved indexed fields | No raw PHI by default; deletion-aware rebuild |
| Backup repository | Encrypted recovery copies | Separate access, retention, restore test |
| Identity map | Patient identity mapping if the clinic requires one | Separate clinic-controlled system or vault; never in the normal case record |

Generic DSH raw-turn persistence, generic plaintext JSONL, external vector stores, Discord history, A2A messages, external NATS, telemetry exporters, crash bundles, and uncontrolled temporary files are not approved PHI stores.

### 7.2 Model-visible means logged

Every model request must be reconstructable from an append-only event sequence containing at least:

```text
event_id
session_id
run_id
actor_id
workspace_id
case_id
timestamp
event_type
model_id
model_artifact_digest
tool_id
approval_state
payload_digest
encrypted_payload_reference
previous_event_hash
event_hash
```

The exact prompt, tool arguments, tool results, approvals, and model output may be stored only through encrypted payload references with policy-controlled retention. Searchable audit metadata must not become a permanent plaintext PHI transcript.

Use:

```text
event_hash = SHA256(previous_event_hash + canonical_event)
```

Canonicalization, key references, event ordering, and deletion behavior must be defined in tests before implementation spreads across packages.

### 7.3 Required clinical output fields

Every clinical-impacting finding must render and persist:

- Finding statement.
- Category.
- Evidence items and source links.
- Evidence grade.
- Confidence or uncertainty.
- Missing information.
- Potential significance.
- Provider questions.
- Suggested follow-up framed as a review item.
- Source freshness timestamp.
- Human review status.
- Reviewer identity and timestamp after review.

No prose-only result may bypass the structured finding model.

---

## 8. Security invariants

These are executable requirements, not documentation-only goals:

1. PHI mode cannot start without approved auth, storage, audit, and egress controls.
2. Every request is authorized against actor, role, case, and operation.
3. A provider cannot read another provider’s unassigned case.
4. Case switching cannot reuse the previous case’s model context.
5. The model cannot widen its own tool set or case scope.
6. External evidence connectors receive minimized queries, never raw documents or full narratives.
7. Cloud model routes and remote fallback are absent from the PHI profile.
8. Discord, A2A, external NATS, uncontrolled webhooks, and telemetry are absent from the PHI path.
9. A failed required audit append blocks the PHI-mode operation.
10. Original findings are immutable; amendments append a new event and retain the reason.
11. Deletion removes active records, extracted data, search entries, exports, and policy-covered backup copies.
12. A restored backup passes integrity verification before becoming usable.
13. Uploaded files cannot escape the case vault through path traversal or archive extraction.
14. Unsupported, ambiguous, or low-confidence OCR never becomes silently confirmed clinical data.
15. Genome data is isolated from standard search and remains disabled until its separate gate passes.
16. Model artifact, tokenizer, runtime, and configuration identity are recorded per model run.
17. Secrets never enter logs, audit exports, screenshots, fixtures, or committed configuration.
18. The service fails closed when key material or policy configuration is unavailable.

### 8.1 Breach-notification contract

The incident-response design must explicitly account for the HHS Breach Notification Rule: a breach of **unsecured PHI** can trigger notification obligations for covered entities and business associates. Caduceus must not treat local hosting, encryption at rest, or a clinic-local network as a substitute for breach assessment.

Before any Clinic Pilot or Live PHI decision, the operator runbook must define:

- Who owns breach discovery, investigation, risk assessment, and notification decisions.
- How the system records discovery time, affected systems, affected records, and PHI categories.
- How encryption/key state is evidenced when assessing whether PHI was secured or unsecured.
- How business-associate and covered-entity responsibilities are coordinated when the deployment crosses those roles.
- How affected individuals, the Secretary, and media notification requirements are evaluated with qualified counsel and the clinic’s incident-response policy.
- How evidence is preserved without copying unsecured PHI into chat, tickets, screenshots, or unmanaged exports.
- How credentials, keys, sessions, connectors, backups, and network routes are contained and rotated after an incident.

**Required evidence:** incident-response runbook, tabletop exercise, breach assessment template, role/responsibility matrix, notification decision record template, and a synthetic unsecured-PHI incident test. This is an operational and legal/compliance obligation; software tests alone do not establish compliance.

---

## 9. Phase 0 — prove the foundation before feature work

**Owner:** Hermes with Hephaestus and Cybermage.
**Entry:** This plan approved; no clinic feature implementation.
**Exit:** All critical gates pass, or the plan pivots with captured floor value.

### Gate 0.1 — Isolated DSH baseline

**Purpose:** Prevent unrelated dirty-tree work from contaminating the Caduceus build.

**Actions:**

- Record the current DSH branch, commit, remote, and dirty paths.
- Create a dedicated worktree under `/home/konan/worktrees/caduceus-clinic` from the approved baseline.
- Walk root `AGENTS.md`, `docs/AGENTS.md`, `packages/AGENTS.md`, and `packages/client/AGENTS.md`.
- Run only baseline checks required to establish the selected revision’s state.

**Evidence:** `baseline/git-status.txt`, `baseline/git-revision.txt`, command outputs, and the worktree path.

**Fail condition:** The selected baseline cannot run the relevant type, Loader, or browser checks without unrelated modifications being involved.

### Gate 0.2 — Cordis profile and bundle composition

**Purpose:** Prove a Caduceus bundle can be loaded without shell forks or vendored Cordis edits.

**Actions:**

- Create a minimal scratch bundle/profile with one clinic policy plugin and one browser plugin.
- Use the existing DSH bundle and client registration conventions.
- Prove the profile dump contains the intended rows and does not contain disallowed remote or general-purpose surfaces.
- Prove browser boot reaches the existing loading-page-to-settled transition.

**Evidence:** Profile dump, package manifest, `cordis.patch.yml`, Loader-composition test output, built browser smoke output, and screenshot.

**Fail condition:** The profile requires changes to `apps/web/src/main.ts`, vendored Cordis, or generic `agent-loop` code.

### Gate 0.3 — Encrypted persistence and replay

**Purpose:** Prove the DSH session persistence interface can support clinic retention without plaintext PHI on disk.

**Actions:**

- Create a synthetic session containing a unique canary phrase.
- Persist it through the proposed clinic persistence provider.
- Inspect all files, SQLite pages, temporary files, logs, and backup outputs for the canary.
- Reload and replay the session with the same approved key reference.
- Rotate or replace the test key according to the selected provider contract.
- Execute deletion and verify the canary is absent from policy-covered stores.

**Evidence:** Persistence contract tests, disk scan output, replay output, deletion output, and key-provider decision record.

**Fail condition:** Plaintext PHI remains in a durable store, the provider cannot replay the exact model-visible envelope, or deletion cannot be demonstrated.

### Gate 0.4 — Auth, case authorization, and revocation

**Purpose:** Prove the minimum clinic identity boundary before building UI workflows.

**Actions:**

- Exercise unique provider, reviewer, operator, administrator, and service identities.
- Prove login failure is generic and rate-limited.
- Prove session expiry and server-side revocation.
- Prove provider/case authorization through the executor, not only the route or UI.
- Prove CSRF and session-fixation defenses for browser requests.
- Decide the first implementation as local clinic accounts with an MFA-capable policy; defer OIDC/SSO unless a clinic identity provider is named.

**Evidence:** Auth test output, authorization matrix, session-cookie inspection, and revocation trace.

**Fail condition:** A trusted LAN, tailnet, bearer token, or hidden UI control is treated as identity or authorization.

### Gate 0.5 — Egress and tool policy

**Purpose:** Prove PHI mode has a real deny-by-default network and tool boundary.

**Actions:**

- Build the approved tool manifest with PHI permission, destinations, filesystem scope, size limits, approval requirement, and audit event.
- Submit canary PHI through document, model, tool, and evidence paths.
- Inspect DNS, sockets, firewall counters, and packet capture.
- Verify no cloud model, telemetry, Discord, A2A, external NATS, or uncontrolled webhook receives the canary.
- Verify sanitized public-source research can run only through an explicitly approved connector.

**Evidence:** Tool manifest, allow/deny test output, network captures, DNS/socket evidence, and assembled profile dump.

**Fail condition:** Any unapproved destination receives PHI, or an alternate caller bypasses the policy.

### Gate 0.6 — Medical capability adapter

**Purpose:** Prove existing Caduceus medical capabilities can be called through a typed loopback adapter without duplicating logic or widening the agent surface.

**Actions:**

- Inventory each candidate capability: input schema, output schema, source hierarchy, credentials, network destinations, PHI behavior, and failure modes.
- Select the first Research Pilot roster: medication/source research only, with deterministic structured output and citations.
- Exclude shell, browser automation, cross-god routing, Discord, and general web search from raw PHI mode.
- Prove tool results, source metadata, and findings become auditable events.

**Evidence:** Tool inventory, adapter contract tests, source citation fixture, and audit trace.

**Fail condition:** A capability cannot declare its PHI behavior, network destinations, or audit contract.

### Gate 0.7 — M5 model/runtime validation

**Purpose:** Prove the exact local inference artifact and runtime on the target hardware.

**Actions:**

- Record exact repository, architecture, parameter count, quantization, context length, tokenizer, runtime, license, provenance, and digest.
- Benchmark the actual artifact on the actual M5-class host.
- Measure startup, latency, context behavior, concurrency, memory pressure, restart, and failure recovery.
- Prefer a validated llama.cpp/Vulkan or ROCm path; treat vLLM on gfx1151 as experimental until proven.
- Reserve memory for OS, database, OCR, audit, and concurrency rather than treating unified memory as dedicated VRAM.

**Evidence:** Model artifact record, digests, benchmark output, memory profile, restart trace, and license record.

**Fail condition:** The model identity is unresolved, the runtime needs a remote fallback, or the target host cannot meet the Research Pilot acceptance envelope.

### Phase 0 decision

- **GO:** All gates pass with artifacts.
- **PIVOT:** A non-critical gate fails; re-scope the Research Pilot and record the constraint before Wave 0.
- **NO-GO:** A critical gate fails; stop feature work and retain only reusable floor value: bundle composition harness, policy schemas, persistence contract tests, and adapter inventory.

No feature wave begins on a NO-GO foundation.

---

## 10. Wave plan

Each wave has one owner, explicit dependencies, executable acceptance criteria, and intentional deferrals. A wave is complete only when its evidence is attached to the release packet and the DSH documentation/Agent Note obligations are satisfied.

### Wave 0 — Product and source foundation

**Owner:** Hermes; contributors: Caduceus, Cybermage, Hephaestus.
**Depends on:** Phase 0 GO or approved PIVOT.

**Deliverables:**

- Product thesis and non-goals.
- Package ownership map.
- DSH/Cordis license and adaptation record.
- Existing Caduceus tool inventory.
- PHI data-flow map.
- Threat model.
- Release-state contract.
- Exact model artifact intake form.
- Clinic operating assumptions.
- Initial evidence-packet directory template.

**Files:**

```text
docs/caduceus/README.md
docs/caduceus/PRD.md
docs/caduceus/data-map.md
docs/caduceus/threat-model.md
docs/caduceus/tool-inventory.md
docs/caduceus/release-gates.md
docs/caduceus/model-artifact-record.md
.agents/notes/proposed/<date>-caduceus-clinic-foundation.md
```

**Acceptance criteria:**

- The base product contains no EHR or patient-facing dependency.
- Every reused capability has a declared owner, input/output contract, PHI classification, network classification, and audit event.
- Every storage location has owner, location, retention, encryption, access, deletion, and backup fields.
- Unresolved model identity is visibly marked unresolved.
- The DSH profile can be evaluated from a generated dump rather than prose.

**Deferred:** Implementation code, live PHI, genome module, EHR adapter, external identity provider.

### Wave 1 — Clinic profile and safe composition

**Owner:** Hephaestus.
**Depends on:** Wave 0; Gates 0.2, 0.5, and 0.7.

**Deliverables:**

- `packages/bundle/caduceus-clinic` bundle.
- Clinic profile patch with complete row replacements.
- Local-only model provider configuration.
- Clinic persona and mode prompt sections.
- Minimal approved tool roster.
- Disabled remote model, telemetry, shell, filesystem, terminal, subagent, Discord, A2A, and uncontrolled web rows in the clinic profile.
- Profile dump verification.

**Files:**

```text
packages/bundle/caduceus-clinic/package.json
packages/bundle/caduceus-clinic/tsconfig.json
packages/bundle/caduceus-clinic/tsdown.config.ts
packages/bundle/caduceus-clinic/cordis.patch.yml
packages/bundle/caduceus-clinic/src/index.ts
packages/bundle/caduceus-clinic/src/policy.ts
packages/bundle/caduceus-clinic/src/profile.ts
packages/bundle/caduceus-clinic/src/invariant.ts
packages/bundle/caduceus-clinic/README.md
packages/bundle/caduceus-clinic/tests/
```

**Acceptance criteria:**

- `pnpm run verify-cordis-config` passes for the clinic patch.
- The clinic profile dump contains only approved active rows.
- No remote model or fallback route is active in PHI mode.
- No telemetry exporter or external event bus is active in PHI mode.
- The assembled profile reaches a real browser smoke test.
- A missing clinic policy dependency fails loudly at load.

**Deferred:** Case UI, document intake, clinical tools, real auth, live PHI.

### Wave 2 — Domain types, policy, and encrypted storage

**Owner:** Hephaestus with Cybermage.
**Depends on:** Wave 1; Gates 0.3 and 0.4.

**Deliverables:**

- Branded case/document/run IDs.
- Case, document, medication, lab, finding, review, retention, and mode schemas.
- Policy evaluator and tool manifest.
- Encrypted payload store.
- Clinic metadata store.
- Key-reference abstraction and startup failure behavior.
- Deletion coordinator.
- Backup inventory contract.

**Files:**

```text
packages/clinic/clinic-domain/
packages/clinic/clinic-policy/
packages/clinic/clinic-storage/
```

**Acceptance criteria:**

- Invalid durable records are rejected with their table/key location.
- Case IDs are non-sequential and cannot contain direct patient identity.
- Metadata and PHI payloads use separate stores and access faces.
- The synthetic canary is absent from plaintext disk, logs, temp files, and unauthorized stores.
- Key absence or policy absence fails closed.
- Deletion returns a store-by-store result and records incomplete cleanup as a failure.
- Concurrent updates do not lose records or bypass retention state.

**Deferred:** Browser UI, OCR, real source connectors, genome records.

### Wave 3 — Clinic session persistence and audit journal

**Owner:** Hephaestus with Cybermage.
**Depends on:** Wave 2.

**Deliverables:**

- Encrypted implementation of the DSH `SessionPersistence` seam.
- Clinic audit event types.
- Canonical event serialization.
- Hash-chain implementation.
- Encrypted payload references.
- Replay/reconstruction command.
- Integrity verification command.
- Retention-aware audit deletion behavior.

**Files:**

```text
packages/clinic/clinic-session-persistence/
packages/clinic/clinic-audit/
```

**Acceptance criteria:**

- A session reload reconstructs the exact model request envelope, tool calls, results, approvals, and output.
- Hash tampering, deletion, reordering, and malformed canonical events are detected.
- Required audit append failure blocks a PHI-mode request.
- Searchable metadata contains no plaintext secret values or unrestricted PHI transcript.
- Original findings remain immutable after amendments.
- Replay works after process restart and after restore into a clean test target.

**Deferred:** UI audit inspection and report export.

### Wave 4 — Clinic API, auth, and authorization

**Owner:** Hephaestus.
**Depends on:** Waves 2 and 3; Gate 0.4.

**Deliverables:**

- Clinic service and typed schemas.
- Provider-local accounts and role assignments.
- MFA-capable policy.
- Secure session cookies, idle expiry, and revocation.
- Case authorization executor.
- CSRF, body-size, rate, and request-origin protections.
- Typed browser API methods over the selected DSH transport.

**Files:**

```text
packages/clinic/clinic-auth/
packages/clinic/clinic-api/
packages/host/apiproxy/src/api/
packages/host/apiproxy/src/api-proxy.ts
packages/host/apiproxy/tests/
```

Only edit generic `packages/host/apiproxy` files if the Phase 0 API decision proves the extension belongs there. Otherwise keep clinic routing in the clinic package and use the existing host webserver carrier.

**Acceptance criteria:**

- Unauthenticated requests receive the documented denial response.
- Provider A cannot read, mutate, or export Provider B’s unassigned case.
- Revoked sessions fail on the next request and cannot reopen a case.
- CSRF-protected state changes reject missing/invalid tokens.
- Oversized and malformed request bodies fail before PHI persistence.
- Authorization tests call the executor directly and through the browser API.
- No API response includes the patient identity map by default.

**Deferred:** OIDC/SSO adapter, EHR adapter, patient accounts.

### Wave 5 — Caduceus client shell and case workspace

**Owner:** Iris for visual direction; Marvin/Hephaestus for implementation.
**Depends on:** Wave 4.

**Deliverables:**

- `@deepseek-ai/dsh-client-ui-caduceus` plugin.
- Case sidebar replacing generic session-first navigation.
- Case creation/selection.
- Provider identity and role display.
- Case-scoped conversation shell.
- Workspace tabs for documents, inputs, findings, review, audit, and export.
- Active mode, case ID, provider, and enabled-tool indicators.
- Empty, loading, failure, and revoked-session states.

**Files:**

```text
packages/client/ui-caduceus/package.json
packages/client/ui-caduceus/tsconfig.json
packages/client/ui-caduceus/tsdown.config.ts
packages/client/ui-caduceus/src/index.ts
packages/client/ui-caduceus/src/invariant.ts
packages/client/ui-caduceus/src/client/apply.ts
packages/client/ui-caduceus/src/client/contract/
packages/client/ui-caduceus/src/client/case-sidebar/
packages/client/ui-caduceus/src/client/case-workspace/
packages/client/ui-caduceus/src/client/styles/
packages/client/ui-caduceus/tests/
packages/bundle/caduceus-clinic/cordis.patch.yml
packages/bundle/caduceus-clinic/package.json
```

**Acceptance criteria:**

- All UI composition uses `ctx.slots.register`; no component imports `ctx`, service classes, or React context.
- `src/client` uses the four props shares and declared stores only.
- Case switching changes session scope and never reuses the prior case’s model context.
- Refresh/reconnect restores the selected case from durable state.
- Two synthetic cases cannot see each other’s documents, findings, sessions, or exports.
- Keyboard navigation and browser accessibility checks pass.
- A real Loader-composition test boots the assembled plugin tree.

**Deferred:** Clinical findings, OCR, genome UI, patient UI, progressive boot.

### Wave 6 — Secure document intake and local OCR

**Owner:** Hephaestus; clinical acceptance by Caduceus.
**Depends on:** Waves 2–5.

**Deliverables:**

- Multipart intake with type, size, count, and decompression limits.
- Encrypted document vault integration.
- SHA-256 content digests.
- Local OCR worker.
- Source-location-preserving extraction draft.
- Provider correction and confirmation.
- De-identification preview and confirmation event.
- Search/index admission policy.

**Files:**

```text
packages/clinic/clinic-ocr/
packages/clinic/clinic-api/src/routes.ts
packages/clinic/clinic-storage/src/encrypted-blob-store.ts
packages/client/ui-caduceus/src/client/intake/
```

**Acceptance criteria:**

- Unsupported, malformed, oversized, and archive-bomb inputs are rejected before persistence.
- File paths cannot escape the case vault.
- OCR output links each extracted field to a source document and location when available.
- OCR uncertainty is visible and blocks silent clinical confirmation.
- Synthetic PHI does not reach unauthorized logs, tools, or connectors.
- Provider correction appends a durable event without overwriting the original extraction.
- Deletion removes active document, OCR, extraction, search, export, and policy-covered backup copies.

**Deferred:** Genome file intake, external OCR, automatic clinical confirmation.

### Wave 7 — Medication and supplement research

**Owner:** Caduceus for clinical contracts; Hephaestus for adapters; Cybermage for boundary review.
**Depends on:** Waves 2–6; Gate 0.6.

**Deliverables:**

- Structured medication and supplement records.
- RxNorm normalization adapter.
- Reviewed Caduceus medication research adapter.
- Interaction cross-check findings.
- Timing/food context fields.
- Evidence/source panel.
- Review queue integration.

**Files:**

```text
packages/clinic/clinic-research/
packages/clinic/clinic-domain/src/clinical-inputs.ts
packages/clinic/clinic-domain/src/finding.ts
packages/client/ui-caduceus/src/client/findings/
packages/client/ui-caduceus/src/client/review/
```

**Acceptance criteria:**

- Known synthetic interaction fixtures produce the expected structured category.
- Ambiguous medication names require provider confirmation.
- Missing dose, route, frequency, timing, or source is visible as missing information.
- Evidence grades, citations, freshness, and uncertainty survive replay and export.
- External connectors never receive raw patient documents or full narratives.
- The UI never renders research as an instruction, prescription, diagnosis, or order.
- Tool arguments, results, approvals, and source citations are auditable.

**Deferred:** Automatic medication-list modification, EHR import, treatment execution.

### Wave 8 — Laboratory workflow

**Owner:** Caduceus and Hephaestus.
**Depends on:** Wave 7.

**Deliverables:**

- Lab PDF/image/CSV intake through the secure document pipeline.
- Structured test extraction.
- Unit normalization with explicit valid/invalid units.
- Lab-provided reference-range preservation.
- Historical trend view.
- Medication/lab relationship research.
- Uncertainty and provider-question findings.

**Files:**

```text
packages/clinic/clinic-domain/src/clinical-inputs.ts
packages/clinic/clinic-ocr/src/extraction.ts
packages/clinic/clinic-research/src/findings.ts
packages/client/ui-caduceus/src/client/workspace/
packages/client/ui-caduceus/src/client/findings/
```

If `workspace/` becomes a separate browser domain, split it into its own plugin package rather than allowing `ui-caduceus` to become a monolith.

**Acceptance criteria:**

- Valid and invalid unit conversion fixtures behave deterministically.
- Source-lab reference ranges remain attached to the result.
- Trends sort by collection time, not upload time.
- OCR uncertainty and missing context remain visible.
- Conflicting or incomplete evidence is not collapsed into a confident conclusion.
- Findings preserve source document references and provider review state.

**Deferred:** Automated diagnosis, reference-range substitution without source data, patient alerts.

### Wave 9 — Findings, review, export, and audit UI

**Owner:** Iris and Marvin; clinical acceptance by Caduceus.
**Depends on:** Waves 3, 5, 7, and 8.

**Deliverables:**

- Structured finding cards.
- Approve, reject, amend, uncertain, and request-more-research actions.
- Immutable amendment history.
- Audit history panel with event filters.
- Replay/reconstruction control for authorized reviewers.
- Approved-report export.
- Export download and deletion events.

**Files:**

```text
packages/client/ui-caduceus/src/client/findings/
packages/client/ui-caduceus/src/client/review/
packages/client/ui-caduceus/src/client/audit/
packages/client/ui-caduceus/src/client/export/
packages/clinic/clinic-audit/src/export.ts
packages/clinic/clinic-api/src/routes.ts
```

**Acceptance criteria:**

- A finding cannot be exported before required review state is satisfied.
- Approve, reject, amend, and uncertain actions require the correct role and case scope.
- An amendment preserves the original finding and records reason, actor, and time.
- Audit inspection reconstructs the selected run without exposing unauthorized cases.
- Export contains citations, grades, uncertainty, reviewer status, and freshness data.
- Export deletion is separately audited and follows retention policy.
- The browser has explicit failure and empty states for unavailable audit or export services.

**Deferred:** External sharing, patient delivery, chart write-back.

### Wave 10 — Research Pilot packaging and operational deployment

**Owner:** Hephaestus; Cybermage security sign-off; Hermes release orchestration.
**Depends on:** Waves 1–9; Phase 0 Gate 0.7.

**Deliverables:**

- Clinic-approved host image and service accounts.
- Full-disk encryption verification.
- Local model runtime installation.
- Firewall and bind configuration.
- Encrypted backup job.
- Restore procedure.
- Health checks and alerting.
- Upgrade/rollback procedure.
- Operator runbook.
- Research Pilot evidence packet.

**Files:**

```text
packages/bundle/caduceus-clinic/cordis.patch.yml
ops/caduceus-clinic/
ops/caduceus-clinic/systemd/
ops/caduceus-clinic/firewall/
ops/caduceus-clinic/backup/
ops/caduceus-clinic/runbooks/
docs/caduceus/operations.md
```

**Acceptance criteria:**

- Services bind only to the clinic-approved interface.
- Model, tokenizer, runtime, packages, and configuration provenance are recorded.
- The host restarts cleanly and the clinic profile reaches a healthy state.
- Restore succeeds on a clean test target and passes journal/storage integrity checks.
- Egress tests show no synthetic PHI leaves the approved boundary.
- Login, revocation, deletion, retention, audit integrity, and case isolation continue working after restart.
- Installation and rollback logs are attached to the evidence packet.

**Release result:** Research Pilot only unless every higher release requirement is independently satisfied.

### Wave 11 — Optional genomic/pharmacogenomic module

**Owner:** Caduceus with Cybermage and an independent clinical reviewer.
**Depends on:** All prior waves plus a separate genome data contract.

This wave is not part of the first Research Pilot release.

**Deliverables:**

- Separate high-sensitivity workspace flag.
- VCF and clinical genetic report intake.
- Variant normalization and source-version tracking.
- Approved ClinVar/CPIC/PharmGKB adapters where licensing permits.
- Pathogenicity/actionability distinction.
- Conflicting interpretation display.
- Genetic-counselor/provider escalation.

**Acceptance criteria:**

- Original genome-file digest is preserved.
- Genome data is excluded from ordinary case search unless explicitly authorized.
- Conflicting sources remain visible.
- Unsupported interpretations are marked unsupported.
- De-identification treats genomic data as high sensitivity.
- Independent clinical review signs off before any clinic pilot use.

---

## 11. Testing and evidence strategy

### 11.1 DSH checks

Run from the isolated DSH worktree and record actual output:

```sh
pnpm install
pnpm run verify-cordis-config
pnpm run verify-client-domain-graph
pnpm run typecheck
pnpm run test:gui
pnpm run test:web
pnpm run verify-package-invariants
pnpm run verify-built-package-invariants
pnpm run hygiene
pnpm run doc-sync
```

Do not run every command for every card. Select the narrowest rung that covers the changed surface, then run the assembled browser test for client-visible changes and the release ladder at wave boundaries.

### 11.2 Clinic package checks

Every new package must have:

- `package.json` with the correct DSH name and exports.
- `tsconfig.json` in the correct aggregate.
- `src/types.ts` containing types only.
- `src/invariant.ts` with a real runtime relationship or a package-specific reason.
- Package-level tests under `tests/`.
- README contract and Model Experience section where model-facing behavior exists.
- Agent Note for non-trivial architecture or product behavior.
- No bare `except:` or top-level debug `print()` in Python support scripts.

### 11.3 Clinic security tests

- Unauthenticated API access.
- Role and case authorization.
- Session fixation, expiry, and revocation.
- CSRF and origin checks.
- Path traversal and archive extraction.
- MIME, size, count, and decompression limits.
- Malicious document content.
- Prompt injection in uploaded documents.
- Cross-case and cross-provider context leakage.
- Tool escalation and alternate-caller bypass.
- Cloud/fallback/telemetry route detection.
- DNS, socket, firewall, and packet egress.
- Log, crash-dump, temp-file, and backup leakage.
- Audit tampering and replay failure.
- Restore integrity.
- Deletion and retention execution.

### 11.4 Clinical safety fixtures

Use reviewed synthetic fixtures only:

- Drug-drug interactions.
- Drug-supplement and food interactions.
- Duplicate therapies.
- Missing dose, route, frequency, and timing.
- Lab unit variation.
- Lab reference-range variation.
- Trend ordering.
- OCR uncertainty.
- Conflicting evidence.
- Unsupported claims.
- Urgent-review wording.
- Genome evidence conflicts after the genome module is separately enabled.

The acceptance target is source-grounded, uncertainty-visible, provider-reviewable behavior. It is not a particular model wording.

---

## 12. Release evidence packet

Create this directory for each Research Pilot or higher release:

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

A claim, code screenshot, or “works on my machine” note is not evidence.

---

## 13. 20-item live-PHI gate

Caduceus Clinic cannot process live PHI until all items are evidenced:

1. Clinic ownership and legal/operational role are documented.
2. Complete PHI data map exists.
3. Provider identities and roles are unique and reviewed.
4. MFA/admin access policy is active.
5. Cloud and remote inference routes are removed from PHI mode.
6. Discord and external event-bus paths are removed from PHI mode.
7. Storage and backups are encrypted.
8. Model and runtime artifacts are pinned and recorded.
9. Tool permissions are least-privilege.
10. Egress deny-by-default is proven.
11. Audit journal is append-only and tamper-evident.
12. Audit failure blocks PHI analysis.
13. Retention and deletion work end to end.
14. Restore test passes.
15. Synthetic PHI leakage tests pass.
16. Prompt-injection tests pass.
17. Clinical safety review passes.
18. Incident-response exercise passes.
19. Workforce training and access-review records exist.
20. Independent security/HIPAA review is complete.

Software delivery alone never changes the claim to “HIPAA compliant.”

---

## 14. Card-sized execution breakdown

Do not dispatch the entire plan as one task. Convert it into dependency-linked cards with one atomic change and one primary verification command.

### Foundation chain

- `C0.1` Record isolated DSH baseline.
- `C0.2` Create Caduceus worktree and branch.
- `C0.3` Write product thesis and non-goals.
- `C0.4` Write PHI data map.
- `C0.5` Write threat model.
- `C0.6` Inventory Caduceus tools.
- `C0.7` Define release evidence packet.

### Phase 0 spike chain

- `P0.1` Boot minimal clinic bundle.
- `P0.2` Prove profile dump allowlist.
- `P0.3` Prove browser boot composition.
- `P0.4` Prove encrypted persistence canary.
- `P0.5` Prove encrypted replay.
- `P0.6` Prove deletion and retention behavior.
- `P0.7` Prove auth and case isolation.
- `P0.8` Prove egress deny-by-default.
- `P0.9` Prove sanitized evidence connector.
- `P0.10` Record exact model artifact and M5 benchmark.
- `P0.11` Issue GO, PIVOT, or NO-GO decision.

### Product build chain

- `W1.1` Add clinic bundle package skeleton.
- `W1.2` Add clinic profile patch rows.
- `W1.3` Add safe tool roster policy.
- `W1.4` Add profile composition test.
- `W2.1` Add branded clinic IDs.
- `W2.2` Add case/document schemas.
- `W2.3` Add finding/review schemas.
- `W2.4` Add mode and retention policy.
- `W2.5` Add encrypted payload provider.
- `W2.6` Add metadata store.
- `W2.7` Add deletion coordinator.
- `W3.1` Add clinic session persistence provider.
- `W3.2` Add audit event envelope.
- `W3.3` Add canonical hash chain.
- `W3.4` Add replay and integrity command.
- `W4.1` Add provider identity store.
- `W4.2` Add secure browser sessions.
- `W4.3` Add role/case authorization executor.
- `W4.4` Add clinic API schemas and routes.
- `W5.1` Add client plugin package skeleton.
- `W5.2` Add case sidebar slot contribution.
- `W5.3` Add case workspace slot contribution.
- `W5.4` Add case-switching state and tests.
- `W6.1` Add bounded multipart intake.
- `W6.2` Add encrypted vault write path.
- `W6.3` Add OCR worker contract.
- `W6.4` Add extraction confirmation flow.
- `W6.5` Add de-identification preview.
- `W7.1` Add medication input schemas.
- `W7.2` Add Caduceus research adapter.
- `W7.3` Add structured interaction findings.
- `W7.4` Add evidence panel and citations.
- `W8.1` Add lab input schemas.
- `W8.2` Add unit normalization.
- `W8.3` Add reference-range preservation.
- `W8.4` Add trend projection.
- `W9.1` Add finding review state machine.
- `W9.2` Add audit history panel.
- `W9.3` Add authorized replay view.
- `W9.4` Add approved report export.
- `W10.1` Add host installation definition.
- `W10.2` Add firewall and bind verification.
- `W10.3` Add encrypted backup and restore runbook.
- `W10.4` Run Research Pilot release evidence packet.

Each card must include exact files, out-of-scope items, one verification command, and a clear dependency. Cards changing more than one architectural seam must be split.

---

## 15. Ownership and handoffs

| Area | Primary owner | Required reviewer |
|---|---|---|
| Product boundary and orchestration | Hermes | Konan |
| DSH/Cordis profile and host integration | Hephaestus | Hermes |
| Clinical methodology and fixture truth | Caduceus | Independent clinical reviewer before live PHI |
| Medical source/tool adapter | Caduceus + Hephaestus | Cybermage |
| UI design and visual QA | Iris | Hermes |
| Client implementation | Marvin | Iris + Hephaestus |
| HIPAA/security gates | Cybermage | Independent security reviewer |
| Model/runtime/M5 operations | Hephaestus | Cybermage |
| Evidence and source verification | Thoth | Caduceus |

No handoff is complete without an artifact path, evidence output, and explicit next dependency.

---

## 16. Definition of done

### Research Pilot done

A provider can log into the clinic-local WebUI, create or select an opaque synthetic/de-identified case, upload and confirm medical documents, use the approved Caduceus research capability, receive cited structured findings, review or amend them, export an approved local report, and reconstruct the model/tool/review history.

The Research Pilot does this without an EHR, patient-facing route, cloud inference, Discord, external A2A, uncontrolled MCP, unrestricted shell, or unapproved PHI retention path.

### Live-PHI ready for independent review

All Research Pilot behavior works, all 20 gates have executed evidence, the clinic owns its risk analysis and operating procedures, clinical safety has been reviewed, and an independent HIPAA/security reviewer has received the complete evidence packet.

### Never acceptable

- Calling the hardware HIPAA compliant.
- Calling the model HIPAA compliant.
- Calling DSH/Cordis HIPAA compliant by inheritance.
- Calling the software HIPAA-compliant production before independent review.
- Treating local inference as proof that PHI cannot escape.
- Treating an append-only log as safe if it retains plaintext PHI forever.

---

## 17. Immediate execution order

1. Approve this plan as the build contract.
2. Create the isolated DSH worktree without touching unrelated dirty files.
3. Execute Phase 0 gates in order, parallelizing only independent probes.
4. Stop on a critical gate failure; issue PIVOT or NO-GO with floor value.
5. If Phase 0 is GO, build Waves 0–4 before deep clinical UI work.
6. Ship the first Research Pilot only after the evidence packet is complete.
7. Treat genome, EHR, patient messaging, and live PHI as later gated work.

**No implementation card is dispatched until Phase 0 and this plan are approved.**

---

## 18. Source anchors

- DSH root rules: `/home/konan/workspace/deepseek-harness/AGENTS.md`.
- DSH package rules: `/home/konan/workspace/deepseek-harness/packages/AGENTS.md`.
- DSH client rules: `/home/konan/workspace/deepseek-harness/packages/client/AGENTS.md`.
- DSH documentation rules: `/home/konan/workspace/deepseek-harness/docs/AGENTS.md`.
- DSH architecture: `/home/konan/workspace/deepseek-harness/docs/architecture.md`.
- DSH web entry: `/home/konan/workspace/deepseek-harness/apps/web/src/main.ts`.
- DSH web boot: `/home/konan/workspace/deepseek-harness/packages/client/web/src/boot.tsx`.
- DSH shell assembly: `/home/konan/workspace/deepseek-harness/packages/client/web/src/app-shell.ts`.
- DSH web bundle: `/home/konan/workspace/deepseek-harness/packages/bundle/web-app/cordis.patch.yml`.
- DSH base bundle: `/home/konan/workspace/deepseek-harness/packages/bundle/base/cordis.patch.yml`.
- DSH session persistence interface: `/home/konan/workspace/deepseek-harness/packages/session/session-persistence/src/index.ts`.
- DSH host API gateway: `/home/konan/workspace/deepseek-harness/packages/host/apiproxy`.
- Caduceus role and medical methodology: `/home/konan/.hermes/profiles/caduceus/SOUL.md`.
- Security white paper: `/home/konan/pantheon/docs/security/CADUCEUS-CLINIC-SECURITY-HIPAA-WHITEPAPER.md`.
- Build assurance checklist: `/home/konan/pantheon/docs/plans/caduceus-clinic-build-assurance-checklist.md`.
- HIPAA review method: `/home/konan/.hermes/skills/security/hipaa-ai-system-review/SKILL.md`.
