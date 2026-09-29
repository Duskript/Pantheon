# Person Roots — Build Gates

**Status:** Draft v0.1  
**Date:** 2026-08-06  
**Companion docs:** `PERSON_ROOTS_THESIS.md`, `PERSON_ROOTS_SCHEMA.md`, `PERSON_ROOTS_PRIVACY_ACL.md`

---

## 1. Definition of done

A Person Roots build wave is not done until it has:

1. Created or modified the intended files only.
2. Passed structural validation.
3. Preserved privacy defaults.
4. Produced evidence that ACL rules behave as expected.
5. Updated the relevant index/docs.
6. Reported all caveats and open questions.

---

## 2. Wave gates

### Gate 1 — Canon structure exists

Required evidence:

- `~/athenaeum/Codex-User/relationships/INDEX.md` exists.
- Seed folders exist for Tallon, Fia, Xander, Finn, Amber, and Sydney.
- Every seed folder contains required base files.
- Direct user seeds contain the direct-user extras only when marked `direct_user: true`.

Verification command shape:

```bash
python3 ~/pantheon/scripts/validate-person-roots.py --root ~/athenaeum/Codex-User/relationships
```

Expected: `PASS` with counts.

### Gate 2 — Schema validity

Required evidence:

- Every markdown file has YAML frontmatter.
- `person_id` matches folder slug.
- `document_type` is in allowed enum.
- `sensitivity` is in allowed enum.
- `trust_tier` is valid when present.

Expected: zero validation errors.

### Gate 3 — Privacy defaults

Required evidence:

- `RELATIONSHIP_TO_KONAN.md` defaults to `shareable_by_default: false`.
- `PERMISSIONS.md` exists for each seed person.
- Sensitive/private files are not marked `public` unless explicitly intended.
- Xander's permission file denies Pantheon private repos by default.
- Fia's permission file denies business/client secrets by default.

### Gate 4 — Account linking is explicit

Required evidence:

- Account links are empty or marked pending unless verified.
- No Discord user ID is invented.
- The index distinguishes `pending` vs `verified` account links.

### Gate 5 — ACL evaluator contract

When implemented, test cases must cover:

| Scenario | Expected |
|---|---|
| Konan reads any person root | allow |
| Unknown user asks about Konan private relationship notes | deny |
| Xander asks for Marvin review of Xander-submitted code | allow |
| Xander asks for Pantheon private repo context | deny |
| Fia asks for her own Pantheon help | allow |
| Fia asks for private notes about another person | deny or needs Konan approval |
| Kairos drafts public post using family-sensitive fact | needs Konan approval |

### Gate 6 — Runtime god integration

When implemented, every god retrieval path must call the resolver + ACL before loading person-root content.

Required evidence:

- Unit tests for resolver.
- Unit tests for ACL.
- Integration smoke test where a god mention of `Xander` loads only allowed context.
- Negative test where a non-authorized user cannot retrieve Konan private notes.

### Gate 7 — Fusion build verification

For fusion-mode implementation tasks:

- Planner performs prerequisite inspection.
- Executor receives a strict Spec Contract.
- Executor reports `STATUS / CHANGES / VERIFIED / GAPS`.
- Planner independently reviews filesystem changes.
- Planner runs the smallest meaningful verification command.

A self-report without planner verification is not accepted.

---

## 3. Acceptance criteria by milestone

### Milestone A — Documentation pack

- [ ] All five planning docs exist under `/home/konan/pantheon/plans/person-roots/`.
- [ ] Docs agree on terminology: Person Roots, relationship folders, direct-user roots, source authority, trust tiers.
- [ ] Xander's lane is correctly scoped as "Marvin reviews Xander's own code," not Pantheon code review.
- [ ] The fusion executor route is documented as DeepSeek V4 Flash, not Marvin by default.

### Milestone B — Schema/template implementation

- [ ] `relationships/INDEX.md` created.
- [ ] Seed person folders created.
- [ ] Required files created with YAML frontmatter.
- [ ] Validator script created.
- [ ] Validator passes against the seed tree.

### Milestone C — ACL library

- [ ] Trust tier enum implemented.
- [ ] Sensitivity enum implemented.
- [ ] Source authority rules implemented.
- [ ] ACL evaluator returns `allow | deny | needs_konan_approval`.
- [ ] Tests cover the table in Gate 5.

### Milestone D — Extraction/proposal flow

- [ ] Konan-authored simple relationship facts can create suggested updates.
- [ ] Sensitive facts become pending approvals unless explicitly safe.
- [ ] Non-Konan-authored statements cannot overwrite Konan relationship canon.
- [ ] Account links require explicit verification.

### Milestone E — God runtime integration

- [ ] Resolver can map aliases to person IDs.
- [ ] Gods retrieve person-root content only through ACL.
- [ ] Kairos public-brand use is restricted to public-approved canon.
- [ ] Marvin Xander code-roast lane loads only Xander-safe context.

---

## 4. Regression blockers

Do not merge a build that:

- creates account IDs from guesses;
- marks private/sensitive relationship files public by default;
- allows non-Konan accounts to rewrite Konan canon;
- exposes one person's private profile to another without permission;
- treats Xander as a Pantheon repo reviewer by default;
- adds runtime automation before schema + ACL are validated;
- edits Hermes/Pantheon auth secrets or Discord tokens as part of this feature.

---

## 5. Evidence standard

Every closeout must include:

- exact files created/modified;
- validator output;
- relevant test output;
- any skipped/deferred gates;
- unresolved privacy decisions;
- whether runtime integration is enabled or documentation-only.

No vibes. Receipts or it didn't happen.
