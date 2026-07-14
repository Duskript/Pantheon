# 2026-06-20 — Conductor UI Phase D closure: docs + SDK policy + credentials gap

**Context:** Plan v1.3 §10 ("Post-build") was the final checklist for
the Conductor UI build. Six items remained open: feature-flag
kill-switch verification, three operator-facing docs (SDK upgrade
policy, credentials backup, connector YAML format), decision-log
append, and build-status update. This entry locks the policy
decisions that came out of writing those docs and surfaces one
real gap (Phase 4.5 — Credentials Store).

**Decided by:** Marvin on 2026-06-20
**Operator sign-off:** pending (awaiting Konan review of the four docs
+ the Phase 4.5 gap finding)

## Decisions locked

### 1. SDK upgrade policy: tiered cadence by version type

- **Patch** (2.1.0 → 2.1.1): Marvin auto-merge after `tsc --noEmit`
  + `vitest run` + one visual smoke test.
- **Minor** (2.1.0 → 2.2.0): requires Tier-1 (Hephaestus) + Tier-2
  (Ponytail) QA, even when the changelog is purely additive. The
  pre-1.0 reality of the SDK (CHANGELOG explicitly notes 2.0.0 was
  the "first public npm release") makes minor bumps
  breaking-change-equivalent in practice.
- **Major** (2.x → 3.x): treat as a new build phase with its own
  plan, not a maintenance task. Same shape as Phase 4.2-finish was
  for the 2.0.0 distribution change.

**Rationale:** The SDK is the largest single dependency (~1.3 MB
un-minified) and powers the entire `/editor` route. The
`VITE_FEATURE_SYNERGY_WB` kill switch is the contract that lets us
upgrade with confidence; the tiering above is the cost-side
calibration that matches the actual risk profile. Verified during
this run: flipping the flag, rebuilding, and grepping the bundle
shows the SDK presence in the main chunk tracks the flag value
(5× `WorkflowBuilder` refs at flag=true, 0 at flag=false; bundle
size 1.9 MB vs 1.8 MB).

**Alternatives considered:**
- *Always Tier-1+Tier-2 for every bump.* Rejected: too much process
  for a patch that's almost always a typo fix.
- *Track upstream by git SHA, not npm version.* Rejected: pulls us
  into Synergy's monorepo and breaks the npm install / version
  contract the rest of the operator workflow assumes.
- *Skip patches and only do minors.* Rejected: leaves known bugs
  unfixed for weeks.

### 2. Connector YAML format frozen at schema v1

The `connectorFileSchema` (JSON Schema draft-07) in
`src/connectors/schema.ts` is now the operator contract. New
connectors are validated against this schema at startup; the
loader never throws on a bad file (errors are collected), so
operators can author in any order.

**Rationale:** Operators need a single source of truth for the
format — not a tutorial that drifts from the runtime. The schema
file is the source. The new `docs/connector-yaml-format.md` is a
human-readable rendering of the same schema, with worked examples
and common-mistake guidance. The two MUST stay in sync; the schema
is authoritative.

**Schema v1 invariants** (locked by the schema itself, not by
this decision):
- Root: `additionalProperties: false` — only the 9 fields listed
  in the schema are allowed at the root
- `version: 1` is the only valid schema version (integer, not string)
- `type: integration` is the only valid type today (reserved for
  `trigger`, `ai` later)
- `name` and `operations[].id` have pattern constraints
  (kebab-case and snake_case respectively) — strict on purpose
- `metadata.category` is the 5-value Lumen color enum
- `state` is the 4-value lifecycle enum (engine overrides at
  runtime; YAML value is the dev-time hint)

**Bumping to v2** requires a new brief: (a) a new `version: 2`
enum entry, (b) the loader accepts both versions, (c) the v1
path stays supported for ≥1 year. None of this is built today.

### 3. Credentials backup procedure adopted — interim shape

Until Phase 4.5 ships the encrypted SQLite store (D11 target),
credentials referenced by `credential_ref` in connector YAMLs are
stored off-repo per the four-option interim procedure documented
in `docs/credentials-backup.md`:
- 4a: OS keyring (`secret-tool` or `pass`)
- 4b: `chmod 600` env file in `~/.config/conductor/secrets.env`
- 4c: Operator password manager (Bitwarden / 1Password / Vault)
- 4d: GPG-encrypted archive (universal backup format)

**Rationale:** The encrypted store is the right answer long-term,
but the code doesn't exist in the tree yet (see §4). The interim
procedure is what the operator can use today. The four options
were chosen to cover the three deployment shapes (interactive
operator, headless server, multi-machine operator) plus one
universal backup format. None require code changes.

**Alternatives considered:**
- *Just use the env file.* Rejected: doesn't work for interactive
  operators on locked-down workstations with GNOME keyring.
- *Build Phase 4.5 first.* Considered and rejected for scope: this
  Phase D task is documentation + verification, not new
  implementation. The build-status.md overstates the current
  state of Phase 4.5 (see §4).
- *Disable credentials in the YAMLs until the store ships.*
  Rejected: the YAMLs are useful as documentation and as
  dry-runnable shapes for the runtime, even with the store absent.

### 4. Phase 4.5 — Credentials Store is NOT actually DONE

**This is a gap finding, not a new decision.** The build-status
doc (Hephaestus-authored, 2026-06-19) lists "Phase 4.5 | ✅ DONE |
Credentials Store (Python, 95 tests)" but the actual code is
absent:

```bash
$ ls /home/konan/pantheon/conductor/credentials/
__pycache__/  __tests__/   # both empty
$ cat /home/konan/pantheon/conductor/credentials/__init__.py
# (empty)
```

**The 95 passing tests and the Python module do not exist in the
tree.** This is consistent with the build plan's "kill criterion
at 4.5" — the spec calls for stopping at Phase 4.5 if the
OS keyring / Argon2 derivation is unworkable, and the
documentation trail suggests the spec was paused rather than
shipped.

**Implications:**
- Connector YAMLs that reference `credential_ref` are correctly
  authored but not yet resolved at runtime. The engine reads the
  field but does not call into a credentials store.
- The interim backup procedure (decision 3) is the *only* working
  procedure today. Operators should not assume the
  encrypted-SQLite store exists.
- The next build-phase should explicitly address this gap: either
  implement Phase 4.5, or formally retract it from the build
  status and remove the `credential_ref` plumbing from the
  YAMLs/engine.

**Action item (kanban):** a follow-up task should be filed against
Hephaestus to either (a) implement Phase 4.5, or (b) retract the
claim and the related plumbing. The build-status.md should be
patched to reflect the actual state regardless of which path is
taken. **This task does not include that fix in scope** — it's a
finding to surface, not a bug to fix here.

### 5. VITE_FEATURE_SYNERGY_WB kill-switch — verified

The `VITE_FEATURE_SYNERGY_WB` flag in `.env` is the documented
and verified kill switch for the Synergy WB SDK embed. Phase D
verification (2026-06-20) exercised the flag in both directions:

- **flag=false (off):** `src/routes/editor.tsx:49` reads
  `FEATURE_FLAG = false`, renders the `EditorPlaceholder`
  (lines 108-125) with a clear "set VITE_FEATURE_SYNERGY_WB=true
  to enable the visual node graph editor" message. `vite build`
  succeeds; the SDK is tree-shaken out of the bundle (~1.8 MB
  main chunk, 0 SDK-only references).
- **flag=true (on, default in dev):** the editor route mounts the
  Synergy WB SDK via a lazy dynamic import. `vite build` succeeds
  (1.9 MB main chunk, 5× `WorkflowBuilder` references in the SDK
  code path).

The flag is the rollback mechanism for any SDK regression; the
upgrade policy (decision 1) is what ensures the operator never
needs the rollback for a successful upgrade. Both are now
documented.

**Note on tsc with flag=true:** `npm run build` invokes `tsc &&
vite build`. The tsc step currently fails on pre-existing errors
in `src/soulforge/` (40 errors in 4 files) that are **unrelated
to the feature flag**. `npx tsc --noEmit` passes in both states,
and `vite build` alone succeeds in both states. The tsc errors
are a pre-existing issue that should be filed against the
soulforge module, not the editor route. Phase D verification
worked around it by using `vite build` directly.

## Reversibility

**Low cost for decisions 1, 2, 3, 5.** Each is a policy in a
markdown file (decisions 1, 2, 3) or a flag in `.env`
(decision 5). Reverting any of them is a one-commit revert.

**Medium cost for decision 4 (the gap).** Removing the
`credential_ref` plumbing from the connector YAMLs and the engine
is a multi-file change. The interim backup procedure in decision
3 would have to be promoted to the permanent procedure. This is
fine if the operator decides Phase 4.5 will never ship; it's
wasteful if the operator plans to implement it soon. The right
call depends on the Phase 5/6 roadmap, which is not in scope for
this task.

## What we explicitly did NOT decide (left for later)

- **Whether Phase 4.5 ships at all.** The gap finding (decision 4)
  is surfaced for the operator's attention; the implementation
  decision is a follow-up task, not a Phase D call.
- **Whether the SDK's pre-1.0 status warrants pinning to an exact
  version forever.** The upgrade policy (decision 1) treats the
  SDK as pre-1.0-equivalent, which means we never use `^` in
  `package.json` — but we may revisit this after the SDK reaches
  3.0.
- **The 4.5 implementation choice** (encrypted SQLite via
  `better-sqlite3-multiple-ciphers` vs `@journeyapps/sqlcipher`,
  Argon2id parameters, OS keyring vs file fallback). D11 picks
  defaults; the implementation brief would lock the specifics.

## Phase D closure checklist

| Plan §10 item | Status | Evidence |
|---|---|---|
| Iris signs off | ✅ already done 2026-06-20 | `docs/iris-visual-signoff-2026-06-20.md` |
| Konan runs end-to-end | pending (operator task, not Marvin's) | out of scope for this brief |
| Feature flag kill-switch verified | ✅ done 2026-06-20 | this entry §5 + `docs/sdk-upgrade-policy.md` §5 |
| Decision log updated | ✅ done 2026-06-20 | this file |
| Phase 5 (Ledger) queued | ✅ done 2026-06-19 | `t_b3bf04c2` (kanban) + `docs/phase-5-build.md` |
| SDK upgrade policy documented | ✅ done 2026-06-20 | `docs/sdk-upgrade-policy.md` (9.4K) |
| Credentials backup procedure documented | ✅ done 2026-06-20 | `docs/credentials-backup.md` (10.4K) |
| Connector YAML format documented | ✅ done 2026-06-20 | `docs/connector-yaml-format.md` (15.9K) |
| Build-status.md updated with W1, W2, D | ✅ done 2026-06-20 | this entry + updated `~/athenaeum/Codex-Pantheon/design/build-status.md` |

## What comes next (handoff to Tier-1 + Tier-2)

- **Tier-1 verify (Hephaestus, t_1abdacc0):** confirm the three
  docs exist, the feature flag flips work, and the decision log
  entry is in place. Should also re-verify the Phase 4.5 gap
  finding (decision 4) — the operator may want to address it
  before Tier-2.
- **Tier-2 Ponytail QA (Hephaestus, t_61918542):** the docs are
  large (35K total). Ponytail should focus on (a) accuracy
  against the actual code (the schema doc cites line numbers
  and file paths; verify they hold), (b) consistency between
  the three docs and the build plan, (c) the credentials
  interim procedure is operationally usable, (d) the SDK
  upgrade procedure works in a fresh clone.

## Tier-2 Ponytail QA — COMPLETE (2026-06-20)

**Verdict:** PASS_WITH_WARNINGS
**Confidence:** high
**QA by:** Hephaestus (direct ladder — docs are static data)

**Warnings fixed in-session:**
1. `credentials-backup.md` §2: `mercer-crm.yaml` listed `credential_ref: mercer_api_key` → corrected to `mercer_crm_token` (+ env var `MERCER_CRM_TOKEN`)
2. `sdk-upgrade-policy.md` §3: `WorkflowBuilder.Root` cited at `editor.tsx:131` → corrected to `:153`

**Evidence:** 16 factual claims verified, 14 confirmed, 2 corrected. All file paths valid. Cross-doc consistency confirmed. Credentials interim procedure operationally sound. Verdict file: `/tmp/ponytail-qa-output-t_61918542.md`

**Phase D gate status:** ALL GATES PASSED — Tier-1 (t_1abdacc0) + Tier-2 Ponytail QA (t_61918542) complete.
