# Olympus UI — Phased Planning Document

> **CRITICAL: This document is the planning anchor. Do not skip phases. Do not jump to code.**
>
> Every session working on Olympus UI must begin by reading this document to know exactly which phase we are in and what the rules are.

---

## Phase Structure

Each phase has:
- **Goal:** What we are deciding/capturing
- **Inputs:** What we need before starting
- **Outputs:** What must be produced before moving on
- **Gate:** Rule that prevents premature implementation

---

## Phase 0: Repository Cleanup & Canonical Source of Truth

### Goal
Eliminate confusion about which UI is canonical. Retire/archive dead branches and files. Establish one reference directory for Olympus UI planning.

### Inputs
- Current running UI state
- Old Pantheon UI branches
- Discontinued experiments
- Existing Pantheon docs

### Outputs
- `docs/olympus/LINEAGE.md` — labels every UI lineage:
  - ACTIVE_DRIVER
  - REFERENCE_ONLY
  - RETIRED_DO_NOT_EDIT
  - FAILED_EXPERIMENT
  - ARCHIVE
- Retired UIs clearly marked (do not accidentally edit them in future sessions).
- Clean Olympus docs directory established: `~/pantheon/docs/olympus/`

### Gate
> **DO NOT WRITE CODE. Continue planning. Proceed to Phase 1.**

---

## Phase 1: Reference Inventory & UX Preferences

### Goal
Collect visual and UX references from all relevant WebUIs. Capture what Konan likes and dislikes from each. Build a comprehensive picture of desired layout, interactions, and feel.

### Inputs
- Current Pantheon UI screenshots/notes
- Old discontinued Pantheon UI branch screenshots/notes
- assistant-ui examples (ChatGPT clone, Claude clone, Perplexity clone, etc.)
- Claude (Anthropic)
- ChatGPT (OpenAI)
- Gemini (Google)
- Grok (xAI)
- Perplexity
- NextChat
- LibreChat
- Open WebUI
- LobeChat / LobeHub
- Any other UI Konan points at

### Process
For each reference, capture:
- Screenshots
- Layout notes
- What Konan likes (specific elements)
- What Konan dislikes
- Features worth copying
- Terms/naming to avoid
- Mobile behavior
- Theming/vibe notes
- Interactions that feel right

### Outputs
- `docs/olympus/REFERENCE_INVENTORY.md` — structured comparison across all references
- Clear preference annotations per reference
- "I like that" → concrete Olympus feature mapping

### Gate
> **DO NOT WRITE CODE. Continue planning. Proceed to Phase 2.**

---

## Phase 2: Architecture & Contracts

### Goal
Define the architecture of Olympus UI before any code exists. Establish contracts between Olympus and Hermes Agent. Define data models and authority rules.

### Inputs
- Phase 1 reference preferences
- Phase 0 clean lineage
- Existing DECISIONS.md

### Outputs
- `docs/olympus/ARCHITECTURE.md` — system architecture
- `docs/olympus/HERMES_ADAPTER_CONTRACT.md` — how Olympus talks to Hermes:
  - sessions
  - messages
  - streaming
  - model/provider
  - profiles/agents
  - skills
  - tools
  - cron
  - memory
  - slash commands
- `docs/olympus/USER_MODEL.md` — human user profile data model
- `docs/olympus/ROLE_PERMISSIONS.md` — roles, permissions, authority rules
- `docs/olympus/SESSION_SCOPING.md` — session ownership and profile tagging
- State authority rules defined:
  - Hermes is source of truth for runtime state
  - Olympus owns UI/display state only
  - No localStorage as authority
  - No duplicated business logic

### Gate
> **DO NOT WRITE CODE. Continue planning. Proceed to Phase 3.**

---

## Phase 3: Design System & Theme Model

### Goal
Define the Olympus theming and design token system. Ensure Olympus can be branded, recolored, and rethemed without editing component code.

### Inputs
- Phase 1 visual preferences
- Phase 2 architecture decisions
- DECISIONS.md theming decisions

### Outputs
- `docs/olympus/THEME_SYSTEM.md` — design token architecture:
  - global CSS variable strategy
  - color system
  - typography tokens
  - spacing/radius/density tokens
  - glow/effect tokens
  - logo/image swap mechanism
- `docs/olympus/TERMINOLOGY_MAP.md` — internal names vs display names:
  - `agent` → `Assistant` (client), `God` (Pantheon theme)
  - `boon` → `Document` (client), `Boon` (Pantheon theme)
  - etc.
- `docs/olympus/COMPONENT_ARCHITECTURE.md` — component tree / module boundaries
- Layout zones defined:
  - header
  - left nav / session area
  - chat center
  - composer
  - right drawer / contextual panel
  - admin/config surface
  - mobile/PWA behavior

### Gate
> **DO NOT WRITE CODE. Continue planning. Proceed to Phase 4.**

---

## Phase 4: Feature Matrix & Config Schema

### Goal
Define every feature/function and how it is configured, toggled, and gated. Finalize config schema.

### Inputs
- All prior phase outputs
- Hermes Agent feature list
- DECISIONS.md feature flag decisions

### Outputs
- `docs/olympus/CONFIG_SCHEMA.md` — deployment config format
- `docs/olympus/FEATURE_FLAGS.md` — every toggle and its behavior:
  - deployment defaults
  - role overrides
  - user overrides
- `docs/olympus/FEATURE_PARITY_MATRIX.md` — Hermes feature → Olympus surface mapping:
  - `/model`, `/tools`, `/skills`, `/cron`, `/memory`, `/profile`, `/usage`, `/status`, etc.
  - status: implemented / partial / missing / hidden by role
- Navigation / sidebar model defined
- Boon/document types defined
- Admin panel scope defined

### Gate
> **DO NOT WRITE CODE. Continue planning. Proceed to Phase 5.**

---

## Phase 5: Build Plan & Foundation Choice

### Goal
Choose the technical foundation. Define the implementation plan. Create bite-sized build tasks. Only now do we decide: assistant-ui, custom React, or other foundation.

### Inputs
- All prior phase outputs
- assistant-ui evaluation
- Other foundation candidates if surfaced

### Outputs
- `docs/olympus/FOUNDATION_DECISION.md` — chosen tech stack and rationale
- `docs/olympus/BUILD_PLAN.md` — phased implementation plan:
  - each task is bite-sized (2–5 min of work)
  - exact file paths
  - verification steps
  - commit points
- Repo structure designed (modular, no giant files)
- Package naming decided
- Build order:
  1. App shell / layout
  2. Hermes health/status adapter
  3. Session list
  4. Chat runtime / streaming
  5. Model picker
  6. Agent rail / profile switching
  7. Tool call rendering
  8. Boon drawer
  9. Skills / tools / settings panels
  10. Cron / memory / usage
  11. PWA / mobile
  12. Theme system / effects

### Gate
> **DO NOT WRITE CODE. Continue planning. Proceed to Phase 6.**

---

## Phase 6: IMPLEMENT

### Goal
Write code. Execute the build plan task by task. Commit frequently. Verify each step.

### Rules
- Follow BUILD_PLAN.md exactly.
- Bite-sized tasks only.
- Commit after each task.
- Verify before moving on.
- If a task reveals a missing design decision, Pause Implementation, update the relevant doc, then resume.
- Delegation may be used for parallel independent workstreams.

### Gate
> **CODE ALLOWED. Execute BUILD_PLAN.md task by task.**

---

## Session Protocol

Every Olympus UI working session:

1. Open `PLANNING_PHASES.md` (this file).
2. Identify current phase.
3. Read current phase's goal/outputs/gate.
4. Do NOT skip phases.
5. Do NOT write code unless phase gate says so.
6. Update the relevant phase output doc(s) before moving to next phase.
7. If Konan says something that sounds like "just build it," gently confirm: still in planning phases, or are we ready to advance?

---

## Current Phase

**Phase 0: Repository Cleanup & Canonical Source of Truth**

Next: Create `docs/olympus/LINEAGE.md`
