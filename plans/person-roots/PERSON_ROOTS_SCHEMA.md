# Person Roots — Schema Contract

**Status:** Draft v0.1  
**Date:** 2026-08-06  
**Companion docs:** `PERSON_ROOTS_THESIS.md`, `PERSON_ROOTS_PRIVACY_ACL.md`

---

## 1. Canonical root

Alpha root:

```text
~/athenaeum/Codex-User/relationships/
```

This directory contains one folder per person plus an `INDEX.md`.

---

## 2. Folder naming

Folder names use stable lowercase slugs:

- `tallon/`
- `fia/`
- `xander/`
- `finn/`
- `amber/`
- `sydney/`

Rules:

1. Use the common name Konan uses most often unless there is a collision.
2. Put legal/full names in frontmatter, not folder names.
3. Aliases go in `ALIASES.md` and `PROFILE.md` frontmatter.
4. Renames require an index update and redirect note.

---

## 3. Directory structure

### 3.1 Mentioned or relationship-only person

```text
relationships/<person>/
  PROFILE.md
  RELATIONSHIP_TO_KONAN.md
  ALIASES.md
  PERMISSIONS.md
  MEMORY_POLICY.md
  INTERACTION_LOG.md
  NOTES.md
```

### 3.2 Direct Pantheon user

A direct user adds:

```text
relationships/<person>/
  ROOT.md
  PREFERENCES.md
  RELATIONSHIPS/
    konan.md
  PROJECTS/
    <project>.md
```

The folder matures in place. Do not move it during promotion.

---

## 4. `INDEX.md` schema

`relationships/INDEX.md` is the resolver entrypoint.

Required sections:

```markdown
# Person Roots Index

## Resolver Table
| Person ID | Display Name | Aliases | Direct User | Trust Tier | Folder | Notes |
|---|---|---|---|---|---|---|

## Account Links
| Platform | Account ID | Person ID | Status | Verified By | Notes |
|---|---|---|---|---|---|

## Pending Approvals
| Date | Person ID | Change | Reason | Requested By | Status |
|---|---|---|---|---|---|
```

---

## 5. Frontmatter base fields

Every markdown file in a person root must have YAML frontmatter.

Minimum fields:

```yaml
person_id: xander
document_type: profile
schema_version: 0.1
status: draft
created: 2026-08-06
updated: 2026-08-06
source_authority: konan
sensitivity: private
```

Allowed `document_type` values:

- `index`
- `profile`
- `relationship_to_konan`
- `aliases`
- `permissions`
- `memory_policy`
- `interaction_log`
- `notes`
- `root`
- `preferences`
- `relationship`
- `project`

Allowed `sensitivity` values:

- `public`
- `basic`
- `private`
- `sensitive`
- `secret`

---

## 6. `PROFILE.md`

Purpose: identity basics and low-level description.

Template:

```markdown
---
person_id: xander
document_type: profile
schema_version: 0.1
status: draft
created: 2026-08-06
updated: 2026-08-06
source_authority: konan
sensitivity: private
display_name: Xander
full_name: Alexander
aliases:
  - Alexander
  - Xander
direct_user: true
trust_tier: tier_2_collaborator
---

# Xander — Profile

## Summary

Short factual summary.

## Known context

- Relationship to Konan: son.
- Primary Pantheon use case: Marvin code-roast / learning lane.

## Source notes

- 2026-08-06: Konan clarified Xander's planned access is for Marvin to review Xander's own code, not Pantheon code.
```

---

## 7. `RELATIONSHIP_TO_KONAN.md`

Purpose: Konan-perspective relationship record.

This file is not automatically visible to the person.

Template:

```markdown
---
person_id: xander
document_type: relationship_to_konan
schema_version: 0.1
status: draft
source_authority: konan
sensitivity: sensitive
perspective_owner: konan
shareable_by_default: false
---

# Relationship to Konan

## Relationship

Son.

## What Konan has said

- ...

## Shareability

- Public-safe: no, unless explicitly approved.
- Direct-user-safe: limited fields only.
```

---

## 8. `PERMISSIONS.md`

Purpose: trust tier, account links, allowed/denied context.

Template:

```markdown
---
person_id: xander
document_type: permissions
schema_version: 0.1
status: draft
source_authority: konan
sensitivity: private
trust_tier: tier_2_collaborator
---

# Permissions

## Account links

```yaml
account_links:
  discord:
    user_ids: []
  telegram:
    user_ids: []
```

## Allowed context

- code_submitted_by_xander
- xander_project_history
- general_programming_guidance
- marvin_roast_coach_mode

## Denied context

- pantheon_private_repos
- konan_private_relationship_notes
- business_client_data
- god_system_config
- other_people_private_profiles
```

---

## 9. `ROOT.md`

Purpose: direct user's own root. Exists only after promotion.

Template:

```markdown
---
person_id: xander
document_type: root
schema_version: 0.1
status: draft
source_authority: self_and_konan
sensitivity: private
direct_user: true
admin_owner: konan
---

# Xander — Pantheon Root

## What Pantheon should help with

- Code review and learning.

## Preferred style

- Constructive, direct, funny code critique.

## Active projects

- `PROJECTS/code-roast.md`
```

---

## 10. `MEMORY_POLICY.md`

Purpose: what can be captured automatically.

Required sections:

- Auto-capture allowed.
- Auto-capture denied.
- Requires approval.
- Retention notes.
- Sharing notes.

Default policy:

```yaml
auto_capture:
  allowed:
    - self_stated_preferences
    - submitted_project_context
    - explicit_relationship_facts_from_konan
  denied:
    - secrets
    - private facts about third parties from non-authoritative speakers
    - sensitive health/religion/relationship details unless explicit
  requires_approval:
    - trust_tier_changes
    - account_links
    - cross-person sensitive facts
```

---

## 11. Seed person folders for alpha

Create seed folders for:

- `tallon/`
- `fia/`
- `xander/`
- `finn/`
- `amber/`
- `sydney/`

Known data levels:

| Person | Seed confidence | Notes |
|---|---:|---|
| Tallon | high | Existing canon has relationship/work/Pantheon context. |
| Fia | high | Existing canon has relationship/Pantheon context; direct Discord access noted by Konan. |
| Xander | medium | Konan clarified code-roast lane; account link pending. |
| Finn | low-medium | Known as Finnegan/Finn, one of Konan's boys; more detail needed. |
| Amber | medium | Existing skill-specific context; relationship to Konan needs clearer category. |
| Sydney | low | Mentioned by Konan; create stub unless more context is available. |

---

## 12. Validation script requirements

A future validator should check:

1. `relationships/INDEX.md` exists.
2. Every person folder listed in index exists.
3. Each person folder has required base files.
4. Every markdown file has YAML frontmatter.
5. `person_id` matches folder slug.
6. `document_type` is allowed.
7. `trust_tier` is valid when present.
8. `sensitivity` is valid.
9. Account links are syntactically valid lists/maps.
10. Direct users have `ROOT.md`, `PREFERENCES.md`, and `MEMORY_POLICY.md`.
