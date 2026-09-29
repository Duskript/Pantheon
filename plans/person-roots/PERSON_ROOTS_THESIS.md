# Person Roots — Product Thesis

**Status:** Draft v0.1  
**Date:** 2026-08-06  
**Owner:** Konan / Hermes planner  
**Build mode:** Fusion — Hermes plans/reviews, DeepSeek V4 Flash executes coding through `delegate_task` unless a named god persona is explicitly required.

---

## 1. Thesis

Pantheon should model people as first-class identity roots, not loose memory fragments attached to Konan's conversations.

A person may begin as someone Konan mentions in his own canon. If that person later interacts directly with Pantheon, the same relationship folder matures into that person's own root: preferences, permissions, projects, memories, relationship map, and privacy policy.

Core doctrine:

> **Know people deeply. Share narrowly. Update only from trusted sources.**

This layer exists so every god can understand who Konan is talking about while still respecting boundaries between Konan, family, collaborators, clients, and direct Pantheon users.

---

## 2. Problem

Current state:

- Konan has a master prompt and `user.md`, but relationship context is compact and uneven.
- Some people are only stored in scattered chat sessions, Ichor events, or skill-specific notes.
- There is no first-class folder per person.
- There is no guaranteed alias map for names like `Alexander` / `Xander` or `Finnegan` / `Finn`.
- There is no clear promotion path from "person Konan mentioned" to "person using Pantheon directly."
- There is no enforced privacy gate that decides which user/god/channel can retrieve which relationship facts.

Result: Pantheon can remember fragments, but it cannot reliably act like it knows the person, the relationship, the source authority, and the privacy boundary.

---

## 3. Product goal

Build a **Person Roots** layer under `Codex-User` that gives each important person a durable, structured, permissioned identity folder.

The system should support:

1. Konan-authored relationship canon.
2. Per-person profile roots for direct Pantheon users.
3. Perspective-bound relationship maps.
4. Source-authority rules.
5. Trust tiers and domain-scoped permissions.
6. Account linking for Discord/Telegram/local identities.
7. Safe extraction/proposal workflows for new relationship facts.
8. God runtime retrieval through an ACL evaluator.

---

## 4. Product principles

### 4.1 Perspective-bound truth

Relationship facts are always from a perspective.

- Konan's view of Fia is not automatically Fia's self-profile.
- Xander's own preferences are not automatically Konan's private notes about Xander.
- Amber's work context is not automatically visible to other people.

Every relationship record should answer: **whose view is this?**

### 4.2 Admin power is not default runtime access

Konan is total admin. That does not mean gods should run every interaction as if every participant has root access.

Normal god behavior must obey ACLs. Admin override should be explicit and logged.

Analogy:

> Root can sudo. Apps should not run as root.

### 4.3 Authoritative source matters

A statement from Konan's account can update Konan's canon. A statement from another person can update their own profile within scope. A public source cannot rewrite private relationship truth.

### 4.4 Private by default

If a fact could be sensitive, it is not shared unless explicitly allowed.

Sensitive categories include family structure, relationship dynamics, health, religion/worldview, finances, business/client details, private emotional context, and notes about other people.

### 4.5 Promotion, not migration

A folder should not move when a person becomes a direct Pantheon user. It matures in place.

`relationships/xander/` starts as Konan's relationship record. When Xander joins, the folder gains `ROOT.md`, `PREFERENCES.md`, `PROJECTS/`, and `RELATIONSHIPS/`.

---

## 5. Core use cases

### 5.1 Konan mentions a person

Konan says:

> My boys Alexander/Xander and Finnegan/Finn...

Pantheon should identify likely people, create or update person folders, map aliases, and mark Konan as authoritative source for the relationship-to-Konan fact.

### 5.2 Fia joins Discord

Fia can interact with Pantheon, but her presence does not grant her access to all private Konan canon.

Pantheon should link Fia's Discord user ID to her person root and apply Fia's permission policy on every retrieval.

### 5.3 Xander uses Marvin for code roast

Xander's planned lane is not Pantheon code review. It is Xander submitting his own code so Marvin can critique it as a mentor.

Allowed:

- Xander-submitted code.
- General programming guidance.
- Xander's own learning/project history.
- Marvin "Roast Coach Mode."

Denied by default:

- Pantheon private repos.
- Konan's private relationship notes.
- Client/business secrets.
- Other people's private profiles.

### 5.4 Kairos writes in Konan's voice

Kairos can use Konan's public brand voice and approved canon. Kairos must not pull private family/religion/relationship context into public Facebook or LinkedIn drafts without explicit approval.

---

## 6. Non-goals

This system should not:

- Auto-share Konan's private context with anyone just because they joined Discord.
- Let non-Konan accounts overwrite Konan's private relationship canon.
- Treat web/public/social data as authoritative for private relationships.
- Collapse everyone into one shared family memory blob.
- Give Xander access to Pantheon repos by default.
- Give Fia access to business/client/secrets context by default.
- Build full UI/dashboard management in the first wave.

---

## 7. First implementation slice

The first fusion build should create the canon structure only:

1. Folder layout under `~/athenaeum/Codex-User/relationships/`.
2. Markdown/YAML templates.
3. Seed folders for known people.
4. `INDEX.md` alias map.
5. A validator that checks required files/frontmatter fields.

No automatic extraction. No runtime god ACL hook yet. No public posting integration yet.

Schema first. Automation second.
