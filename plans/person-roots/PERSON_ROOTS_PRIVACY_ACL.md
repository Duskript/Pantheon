# Person Roots — Privacy & ACL Contract

**Status:** Draft v0.1  
**Date:** 2026-08-06  
**Companion docs:** `PERSON_ROOTS_THESIS.md`, `PERSON_ROOTS_SCHEMA.md`, `PERSON_ROOTS_BUILD_GATES.md`

---

## 1. Privacy doctrine

The Person Roots layer must enforce this rule:

> **Pantheon may know more than it shares. Retrieval is permissioned by speaker, account, person, purpose, and channel.**

The system should get to know each person individually, but it must not leak one person's private context into another person's session.

---

## 2. Source authority

Source authority determines whether a statement can create/update canon.

| Source | Authority |
|---|---|
| Konan account | Authoritative for Konan canon, relationship-to-Konan records, admin decisions, sharing permissions. |
| Direct user account | Authoritative for that user's own preferences/profile, within their scope. |
| Trusted contact/family account | May update their own profile and suggest relationship updates. Does not overwrite Konan's private view. |
| Pantheon god/subagent | May propose updates based on observed interactions. Must not canonize sensitive facts without a rule or approval. |
| Public web/social data | Never authoritative for private relationship profile facts. |

### 2.1 Konan-only automapping

Relationship/profile automapping for Konan's private canon only auto-applies when the source message is from a verified Konan account.

If the message comes from Fia, Xander, Amber, Tallon, or another user, the system may:

- link that account to the matching person profile;
- update that person's self-profile/preferences within allowed scope;
- create a suggested update for Konan's view;
- request Konan approval for sensitive relationship changes.

It must not silently rewrite Konan's private relationship canon.

---

## 3. Trust tiers

Trust tier is a coarse permission level. It is not enough by itself; domain-scoped permissions still apply.

```yaml
trust_tiers:
  tier_0_unknown:
    description: Unknown/public user
    default_access:
      - public_help

  tier_1_recognized:
    description: Known person, identity mapped
    default_access:
      - basic_self_context
      - public_pantheon_help

  tier_2_collaborator:
    description: Trusted for project/work domains
    default_access:
      - explicitly_shared_projects
      - collaboration_context

  tier_3_family_close:
    description: Close relationship/family
    default_access:
      - explicitly_allowed_family_context
      - own_profile
      - shared_household_or_family_context_if_allowed

  tier_4_owner_admin:
    description: Konan / owner admin
    default_access:
      - full_admin
      - override_with_logging
```

---

## 4. Domain-scoped permissions

Every person must have explicit `allowed_context` and `denied_context` lists.

Trust tier answers: **how trusted is this person generally?**

Domain permissions answer: **what can this person access for this purpose?**

Example — Xander:

```yaml
person_id: xander
relationship_to_konan: son
direct_user: true
assigned_gods:
  - marvin
primary_use_case: code_roast_and_learning
trust_tier: tier_2_collaborator
allowed_context:
  - code_submitted_by_xander
  - xander_project_history
  - general_programming_guidance
  - marvin_roast_coach_mode
denied_context:
  - pantheon_private_repos
  - konan_private_relationship_notes
  - business_client_data
  - god_system_config
  - other_people_private_profiles
```

Example — Fia:

```yaml
person_id: fia
relationship_to_konan: partner
direct_user: true
trust_tier: tier_3_family_close
allowed_context:
  - her_own_profile
  - her_own_pantheon_usage
  - shared_family_context_if_explicitly_allowed
  - general_pantheon_help
denied_context:
  - private_notes_about_other_people
  - business_client_data
  - secrets
  - konan_private_admin_context
```

---

## 5. ACL decision inputs

The ACL evaluator must receive:

```yaml
requesting_account_id: string
requesting_person_id: string | null
source_platform: discord | telegram | local | api | webhook
channel_id: string | null
session_owner_person_id: string | null
target_person_id: string
requested_context_domain: string
requested_fact_type: public | basic | sensitive | secret | admin
purpose: string
actor_god: string
```

It returns:

```yaml
decision: allow | deny | needs_konan_approval
reason: string
allowed_files:
  - path
redacted_domains:
  - domain
log_required: true | false
```

---

## 6. Default ACL rules

### Rule ACL-001 — Unknown users receive public help only

Unknown users cannot retrieve private person roots or Konan canon.

### Rule ACL-002 — Konan has owner-admin access

Konan can read, create, update, approve, revoke, and override. Overrides must be explicit and logged when they bypass a deny rule.

### Rule ACL-003 — Direct users can access their own root

A direct Pantheon user can access their own `ROOT.md`, `PREFERENCES.md`, `PROJECTS/`, and allowed self-profile context.

### Rule ACL-004 — Relationship-to-Konan is not the same as self-profile

`RELATIONSHIP_TO_KONAN.md` is Konan-perspective. Another user may see only fields explicitly marked shareable.

### Rule ACL-005 — Sensitive cross-person facts require approval

Facts about another person's private life, health, family relationship, emotional state, religion/worldview, or conflict require explicit sharing permission.

### Rule ACL-006 — Public brand use is stricter

Kairos/Rheta/Iris public content may use only public-approved canon unless Konan explicitly approves sensitive personal context in a post.

### Rule ACL-007 — Code-roast lane is project-scoped

Xander's code-review lane grants access to code Xander submits and general programming guidance. It does not grant Pantheon private repo access.

### Rule ACL-008 — God handoffs preserve ACL context

If one god hands work to another, the handoff must carry the requesting person and allowed context domains. A receiving god cannot broaden access just because the task was handed off.

---

## 7. Account linking

Each direct user profile may include account links:

```yaml
account_links:
  discord:
    user_ids: []
    guild_ids: []
  telegram:
    user_ids: []
  local:
    profile_names: []
```

Account linking must be explicit or verified through a Konan-approved flow.

Minimum safe flow:

1. Konan names the person and platform account, or the person self-identifies.
2. Pantheon creates a pending link.
3. Konan confirms link for sensitive or family accounts.
4. The link becomes active.

---

## 8. Logging

The ACL system must log:

- denied access attempts;
- admin overrides;
- sensitive profile updates;
- account links created/removed;
- changes to trust tier;
- changes to allowed/denied context domains.

Logs should be local-first and stored under the person root or a central audit log with person IDs, not raw secrets.

---

## 9. Open questions

1. Should Tier 3 family-close users have any shared family context by default, or should all family context be explicit allowlist only?
2. Should Konan admin overrides be visible to the affected user in their audit log, or only to Konan?
3. Should each direct user eventually get a separate `Codex-User-<person>` or should the relationship folder remain the root indefinitely?

Current recommendation: keep direct user roots inside `Codex-User/relationships/<person>/` for alpha, then revisit separate codices after real usage.
