---
title: "User-Context-Engine / Codex-Stream Ingest Pipeline — Handoff Concept for Hephaestus"
type: "concept-handoff"
status: "draft — pending operator sign-off"
created: "2026-06-16"
created_by: "Thoth (per Konan)"
assigned_to: "Hephaestus (executor, post-rework as God of Building and Architecture)"
vocabulary: "Internal — uses god names, technical terms. The customer-facing work products (connectors' output) follow the role-based labeling principle per the Workforge interview design."
related:
  - "athenaeum/Codex-Pantheon/design/user-context-engine.md" (v0.2 design — the spec this concept hands off)
  - "athenaeum/Codex-Stream/ingest/" (the existing pipeline that needs to be wired)
  - "athenaeum/Codex-Stream/" (the data codex)
  - "athenaeum/Codex-Stream/raw/" (the existing one-time ingest output)
  - "athenaeum/scripts/process-inbox.py" (existing triage, the bridge between connectors and pipeline)
  - "athenaeum/Codex-User/profile/" (the profile layer to be enriched)
  - "pantheon/gods/gods.yaml" (the canonical god roster — Hephaestus is post-rework)
tags: ["user-context-engine", "codex-stream", "ingest-pipeline", "connectors", "profile-loop", "hephaestus-build", "concept-handoff"]
---

# User-Context-Engine / Codex-Stream Ingest Pipeline — Handoff Concept

> **This is the concept document Hephaestus needs to execute the user-context-engine build.** It outlines everything that needs to be fixed, the priority order, the scope of each piece, the constraints, and the success criteria. Hephaestus takes this, dispatches the work (per the conductor-ui chain pattern), monitors it, and ships it.
>
> **Scope of this concept:** Wire up the existing Codex-Stream ingest pipeline + build the connector layer + build the profile-update loop. **NOT in scope:** the in-app Workforge / Conductor UI build (that's a separate chain), the broader TheoForge product (separate roadmap), or per-tenant onboarding (later phases per the design).

---

## 0. The diagnosis — what's broken

The system is **built but dormant.** Three concrete gaps:

### Gap 1: The pipeline ran once and stopped

- The Codex-Stream ingest pipeline (`~/athenaeum/Codex-Stream/ingest/`) is built: 6 Python files, ~1047 lines, working code (chunker, hotness, cleanup, pipeline orchestrator).
- It ran **once** on 2026-05-28/29, producing 5 gmail + 3 github + 1 test files in `~/athenaeum/Codex-Stream/raw/{provider}/{date}/`.
- **Nothing has driven it since.** No cron fires. The pipeline is dormant.
- Per the pipeline's own `__init__.py` docstring: "The sync scheduler (`~/.hermes/cron/pantheon-sync/`) calls into this Codex." **That scheduler doesn't exist** (I checked `~/.hermes/cron/` — no `ingest` or `context` cron jobs).

### Gap 2: The connector layer doesn't exist

- The user-context-engine v0.2 design (`~/athenaeum/Codex-Pantheon/design/user-context-engine.md`) calls for a connector layer at `~/pantheon/connectors/` with:
  - `lib/base.py` — `ConnectorBase` ABC (authenticate, fetch_since, normalize, run)
  - `lib/normalize.py` — markdown + YAML frontmatter for `process-inbox.py`
  - `lib/state.py` — per-connector cursor / OAuth tokens
  - `lib/__init__.py`
  - `run.py` — CLI: `python run.py youtube --since 7d`
  - `sources/{youtube_takeout, gemini_takeout, claude_export, chatgpt_export, gmail, slack, teams, discord_dm, telegram, rss_generic, pocket}/` — 12 source connectors
- **None of this exists.** The `~/pantheon/connectors/` directory itself doesn't exist.

### Gap 3: The profile-update loop doesn't exist

- The design §4 calls for a profile-update loop that:
  - Reads recent N records from each codex (default N=50)
  - Runs an LLM pass to extract profile signals (voice, patterns, interests, contacts, projects, decisions, open-loops)
  - Updates 7 generated profile artifacts: `Codex-User/profile/{voice,patterns,interests,contacts,projects,decisions,open-loops}.md`
  - Has diff-aware writes that preserve `<!-- manual -->` markers
  - Runs daily (light) / weekly (full) / on-demand
- **The 7 artifacts don't exist** (only `master-prompt.md`, `claude-profile.md`, `pantheon-origin-interview.md`, `ANNOUNCEMENT.md` are in `Codex-User/profile/`).
- **The loop script doesn't exist** (no `profile_update.py` or equivalent).
- **No cron fires it.**

---

## 1. What "fixed" looks like

After this concept ships, the system should be:

1. **Cron-driven ingestion.** A daily/weekly cron fires the pipeline, the pipeline processes the inbox + new content, the raw/ directory grows with new chunks, hotness.json updates, entities get promoted at threshold.

2. **Working source connectors.** The connector layer is built. At least 1 source (YouTube Takeout per the v0.3 roadmap) is fully wired end-to-end. 2-3 more (Gemini, Claude, ChatGPT) are built per the v0.5 roadmap.

3. **Profile loop firing.** The 7 generated profile artifacts exist. The loop runs nightly, updates them based on recent codex records, and diff-aware preserves manual edits. `master-prompt.md` references the new artifacts so gods load them in order.

4. **The existing inbox flow is preserved.** The web clipper still works. The `processed/` and `failed/` directories are the fallback. New connectors are additive, not replacement.

5. **Documented, testable, observable.** Each component has a README, a test, and a way to inspect state. Failures don't go silent — they surface in the inbox `failed/` directory or via the standard god-notify channel.

---

## 2. The scope — what Hephaestus builds

Six discrete deliverables. Each is a separate kanban task with QA review follow-on.

### Deliverable 1: The connector library (3-4 files, 1 task)

**Files:**
- `~/pantheon/connectors/lib/__init__.py`
- `~/pantheon/connectors/lib/base.py` — `ConnectorBase` ABC with `name`, `default_cadence`, `authenticate`, `fetch_since`, `normalize`, `run`, `_last_cursor`, `_update_cursor`, `_drop_in_inbox` (private helper)
- `~/pantheon/connectors/lib/normalize.py` — frontmatter template + content-type-specific normalizers (markdown, JSON-conversation, email, RSS)
- `~/pantheon/connectors/lib/state.py` — per-connector JSON state file: `~/pantheon/connectors/state/<connector_name>/{cursor,oauth,last_run,error_count}.json`
- `~/pantheon/connectors/run.py` — CLI: `python run.py <connector_name> [--since <duration>] [--dry-run]`

**Spec reference:** `athenaeum/Codex-Pantheon/design/user-context-engine.md` §1.1, §3 (the `ConnectorBase` class is on line 129).

**Verification gates:**
- [ ] `ConnectorBase` is an ABC; cannot be instantiated directly
- [ ] `normalize()` returns a string with valid YAML frontmatter (`title`, `source`, `clipped_at`)
- [ ] `run()` round-trips: auth → fetch → normalize → drop-in-inbox → update-cursor
- [ ] State file is created on first run, updated on every run
- [ ] At least 1 unit test for each of the lib files
- [ ] `run.py` CLI is documented in a README

**Owner:** Marvin (pure Python, no UI). Hephaestus dispatches.

**Estimated complexity:** Low — the design doc has the ABC spec verbatim. ~300-500 lines total.

### Deliverable 2: The YouTube Takeout connector (v0.3, 1 task)

**Files:**
- `~/pantheon/connectors/sources/youtube_takeout/__init__.py`
- `~/pantheon/connectors/sources/youtube_takeout/connector.py` — `YouTubeTakeoutConnector(ConnectorBase)`
- `~/pantheon/connectors/sources/youtube_takeout/README.md`
- `~/pantheon/connectors/sources/youtube_takeout/tests/test_connector.py`

**Spec reference:** user-context-engine.md §3.1, §5 (v0.3 — the proof of concept).

**Inputs:**
- YouTube Takeout export: `watch-history.json` + `subscriptions.csv` + per-video transcript
- Polling cadence: 24-48h (per design)

**Output:** One markdown file per video, dropped into `~/athenaeum/inbox/` with frontmatter:
```yaml
---
title: "Video Title"
source: "youtube_takeout"
clipped_at: "2026-06-16T..."
video_id: "..."
channel: "..."
duration: "..."
---
[transcript content]
```

**Auth:** OAuth (the YouTube API). The Takeout export approach (file-drop) is also valid; the design accepts both. **Hephaestus's call which to use.** For v1, **file-drop is simpler** (no OAuth flow); the operator manually places the Takeout export in a known location, the connector ingests.

**Verification gates:**
- [ ] Reads a real YouTube Takeout export (test with fixture)
- [ ] Normalizes to markdown with all 6 frontmatter fields
- [ ] Drops into `~/athenaeum/inbox/`
- [ ] Updates state file with cursor
- [ ] Re-runs are idempotent (no duplicate files)
- [ ] 1+ integration test with a fixture export
- [ ] README explains auth model, cadence, failure modes

**Owner:** Marvin. Hephaestus dispatches.

**Estimated complexity:** Medium — Takeout parsing is straightforward, transcript fetching (via `youtube-content` skill) is the harder part. ~400-700 lines.

### Deliverable 3: The Gemini + Claude + ChatGPT Takeout connectors (v0.5, 1-3 tasks)

**Files:** Same shape as YouTube per source.

**Spec reference:** user-context-engine.md §3.1, §5 (v0.5).

**Inputs:**
- Gemini Takeout: `gemini_conversations.json` (Google Takeout, weekly)
- Claude Settings export: `conversations.json` (Anthropic, weekly)
- ChatGPT Settings export: `conversations.json` (OpenAI, weekly)

**Output:** One markdown file per conversation, dropped into inbox.

**Auth:** File-drop (the Takeout/exports are user-initiated downloads).

**Verification gates (per connector):**
- [ ] Reads a real export (test with fixture or anonymized real data)
- [ ] Normalizes to markdown with frontmatter
- [ ] Idempotent re-runs
- [ ] 1+ integration test
- [ ] README

**Owner:** Marvin. Hephaestus dispatches.

**Estimated complexity:** Low-Medium — all three are JSON-to-markdown with similar shapes. ~300-500 lines per connector. Can be parallelized as 3 separate tasks (1 per source) or shipped as 1 combined task.

**Note:** The 192-file Codex-Claude importer (per design §7, line 302) may be reusable. **Hephaestus should check `~/athenaeum/Codex-Claude/` and the import script that built it** before building the Claude connector from scratch. The 192-file one-shot may already solve 80% of the Claude export parsing.

### Deliverable 4: The ingest scheduler (cron, 1 task)

**Files:**
- `~/.hermes/cron/pantheon-sync/` (the directory the pipeline's `__init__.py` already references)
- The cron entry that fires daily

**Behavior:**
- Wakes daily (e.g., 06:00Z)
- For each enabled connector, runs `python ~/pantheon/connectors/run.py <connector_name> --since 24h`
- After connectors drop into inbox, runs `process-inbox.py` (existing triage) to route content
- After routing, the pipeline ingests routed content (per the Codex-Stream pipeline's design)
- Hotness updates, cleanup runs (daily entity promotion at threshold)

**Spec reference:** user-context-engine.md §1.1 (line 35: "After drop, everything else is existing infrastructure. process-inbox.py classifies and routes, Hades consolidates, Ichor extracts, dreamweaver curates.").

**Verification gates:**
- [ ] Cron fires on schedule (manual trigger works)
- [ ] Connectors run in order (or parallel with lock)
- [ ] Inbox content gets routed
- [ ] Pipeline ingests routed content
- [ ] Hotness.json updates
- [ ] Failures are logged to god-notify (not silent)

**Owner:** Hephaestus (this is the integration glue — Hephaestus's lane, not Marvin's). Or Marvin if it's a one-script job.

**Estimated complexity:** Medium — the integration work is more interesting than the code. ~200-400 lines for the cron entry, possibly a small scheduler script.

### Deliverable 5: The profile-update loop (1-2 tasks)

**Files:**
- `~/pantheon/connectors/profile_update.py` (or `~/athenaeum/scripts/profile_update.py` — Hephaestus's call on location)
- `~/.hermes/cron/profile-loop/` (the cron that fires it)
- The 7 generated profile artifacts in `~/athenaeum/Codex-User/profile/`:
  - `voice.md`
  - `patterns.md`
  - `interests.md`
  - `contacts.md`
  - `projects.md`
  - `decisions.md`
  - `open-loops.md`

**Spec reference:** user-context-engine.md §4 (full spec including LLM prompt, inputs, diff-aware writes, cadence).

**Behavior:**
- Reads recent N records (default 50) from each codex's `sessions/` and `distilled/`
- Reads current `Codex-User/profile/*.md` as "current state"
- Runs LLM pass with structured prompt (per design §4.3)
- Writes updated artifacts, diff-aware (preserves `<!-- manual -->` markers)
- Updates `master-prompt.md` to reference the new artifacts

**Cadence:**
- Daily: light pass (top 10 per codex)
- Weekly: full pass (all new since last full)
- On-demand: `@thoth rebuild profile` from Telegram

**Verification gates:**
- [ ] All 7 artifacts are generated and well-formed
- [ ] Diff-aware writes preserve `<!-- manual -->` sections (test with a manually-edited artifact)
- [ ] Daily run is idempotent (re-running produces no diff)
- [ ] Weekly run is more thorough than daily
- [ ] `master-prompt.md` references the new artifacts in order
- [ ] On-demand trigger works from Telegram
- [ ] LLM pass is logged (which model, which input records, which output diff)

**Owner:** Thoth (the LLM pass is a research synthesis — Thoth's lane). Or Hephaestus if it's purely a code task and Thoth provides the prompt template.

**Estimated complexity:** Medium-High — the LLM prompt is the real work. The script is ~200-400 lines; the prompt is the IP. ~500-1000 lines including the prompt + tests.

### Deliverable 6: The hook layer (1 task, optional for v0.3)

**Files:**
- `~/pantheon/connectors/hooks.yaml` (per-source action rules)
- The hook runner (integrated with the scheduler)

**Spec reference:** user-context-engine.md §5.

**Behavior:**
- Per-source actions (notify, digest, log)
- Default = notify (don't act on new content unless explicitly configured)
- Operator-locked sovereignty: external events don't auto-execute without approval

**Verification gates:**
- [ ] `hooks.yaml` schema is validated
- [ ] Default behavior = notify (no auto-action)
- [ ] Per-source overrides work (e.g., YouTube = notify + digest; Gmail = notify-urgent-only)
- [ ] Operator approval is required for any non-notify action

**Owner:** Hephaestus. Marvin for the YAML schema validator.

**Estimated complexity:** Low-Medium — the YAML schema and the hook runner are mechanical. ~200-400 lines.

**Note:** This is **optional for v0.3** (the design puts it at v0.7, after Tier A polling connectors are proven). Hephaestus can defer to v0.4+ if the v0.3-0.5 work has bandwidth issues.

---

## 3. The build order — what ships first

| # | Deliverable | Owner | Priority | Depends on |
|---|---|---|---|---|
| 1 | Connector library (Deliverable 1) | Marvin | **P0** | Nothing |
| 2 | YouTube Takeout connector (D2) | Marvin | **P0** | D1 |
| 3 | Ingest scheduler cron (D4) | Hephaestus | **P0** | D1, D2 (so something to schedule) |
| 4 | Gemini + Claude + ChatGPT connectors (D3) | Marvin | **P1** | D1 |
| 5 | Profile-update loop (D5) | Thoth | **P1** | D1 (needs the lib for any code that lives there) |
| 6 | Hook layer (D6) | Hephaestus | **P2** (optional) | D1, D4 |

**P0 = critical path.** Must ship before any of the rest. Without the lib, no connector works. Without YouTube + scheduler, no end-to-end proof.

**P1 = next wave.** Gemini/Claude/ChatGPT + profile loop. Can be parallelized.

**P2 = optional.** Hook layer is nice-to-have, not required for the system to function.

---

## 4. The constraints — operator-locked rules

Per `~/athenaeum/Codex-Pantheon/design/operator-rules-cheatsheet.md`:

1. **Build path convention.** All Python code lives under `~/pantheon/connectors/` (not `~/projects/`, not `~/athenaeum/`). The exception is the profile-update script if Hephaestus decides it belongs in `~/athenaeum/scripts/` (the existing `process-inbox.py` is there).
2. **No time estimates in plans or reports.** Phase scope only, no calendar durations.
3. **Sovereignty rule.** External events (new emails, new videos, new chat messages) must NEVER auto-execute without explicit operator approval. The hook layer's default = notify. Any non-notify action requires operator approval.
4. **QA gate.** Every code-producing task has a follow-on Thoth review. The reviewer blocks until the coder completes; the coder isn't done until the reviewer passes.
5. **No silent failures.** If a connector fails, it logs to `~/pantheon/connectors/state/<name>/error_count.json` and surfaces to the operator (god-notify or similar). It does not silently skip.
6. **No LLM calls during retrieval.** Per `athenaeum/Codex-Pantheon/research/openhuman-memory-system-analysis.md` (cited in the design): "LLMs are used ONLY during ingestion/background reflection. ALL retrieval paths are zero-LLM-cost." The profile loop is the only LLM-touching component during ingestion. Retrieval is grep/FTS5/vector.
7. **Secret redaction.** No secrets in any codex write path. The safety layer is pre-ingestion. (Per the same research, this is a current gap that should be addressed.)
8. **The role-based labeling principle is product-wide.** Customer-facing labels use role names, not god names. Internal docs (this concept, the design, the code) use god names. The boundary is the same as for the Workforge design: internal vs customer-facing.

---

## 5. The success criteria — what "shipped" means

The concept is "shipped" when:

- [ ] The connector library (`~/pantheon/connectors/lib/`) is built, tested, documented
- [ ] The YouTube Takeout connector is built, tested, integrated with the cron, and **producing real chunks in `~/athenaeum/Codex-Stream/raw/youtube/`**
- [ ] The Gemini + Claude + ChatGPT connectors are built (may be combined into one task)
- [x] The ingest scheduler cron fires daily, runs the connectors, runs the pipeline, updates hotness
- [ ] The profile-update loop runs nightly, generates the 7 artifacts, preserves manual edits
- [ ] All 6 deliverables have QA review tasks that passed (`pass` or `pass_with_notes`)
- [ ] The README at `~/pantheon/connectors/README.md` explains the architecture, the connectors, the cron, the profile loop
- [ ] The `Codex-Stream/ingest/INDEX.md` is updated to reflect the wired state ("managed by Demeter and Mnemosyne" → "managed by the pantheon-sync cron + the connector layer")
- [ ] A new entry is added to `~/athenaeum/Codex-Pantheon/decisions/` recording the ship + the cron schedule + the operator's sign-off

---

## 6. The risks — what could go wrong

### Risk 1: WikiProvenance plugin isn't wired

`pipeline.py` imports WikiGuard and WikiDedup but I don't see WikiProvenance imported. The provenance inject step in the pipeline (per the docstring) may not be running. **Hephaestus should verify this on first inspection** — if the pipeline isn't injecting provenance, the audit trail for ingested chunks is missing. Easy fix (1 line), but worth checking.

### Risk 2: "Demeter and Mnemosyne" naming confusion

The Codex-Stream INDEX says content is "managed by Demeter and Mnemosyne." Neither is a current god in `~/pantheon/gods/gods.yaml`. **Mnemosyne was explicitly the wrong parallel pipeline the v0.2 design rejected** (line 4: "Replaces v0.1 (which invented a parallel pipeline that already exists)"). The naming in the INDEX is a red flag from an earlier abandoned design. **Hephaestus should update the INDEX to reflect the actual current state** ("managed by the pantheon-sync cron + connector layer").

### Risk 3: The pipeline's plugin path injection is brittle

`pipeline.py` does `sys.path.insert(0, str(_PLUGIN_ROOT / "wikiguard"))` at import time. If the plugin layout changes (e.g., WikiGuard moves to a different directory), the pipeline breaks. **Hephaestus should consider whether to add a proper plugin discovery mechanism** (entry points, config-driven paths, etc.) — but only if the current state is causing problems. If it works, leave it.

### Risk 4: YouTube Takeout OAuth vs. file-drop

The design says YouTube uses OAuth (the YouTube API). But YouTube also has a "Takeout" export that's a file drop. **OAuth is more complex (token refresh, scopes) but real-time. File-drop is simpler but manual.** The design accepts both. **Hephaestus's call.** For the proof of concept, file-drop is the faster path. OAuth can come later if needed.

### Risk 5: Profile loop's LLM prompt is the real work

The script is ~300 lines. The prompt is the IP. **Without a well-designed prompt, the profile loop produces generic output that doesn't actually help the gods load better context.** Thoth should design the prompt, not Marvin. The LLM call is research synthesis, not code generation. **Hephaestus should dispatch the prompt-design work to Thoth separately from the script-coding work to Marvin.**

### Risk 6: 12 source connectors is a lot of scope

The design lists 12 sources. If Hephaestus tries to ship all 12 in one go, the build will take months. **The v0.3-0.7 roadmap in the design exists for a reason.** Ship YouTube first (proof), then 3-4 chat exports (Gemini/Claude/ChatGPT), then 1-2 push connectors (Gmail/Slack), then the rest. **Prioritize by user value, not by alphabet.**

---

## 7. The handoff — what Hephaestus does with this

1. **Read the design doc** (`~/athenaeum/Codex-Pantheon/design/user-context-engine.md`) end-to-end. This concept is the *build plan*; the design is the *spec*. They should agree.
2. **Inspect the existing code** (`~/athenaeum/Codex-Stream/ingest/`) to verify what's actually there vs. what the design assumes.
3. **Verify the plugin state** (WikiProvenance wiring, plugin path injection, etc.).
4. **Build the build plan** (per `build-plan-orchestrator` skill v1.0.4) with the 6 deliverables as discrete tasks, parent-child linked, QA follow-ons auto-generated.
5. **Get operator sign-off** on the build plan (Path B operator-in-the-loop, per `pantheon-dev-workflow`).
6. **Dispatch the chain** (per `plan-execution` + `dispatch-monitoring` skills).
7. **Monitor the chain** (per `dispatch-monitoring` skill — 5 problem patterns: stall, blocked-too-long, repeated crashes, missed QA, gate-not-run).
8. **Ship and report back** to Konan + Thoth when v0.3 is delivered (the lib + YouTube + scheduler).

**Don't:** try to build all 12 connectors in one go. Ship v0.3 first (lib + YouTube + scheduler), report back, then continue with v0.5+.

**Do:** verify the existing pipeline works (run it manually with a fixture), build the lib, then the YouTube connector, then the scheduler. Each step is end-to-end testable.

---

## 8. The references — for context

| Document | What it tells you |
|---|---|
| `athenaeum/Codex-Pantheon/design/user-context-engine.md` | The full v0.2 design spec. Read this end-to-end. |
| `athenaeum/Codex-Stream/ingest/pipeline.py` | The existing pipeline orchestrator. 369 lines. |
| `athenaeum/Codex-Stream/ingest/chunker.py` | The chunker. 204 lines. Splits text on paragraph boundaries, SHA256 IDs. |
| `athenaeum/Codex-Stream/ingest/hotness.py` | The hotness tracker. 222 lines. Tracks mention frequency, promotes at threshold. |
| `athenaeum/Codex-Stream/ingest/cleanup.py` | The cleanup. 228 lines. Daily purge of old raw/ + entity promotion. |
| `athenaeum/Codex-Stream/ingest/__init__.py` | The package docstring. Note the scheduler reference (line 32). |
| `athenaeum/Codex-Stream/raw/` | The existing one-time ingest output. Shows the file layout. |
| `athenaeum/scripts/process-inbox.py` | The existing triage. The bridge between connectors and pipeline. |
| `~/.hermes/plugins/wikiguard/` | The scoring plugin. Used by pipeline. |
| `~/.hermes/plugins/wiki-dedup/` | The dedup plugin. Used by pipeline. |
| `~/.hermes/plugins/wiki-provenance/` | The provenance plugin. **Possibly not wired — verify.** |
| `athenaeum/Codex-User/profile/` | The profile layer to be enriched (7 new generated artifacts). |
| `athenaeum/Codex-Pantheon/design/operator-rules-cheatsheet.md` | The operator-locked rules Hephaestus must follow. |
| `athenaeum/Codex-Pantheon/research/openhuman-memory-system-analysis.md` | The "no LLM in retrieval" principle + the secret-redaction gap. |
| `athenaeum/Codex-Pantheon/constitution/GODS.md` | The god roster. Hephaestus is "God of Building and Architecture" (post-rework). |
| `pantheon/god-packages/shared-skills/build-plan-orchestrator/SKILL.md` | The skill to use for the build plan. v1.0.4. |
| `pantheon/god-packages/shared-skills/plan-execution/SKILL.md` | The skill to use for dispatching the chain. |
| `pantheon/god-packages/shared-skills/dispatch-monitoring/SKILL.md` | The skill for monitoring the chain. |
| `pantheon/god-packages/shared-skills/standard-pattern-applier/SKILL.md` | The skill for applying a standard to a new instance (e.g., subsystem-shape to the new connectors). |

---

## 9. The message back to Konan

When v0.3 ships (lib + YouTube + scheduler + cron firing), Hephaestus sends a handoff back to Thoth with:

- Path to the build plan that was approved
- Path to the deliverables (6 files minimum for v0.3)
- QA review pass results
- Test results (the YouTube connector ingested a real Takeout export, chunks landed in `Codex-Stream/raw/youtube/`, hotness.json updated)
- Cron schedule (when does the daily run fire?)
- Any open questions for v0.5+ (Gemini/Claude/ChatGPT, profile loop, hooks)

Thoth relays to Konan with the operator-in-the-loop pattern: "v0.3 shipped. v0.5 is queued. Here's what's next."

---

## 10. The sign-off

**Operator (Konan) review needed on:**

1. **Build priority.** v0.3 (lib + YouTube + scheduler) is critical path. v0.5 (chat exports) is next. v0.6 (push connectors) and v0.7 (hooks) are later. **Confirm this order, or specify a different order.**
2. **YouTube OAuth vs. file-drop.** File-drop is faster to ship. OAuth is more complex but real-time. **Confirm: ship file-drop first, OAuth later?**
3. **Profile loop owner.** Thoth designs the prompt, Marvin codes the script, Hephaestus dispatches. **Confirm this split, or specify differently.**
4. **WikiProvenance wiring.** Verify on first inspection. **If not wired, Hephaestus wires it (small fix).**
5. **Naming cleanup.** The Codex-Stream INDEX says "Demeter and Mnemosyne" which is wrong. **Confirm: Hephaestus updates the INDEX as part of the build?**

---

**Hephaestus — when you read this, the next step is to:**
1. Read the v0.2 design doc end-to-end
2. Inspect the existing code
3. Build a build plan (per `build-plan-orchestrator` skill) with the 6 deliverables
4. Get Konan's sign-off on the 5 questions in §10
5. Dispatch the chain
6. Ship v0.3 (lib + YouTube + scheduler)
7. Report back

**The build path is `~/pantheon/connectors/` (per the operator-locked build-path convention). The QA gate is on every code task. The sovereignty rule is the default. The role-based labeling principle applies to customer-facing surfaces only — this concept is internal.**

Go.
