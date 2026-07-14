# User-Context-Engine v0.3 — Build Plan

> **Status:** DRAFT — awaiting operator (Konan) review
> **Date:** 2026-06-17
> **Author:** Hephaestus (from Thoth's design doc v0.2 + operator decisions)
> **Project root:** `~/pantheon/connectors/` (per [Build Path Convention])
> **Foundation:** Thoth's design at `~/athenaeum/Codex-Pantheon/design/user-context-engine.md` + existing pipeline at `~/athenaeum/Codex-Stream/ingest/`

---

## 0. Provenance

| Source | What it told us |
|---|---|
| **Thoth's design v0.2** | User-context-engine is not a new system — it's a connector layer + profile-update loop that feeds the existing Athenaeum pipeline. Two components: connector library + per-source connectors that normalize to `process-inbox.py` format and drop into `~/athenaeum/inbox/`. |
| **Thoth's handoff (2026-06-17)** | 6 deliverables ordered by priority: P0 connector lib + YouTube + scheduler, P1 chat connectors + profile loop, P2 hook layer. Risks: WikiProvenance wiring, INDEX naming cleanup, YouTube file-drop first. |
| **Konan's decisions (2026-06-17)** | (1) v0.3 critical path, v0.5 next. (2) YouTube file-drop first, OAuth later. (3) Two-tier QA: Hephaestus verifies → Thoth final QA. (4) Verify/fix WikiProvenance wiring. (5) Update Codex-Stream INDEX. |
| **Existing pipeline** | `~/athenaeum/Codex-Stream/ingest/pipeline.py` (369 lines) — canonical → chunk → score → dedup → write. WikiGuard + wiki-dedup plugins imported with graceful degradation. `process-inbox.py` classifies and routes from inbox/. |
| **Codex-Claude importer** | 192-file reference implementation — check before building chat connectors (v0.5). Not needed for v0.3. |

---

## 1. Tier routing summary

**Tools:** `cli_tool` (connectors are Python CLI scripts) + `cron` (scheduler)

**Pattern:** Pipeline — lib → connector → scheduler → verify. Each deliverable gates on the previous.

**Catalog search terms:** `connector`, `ingest`, `pipeline`, `cron`, `takeout`

**Complexity:** Medium — 4 discrete deliverables, each ~100-300 lines. All pieces exist; this is wiring, not greenfield.

**Specialists:**
- **Marvin** (master coder) — all `Action: CREATE` and `Action: MODIFY` rows
- **Hephaestus** (architect/conductor) — architecture review, dispatches, first-tier QA verification
- **Thoth** (QA gate) — final QA review on all code before phase progression
- **Hermes** (operations) — cron wiring

---

## 2. Foundation — existing pipeline

The pipeline at `~/athenaeum/Codex-Stream/ingest/` already handles:
- Chunking (`chunker.py`)
- Quality scoring (`WikiGuard` plugin — `wikiguard/signals.py`)
- Deduplication (`wiki-dedup` plugin)
- Provenance frontmatter injection
- Entity extraction (spaCy NER)
- Hotness tracking (`hotness.py`)

The missing piece: nothing feeds it new content. The inbox at `~/athenaeum/inbox/` accepts manual drops via web clipper, but there's no automated connector layer. v0.3 builds that layer.

**Pre-build verification (completed by Hephaestus):**
- WikiGuard + wiki-dedup plugins: ✅ wired, graceful degradation on import failure
- `process-inbox.py`: exists, routes by frontmatter `codex` field
- `Codex-Stream/ingest/INDEX.md`: references abandoned "Demeter and Mnemosyne" names — to be fixed in this build

---

## 3. Phased implementation plan

```
v0.3 (this build)
  ↓ lib/  — ConnectorBase + normalize + state
  ↓ youtube_takeout/  — parse watch-history.json, fetch transcripts, drop in inbox
  ↓ scheduler  — daily cron fires connectors → pipeline → hotness update
  ↓ verify  — end-to-end: YouTube Takeout → inbox → pipeline → Codex-Stream/raw/
  ↓ cleanup  — INDEX.md fixed, WikiProvenance confirmed
        ↓
v0.5 (next build — Gemini + Claude + ChatGPT connectors)
```

**v0.3 ships when:** A real YouTube Takeout export is ingested, classified, chunked, scored, deduped, and written to `Codex-Stream/raw/youtube/`. The cron fires daily.

---

## 4. File-by-file changes

### Deliverable 1: Connector library

| Path | Action | Owner | Verification |
|---|---|---|---|
| `~/pantheon/connectors/README.md` | CREATE | Marvin | Documents connector pattern |
| `~/pantheon/connectors/lib/__init__.py` | CREATE | Marvin | Exports `ConnectorBase`, `normalize_to_inbox`, `load_state`, `save_state` |
| `~/pantheon/connectors/lib/base.py` | CREATE | Marvin | `ConnectorBase` ABC: `name`, `authenticate()`, `fetch_since()`, `normalize()`, `run()` default loop |
| `~/pantheon/connectors/lib/normalize.py` | CREATE | Marvin | `normalize_to_inbox(item, source, codex)` → markdown with YAML frontmatter matching `process-inbox.py` schema |
| `~/pantheon/connectors/lib/state.py` | CREATE | Marvin | `load_state(user_id, source)` / `save_state(user_id, source, data)` → JSON at `~/pantheon/connectors/state/{user_id}/{source}.json` |
| `~/pantheon/connectors/lib/__tests__/test_base.py` | CREATE | Marvin | Mock connector: instantiate, run default loop, verify inbox drop |
| `~/pantheon/connectors/lib/__tests__/test_normalize.py` | CREATE | Marvin | Test: YouTube item → valid `process-inbox.py` frontmatter |
| `~/pantheon/connectors/lib/__tests__/test_state.py` | CREATE | Marvin | Test: save/load roundtrip, cursor update, concurrent safety |

### Deliverable 2: YouTube Takeout connector

| Path | Action | Owner | Verification |
|---|---|---|---|
| `~/pantheon/connectors/sources/youtube_takeout/__init__.py` | CREATE | Marvin | Exports `YouTubeTakeoutConnector` |
| `~/pantheon/connectors/sources/youtube_takeout/connector.py` | CREATE | Marvin | Extends `ConnectorBase`: parse `watch-history.json`, per-video transcript fetch via `youtube-content` skill, normalize, drop to inbox |
| `~/pantheon/connectors/sources/youtube_takeout/README.md` | CREATE | Marvin | How to export YouTube Takeout, where to place the file |
| `~/pantheon/connectors/sources/youtube_takeout/tests/test_connector.py` | CREATE | Marvin | Mock watch-history.json → parse → normalize → verify inbox format |
| `~/pantheon/connectors/run.py` | CREATE | Marvin | CLI: `python run.py youtube --since 7d` (or `--file watch-history.json`) |

### Deliverable 3: Ingest scheduler

| Path | Action | Owner | Verification |
|---|---|---|---|
| `~/.hermes/cron/pantheon-sync/connectors.sh` | CREATE | Hephaestus | Shell wrapper: runs connectors, then pipeline, then hotness update. Logs to `~/pantheon/connectors/state/sync.log` |
| Cron entry | CREATE | Hephaestus | Daily at 06:00 UTC (before Hades 07:00). `hermes cron create pantheon-sync-connectors --schedule '0 6 * * *' --script connectors.sh` |
| `~/pantheon/connectors/state/.gitkeep` | CREATE | Hephaestus | State directory with user subdirs |

### Deliverable 4: Cleanup

| Path | Action | Owner | Verification |
|---|---|---|---|
| `~/athenaeum/Codex-Stream/ingest/INDEX.md` | MODIFY | Marvin | Replace "Demeter and Mnemosyne" with "Connector-driven ingestion pipeline. Content enters via connectors → inbox → process-inbox.py → Codex-Stream/ingest/pipeline.py → Codex-Stream/raw/." |

---

## 5. Tests + verification gates

**Per-deliverable "done" check:**

| Deliverable | Gate | Command |
|---|---|---|
| **D1: Library** | All unit tests pass, abstract methods raise on unimplemented | `cd ~/pantheon/connectors && python -m pytest lib/__tests__/ -v` |
| **D2: YouTube** | Mock watch-history parses, normalizes to valid inbox format, transcript fetch mocked | `cd ~/pantheon/connectors && python -m pytest sources/youtube_takeout/tests/ -v` |
| **D3: Scheduler** | Cron entry exists, script runs without error on dry-run | `hermes cron list | grep pantheon-sync-connectors` |
| **D4: Cleanup** | INDEX.md no longer mentions Demeter/Mnemosyne | `grep -c "Demeter\|Mnemosyne" ~/athenaeum/Codex-Stream/ingest/INDEX.md` → 0 |
| **End-to-end** | Real YouTube Takeout → inbox → pipeline → raw/youtube/ | Manual: place `watch-history.json`, run `python run.py youtube --file watch-history.json`, verify files in `Codex-Stream/raw/youtube/` |

**Test minimums:** ≥4 tests per Python module. Mock external dependencies (YouTube API, filesystem).

**Build-test gate:** All tests pass before advancing between deliverables. Two-tier QA on every code deliverable.

---

## 6. Decisions applied

| # | Decision | Effect on plan |
|---|---|---|
| **D1** | v0.3 critical path, v0.5 next | This plan covers v0.3 only. v0.5 (chat connectors) is a separate build plan. |
| **D2** | YouTube file-drop first, OAuth later | Connector reads `watch-history.json` from local filesystem. OAuth is deferred to v0.6+. |
| **D3** | Two-tier QA: Hephaestus verify → Thoth final | Every Marvin code deliverable gets: (1) Hephaestus architecture/contract review, iterative with Marvin until pass, (2) Thoth comprehensive QA. No phase progression until both tiers pass. |
| **D4** | WikiProvenance: verify and fix if needed | Verified: WikiGuard + wiki-dedup plugins are imported in `pipeline.py` with graceful degradation. No fix needed. |
| **D5** | Codex-Stream INDEX cleanup | Deliverable 4 — remove "Demeter and Mnemosyne" references. |
| **D6** | Build path convention | Code lives at `~/pantheon/connectors/`. State at `~/pantheon/connectors/state/`. No build output under `~/projects/` for this build (it's system infrastructure). |
| **D7** | No time estimates | Scope described as deliverables + tasks, no calendar durations. |
| **D8** | Sovereignty guardrail | Hook layer (P2) defaults to `notify`. Never auto-act. Not in scope for v0.3. |

---

## 7. Phase scope

| Deliverable | Tasks | Coder | Reviewer (Tier 1) | Reviewer (Tier 2) | Depends on |
|---|---|---|---|---|---|
| D1: Library | 8 files | Marvin | Hephaestus | Thoth | None |
| D2: YouTube | 5 files | Marvin | Hephaestus | Thoth | D1 |
| D3: Scheduler | 3 files | Hephaestus | — | Thoth | D2 |
| D4: Cleanup | 1 file | Marvin | Hephaestus | — | D1 (parallel) |

**Critical path:** D1 → D2 → D3. D4 is parallel to D2.

**QA overhead:** 4 Marvin code deliveries × 2-tier review = 8 review checkpoints (4 Hephaestus tier-1 + 4 Thoth tier-2). Plus 1 Thoth review on D3 (Hephaestus's scheduler code).

---

## 8. Specialists

| God | Role in this build |
|---|---|
| **Marvin** | Primary coder — all CREATE/MODIFY rows for Python files |
| **Hephaestus** | Architecture design, dispatches work, tier-1 QA verification (iterative with Marvin), scheduler cron, end-to-end test |
| **Thoth** | Tier-2 final QA on all code, design doc author (already done) |
| **Konan** | Operator — sign-off at plan approval + end-to-end verification gate |

---

## 9. Two-tier QA process (operator-locked, 2026-06-17)

Per Konan's directive, each code deliverable follows this loop:

```
Marvin codes → Hephaestus verifies
  ↓ (if not good)
  back to Marvin for fixes
  ↓ (repeat until Hephaestus signs off)
Thoth final QA
  ↓ (pass | needs_changes | block)
Phase progression (if pass)
```

**Hephaestus tier-1 review checks:**
- Code matches the architecture contract (ConnectorBase interface, normalize output schema, state format)
- Tests cover the contract
- No broken imports, types pass
- Edge cases handled (empty watch-history, missing transcript, malformed JSON)

**Thoth tier-2 review checks:**
- Full QA per the QA-gate rubric
- Security: no credentials in code, state files permissions
- Pipeline integration: does the connector output actually work with process-inbox.py?
- Code quality: readable, documented, no silent failures

---

## 10. Pitfalls

- **Takeout format drift.** Google changes the `watch-history.json` schema occasionally. The connector should validate the schema on load, not assume.
- **Transcript fetch is the bottleneck.** `youtube-content` skill may be slow or rate-limited. Batch with retry, log failures.
- **State file corruption.** If the scheduler crashes mid-write, the state JSON could be malformed. Use atomic write (write to temp file, rename).
- **process-inbox.py may reject new frontmatter fields.** The schema in Appendix A of the design doc is the contract. Stick to it exactly.
- **Cron permissions.** The scheduler runs as the `konan` user. Verify the cron daemon is running and the user has cron access.
- **WikiProvenance confusion resolved.** The `wikiguard` and `wiki-dedup` plugins ARE the scoring + dedup layer. The "WikiProvenance" name in Thoth's risk list was a misnomer — provenance is just a frontmatter field in pipeline.py.

---

## 11. Post-build

When v0.3 ships:
1. Run a real YouTube Takeout through the pipeline end-to-end
2. Verify transcripts land in `Codex-Stream/raw/youtube/YYYY-MM-DD/`
3. Verify `process-inbox.py` classifies and routes them
4. Confirm cron fires daily
5. Log the ship decision to `pantheon/shared/decisions/`
6. Queue v0.5 build plan (Gemini + Claude + ChatGPT connectors)

---

## 12. Sign-off

**Operator checklist:**
- [ ] Plan covers all 5 answered decisions
- [ ] Two-tier QA process matches intent
- [ ] File-by-file table is complete
- [ ] Verification gates are concrete
- [ ] No time estimates (scope only)
- [ ] Build path follows convention

Reply `approved` to dispatch, or `change: <what>` to revise.
