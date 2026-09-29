# Person Roots — Fusion Build Plan

**Status:** Draft v0.1  
**Date:** 2026-08-06  
**Planner:** Hermes  
**Default executor:** DeepSeek V4 Flash through Hermes `delegate_task` / fusion-mode delegation route  
**Named-god exception:** Use Marvin only when the task requires Marvin's persona/domain, especially Xander's code-roast workflow.

---

## 1. Fusion mode contract

Fusion mode for this build means:

- Hermes owns product reasoning, architecture, Spec Contracts, and final review.
- DeepSeek V4 Flash executes bounded coding tasks via delegation.
- Executor does not commit or push.
- Hermes independently verifies changes before reporting done.
- Marvin is not the default executor for this system build.

Current verified executor route from session:

```yaml
delegation:
  provider: opencode-go
  model: deepseek-v4-flash
  base_url: ''
  api_key: ''
  api_mode: ''
```

---

## 2. Build waves

### Wave 0 — Spec doc pack

**Goal:** Lock thesis, privacy ACL, schema, gates, and build order.

**Files:**

- `/home/konan/pantheon/plans/person-roots/PERSON_ROOTS_THESIS.md`
- `/home/konan/pantheon/plans/person-roots/PERSON_ROOTS_PRIVACY_ACL.md`
- `/home/konan/pantheon/plans/person-roots/PERSON_ROOTS_SCHEMA.md`
- `/home/konan/pantheon/plans/person-roots/PERSON_ROOTS_BUILD_GATES.md`
- `/home/konan/pantheon/plans/person-roots/PERSON_ROOTS_FUSION_BUILD_PLAN.md`

**Exit gate:** Konan approves the doc pack or requests edits.

### Wave 1 — Schema + seed tree

**Goal:** Create the alpha Person Roots filesystem structure and templates.

**Target root:**

```text
/home/konan/athenaeum/Codex-User/relationships/
```

**Create:**

```text
INDEX.md
_templates/
  PROFILE.md
  RELATIONSHIP_TO_KONAN.md
  ALIASES.md
  PERMISSIONS.md
  MEMORY_POLICY.md
  INTERACTION_LOG.md
  NOTES.md
  ROOT.md
  PREFERENCES.md
  RELATIONSHIP.md
  PROJECT.md

tallon/
fia/
xander/
finn/
amber/
sydney/
```

**Seed rules:**

- Tallon: high-confidence from existing canon.
- Fia: high-confidence, direct Discord access noted, account link pending.
- Xander: medium-confidence, direct user planned for code-roast lane.
- Finn: low-medium confidence, alias Finnegan/Finn.
- Amber: medium confidence from skill-specific context.
- Sydney: low confidence stub unless more source context is found.

**Verification:** validator passes.

### Wave 2 — Validator

**Goal:** Add a structural validator script for Person Roots.

**Likely file:**

```text
/home/konan/pantheon/scripts/validate-person-roots.py
```

**Checks:**

- root exists;
- index exists;
- person folders exist;
- required files exist;
- YAML frontmatter parses;
- `person_id` matches folder;
- document/sensitivity/trust-tier enums are valid;
- direct users have direct-user required files.

**Verification command:**

```bash
python3 /home/konan/pantheon/scripts/validate-person-roots.py --root /home/konan/athenaeum/Codex-User/relationships
```

Expected output includes `RESULT: PASS`.

### Wave 3 — ACL evaluator library

**Goal:** Implement source authority + trust tier + domain permission evaluation.

**Likely files:**

```text
/home/konan/pantheon/lib/person_roots/__init__.py
/home/konan/pantheon/lib/person_roots/schema.py
/home/konan/pantheon/lib/person_roots/acl.py
/home/konan/pantheon/tests/test_person_roots_acl.py
```

**Core interface:**

```python
def evaluate_access(request: AccessRequest, root: PersonRoot) -> AccessDecision:
    ...
```

**Decision enum:**

```python
allow | deny | needs_konan_approval
```

**Verification:** pytest covers gate matrix from `PERSON_ROOTS_BUILD_GATES.md`.

### Wave 4 — Resolver + account linker

**Goal:** Resolve aliases and platform accounts to person IDs.

**Likely files:**

```text
/home/konan/pantheon/lib/person_roots/resolver.py
/home/konan/pantheon/lib/person_roots/accounts.py
/home/konan/pantheon/tests/test_person_roots_resolver.py
```

**Examples:**

- `Alexander` → `xander`
- `Xander` → `xander`
- `Finnegan` → `finn`
- `Finn` → `finn`
- `digitalon` → `tallon`

**Verification:** alias tests + pending/verified account link tests.

### Wave 5 — Extraction/proposal flow

**Goal:** Propose relationship updates from conversation snippets without unsafe auto-canonization.

**Likely files:**

```text
/home/konan/pantheon/lib/person_roots/extract.py
/home/konan/pantheon/lib/person_roots/proposals.py
/home/konan/pantheon/tests/test_person_roots_proposals.py
```

**Rules:**

- Konan-authored low-risk relationship facts can become draft updates.
- Sensitive facts require approval.
- Non-Konan-authored statements become suggestions only.
- Public/web data never updates private profiles.

### Wave 6 — God integration hooks

**Goal:** Let gods resolve person names and retrieve allowed context only.

**Scope:** Not first implementation slice. Requires careful integration with Hermes/Pantheon runtime.

**Rules:**

- Any god answering about a known person must use resolver + ACL.
- Handoffs preserve request person/purpose/context domain.
- Kairos gets public-brand-safe canon only.
- Marvin gets Xander-safe code-roast context only.

### Wave 7 — Dashboard/admin UI

**Goal:** Admin surface for trust tiers, account links, pending approvals, and profile diffs.

**Scope:** Later. Do not build until schema + ACL + resolver are proven.

---

## 3. First executor Spec Contract

Use this when Konan approves Wave 1 implementation.

```text
IMPLEMENT: Person Roots seed schema tree and validator foundation.

Objective:
Create the alpha Person Roots filesystem structure under `/home/konan/athenaeum/Codex-User/relationships/` plus a validator script. This is schema-only; do not wire runtime extraction, god prompts, Discord, or dashboard UI.

Files:
- Create `/home/konan/athenaeum/Codex-User/relationships/INDEX.md`
- Create `/home/konan/athenaeum/Codex-User/relationships/_templates/*.md`
- Create seed folders: `tallon`, `fia`, `xander`, `finn`, `amber`, `sydney`
- Create required markdown files in each seed folder per `PERSON_ROOTS_SCHEMA.md`
- Create `/home/konan/pantheon/scripts/validate-person-roots.py`

Interfaces:
- Validator CLI: `python3 scripts/validate-person-roots.py --root <relationships-root>`
- Validator output must end with `RESULT: PASS` or `RESULT: FAIL`
- Validator must return exit code 0 on pass, nonzero on fail

Constraints:
- Do not invent Discord/Telegram account IDs.
- Do not mark sensitive/private files public by default.
- Do not edit Hermes config, Discord config, auth files, or god SOUL.md files.
- Do not implement runtime extraction or god retrieval hooks.
- Do not commit or push.
- Keep files markdown + YAML frontmatter only.

Verification:
- Run `python3 /home/konan/pantheon/scripts/validate-person-roots.py --root /home/konan/athenaeum/Codex-User/relationships`
- Expected: exit 0 and output includes `RESULT: PASS`
- Run `python3 -m py_compile /home/konan/pantheon/scripts/validate-person-roots.py`
- Expected: exit 0

Return exactly:
STATUS: complete | partial | blocked | escalate
CHANGES:
VERIFIED:
GAPS:
```

---

## 4. Open decisions before implementation

1. Should Wave 1 seed real known details from current master prompt/user.md, or create mostly stubs and let Konan fill them in later?
2. Should `sydney/` be created as a low-confidence stub now, or wait until Konan gives explicit relationship context?
3. Should Fia's Discord access be represented as `pending` account link until her exact Discord user ID is verified?

Recommended defaults:

1. Seed safe, already-canon facts only.
2. Create `sydney/` as a low-confidence stub because Konan named Sydney in the target list.
3. Mark all account links pending unless exact IDs are verified.
