# Conductor Parallel Work — Build Plan

**Document:** CONDUCTOR-PARALLEL-BUILD-001
**Status:** v1.0 — ready to execute
**Created:** 2026-06-16
**Owner:** Marvin (engine + sim + workflow), Thoth (program.md + workflow YAMLs), Iris (GUI), Konan (operator)
**Duration:** ~5 weeks wall-clock with 3 parallel workstreams
**Goal:** Marvin + Hephaestus + Claude Code + Codex CLI running in tandem on the same feature, with a judge picking the best output. Plus the Forge autoresearch loop using the same primitives.

---

## 0. The headline

This is a **3-workstream parallel build** for one shared goal: get Conductor v2 to run multiple agents in parallel and merge their results. The build plan is structured so that the three streams can move in parallel from day 1, with one critical-path dependency (the `cli_tool` step type) that unlocks everything else.

```
                         ┌─────────────────────────────┐
                         │  Conductor v2 engine        │
                         │  (the substrate)            │
                         │  ~/pantheon/conductor/v2/   │
                         └──────────────┬──────────────┘
                                        │
              ┌─────────────────────────┼─────────────────────────┐
              │                         │                         │
              ▼                         ▼                         ▼
    ┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
    │  STREAM A        │      │  STREAM B        │      │  STREAM C        │
    │  CLI Orchestration│      │  Forge Autoresearch│      │  Conductor GUI   │
    │  (the engine)    │      │  (the consumer)  │      │  (the visibility)│
    │  Owner: Marvin   │      │  Owner: Marvin   │      │  Owner: Iris     │
    │  Phases 1-4: 4 wks│      │  Phases 1-3: 3 wks│      │  Phase 1: 2 wks  │
    └────────┬─────────┘      └────────┬─────────┘      └────────┬─────────┘
             │                         │                         │
             └─────────────────────────┼─────────────────────────┘
                                       │
                                       ▼
                            ┌─────────────────────┐
                            │  4-AGENT CODING     │
                            │  WORKFLOW           │
                            │  (the proof)        │
                            │  Marvin + Hephae    │
                            │  + Claude + Codex   │
                            │  in tandem          │
                            └─────────────────────┘
```

**The critical-path insight:** the `cli_tool` step type (Stream A Phase 1) is the one thing every other stream depends on. Once that ships, all three streams can move in parallel. Until it ships, Streams B and C are blocked on Phase 1 of A.

**The target:** by week 5, you can run a workflow that says "have Marvin, Hephaestus, Claude Code, and Codex CLI all implement feature X, then have a judge pick the best, then have Hephaestus review the winner" — and watch it happen live in the Conductor GUI.

---

## 1. The workstreams

### Stream A — CLI Orchestration (the engine primitives)

**Specs:**
- `~/athenaeum/Codex-Pantheon/specs/conductor-cli-orchestration.md` (v1.0.0)
- `~/pantheon/shared/active/conductor-cli-orchestration-brief.md`

**What it adds:** 3 new step types to the Conductor v2 engine:
- `cli_tool` — invoke a CLI subprocess (Claude Code, Codex CLI, etc.)
- `parallel` — run N child steps concurrently
- `merge` — combine N outputs via strategy (concat, llm_pick_best, etc.)

Plus a WebSocket live-observability stream so the GUI can show what the agents are doing in real time.

**Phases:**

| Phase | What | LOC | Tests | Dependencies |
|---|---|---|---|---|
| **A.1** | `cli_tool` step type | ~500 | ~12 | None (this is the critical-path) |
| **A.2** | WebSocket live stream | ~400 | ~10 | A.1 (uses `cli_tool`'s `stream: true` flag) |
| **A.3** | `parallel` step type | ~350 | ~10 | None (independent of A.2) |
| **A.4** | `merge` step type (6 strategies) | ~300 | ~12 | None (independent of A.2, A.3) |
| **A.5** | `cli_tools.yaml` registration + 3 v1 tools | ~150 | ~5 | A.1 |

**Critical path:** A.1. Once A.1 ships, A.2-A.5 can run in parallel (4 streams within Stream A).

### Stream B — Forge Autoresearch (the consumer)

**Specs:**
- `~/athenaeum/Codex-Pantheon/specs/forge-autoresearch.md` (v1.0.0)
- `~/pantheon/shared/active/forge-autoresearch-brief.md`

**What it adds:** converts the Ichor Forge from operator-triggered to a closed-loop autoresearch system. Runs overnight, proposes gate config changes, simulates them against the last 7 days of intervention logs, picks the best, auto-applies safe ones, queues controversial ones for the morning brief.

**Phases:**

| Phase | What | LOC | Tests | Dependencies |
|---|---|---|---|---|
| **B.1** | Score functions (precision, recall, override, composite) + baseline | ~150 | ~6 | None (independent — measures the *current* Forge) |
| **B.2** | Simulation harness (`analyze_with_config`) | ~250 | ~8 | B.1 (uses the score functions) |
| **B.3** | `ForgeResearcher` + `ForgeApplier` + `classify_controversy` + approval card generator | ~700 | ~15 | B.1, B.2 |
| **B.4** | Conductor workflow (`forge-overnight-research.yaml`) | ~200 | ~5 | **A.1** (uses `cli_tool`), A.3 (uses `parallel`), A.4 (uses `merge`) |
| **B.5** | `forge-program.md` (the strategy document) | Markdown only | n/a | None (I write this in parallel) |
| **B.6** | Morning-briefing integration (new step in `morning-briefing.yaml`) | ~50 | ~3 | None (small wiring change) |
| **B.7** | Staging rollout + 2-week monitoring | n/a | n/a | All B phases |

**Critical path:** B.1 → B.2 → B.3 → B.4. B.1-B.3 can run in parallel with Stream A. B.4 is blocked on A.1, A.3, A.4.

### Stream C — Conductor GUI (the visibility)

**Spec:**
- `~/projects/ledger/CONDUCTOR-UI-BUILD-PLAN.md` (the build plan I wrote earlier)

**What it adds:** Iris's mock at `http://100.68.106.59:8889/` becomes a production React app. The Run view subscribes to the WebSocket live stream from A.2 and shows what each agent is doing in real time.

**Phases (extracted from the GUI build plan):**

| Phase | What | Owner | Dependencies |
|---|---|---|---|
| **C.1** | React app scaffold + MSW mocks + theme + routing | Iris | None |
| **C.2** | Workflows list view | Iris | C.1 |
| **C.3** | Editor view (canvas + inspector + soulforge chat) | Iris | C.1 |
| **C.4** | Run view with **WebSocket live observability** | Iris | **A.2** (WebSocket server), C.1 |
| **C.5** | HTTP wrapper backend (FastAPI) | Marvin | A.1 (the cli_tool contract is part of the API) |
| **C.6** | Integration + bug bash | Iris + Marvin | C.4, C.5 |

**Critical path:** C.1 → C.4. C.4 is blocked on A.2 (WebSocket server must exist before Iris can subscribe).

---

## 2. The dependency graph (what blocks what)

```
         ┌──── A.1: cli_tool ──────────────────────┐
         │                                          │
         │  (unblocks everything)                    │
         │                                          │
         ├──── A.2: WebSocket ──────┐               │
         │                          │               │
         │  (unblocks C.4)          │               │
         │                          │               │
         ├──── A.3: parallel ──┐    │               │
         │                      │    │               │
         ├──── A.4: merge ──┐   │    │               │
         │                  │   │    │               │
         └─ A.5: cli_tools.yaml   │    │               │
            │                  │   │    │               │
            │                  ▼   ▼    ▼               │
            │              ┌─────────────┐             │
            │              │ B.4: workflow│             │
            │              │ (uses all 3) │             │
            │              └─────────────┘             │
            │                                          │
            │           ┌──── C.4: Run view live ─────┤
            │           │                              │
            ▼           ▼                              │
        ┌────────────────────┐                        │
        │ 4-AGENT WORKFLOW   │                        │
        │ (the proof)        │                        │
        └────────────────────┘                        │
                                                      │
         ┌──── B.1: score functions ──────┐          │
         │                                  │          │
         ├──── B.2: simulation ─────────────┤          │
         │                                  │          │
         └──── B.3: researcher/applier ─────┘          │
                                                      │
         (B.1-B.3 are independent of A and C)         │
```

**Reading this:**
- **Day 1, three parallel workstreams start:**
  - **Marvin:** A.1 (cli_tool — 1 week) AND B.1 (score functions — 1 week) — these don't conflict
  - **Iris:** C.1 (React scaffold — 2 weeks, can run in parallel with Marvin's work)
  - **Thoth (me):** B.5 (forge-program.md — 1 day) and start drafting the 4-agent worked-example workflow YAML (1-2 days)

- **Week 2, after A.1 ships:**
  - **Marvin:** branches into A.2, A.3, A.4 (in parallel — 3 workstreams within Stream A)
  - **Marvin:** starts B.2 (simulation harness) in parallel with A.2-A.4
  - **Iris:** continues C.1 (React scaffold) → C.2 (list view) → C.3 (editor view)

- **Week 3-4, after A.2 ships:**
  - **Iris:** C.4 (Run view with live observability) can start
  - **Marvin:** B.3 (researcher + applier + approval card)
  - **Thoth:** finishes 4-agent workflow YAML, starts monitoring doc + staging rollout prep

- **Week 4-5, after A.3, A.4 ship:**
  - **Marvin:** B.4 (the Forge autoresearch Conductor workflow) — this is the integration test for A.3 + A.4
  - **Marvin:** C.5 (HTTP wrapper) — backend for the GUI
  - **Iris:** C.4 finishing + C.6 (integration with C.5)

- **Week 5, end of build:**
  - **All together:** integration testing, bug bash, the 4-agent coding workflow runs end-to-end, the Forge autoresearch runs in staging
  - **Konan (operator):** reviews the first morning brief with the Forge approval card

---

## 3. Week-by-week plan

### Week 1 — Foundation phase (all three streams start)

**Marvin (full time):**
- A.1 (cli_tool step type) — Monday to Friday
- B.1 (score functions + baseline) — can interleave with A.1 or do it in parallel
- **Expected output:** `cli_tool` works in the engine. `analyze()` reports precision/recall/override/composite. Baseline measured.

**Iris (full time):**
- C.1 (React app scaffold) — Vite + React 19 + TS 6 + Tailwind v4 + Olympus tokens
- C.1 includes: MSW mocks, theme toggle, routing, top bar + sidebar
- **Expected output:** App loads, you can navigate between screens with mock data.

**Thoth (me, ~half time):**
- B.5 (`forge-program.md`) — 1 day
- Draft 4-agent worked-example workflow YAML — 1-2 days
- **Expected output:** Strategy document written, example workflow drafted.

**Operator (Konan):**
- Lock the 16 open questions in the two specs (or accept my recommendations)
- Provision staging environment for Forge autoresearch (separate config dir + log file)

**Checkpoint at end of week 1:** Marvin has cli_tool working. Iris has a scaffolded React app. Forge has score functions. If A.1 is blocked, the whole plan slips — that's why A.1 is the first thing Marvin works on.

### Week 2 — Expansion phase (Marvin fans out, Iris continues)

**Marvin (parallel work):**
- A.2 (WebSocket live stream) — 1 week
- A.3 (parallel step type) — 1 week (can run in parallel with A.2)
- A.4 (merge step type) — 1 week (can run in parallel with A.2, A.3)
- B.2 (simulation harness) — 1 week (can run in parallel with A.2-A.4)
- A.5 (cli_tools.yaml + 3 v1 tools) — small task, fit in anywhere

**Iris:**
- C.2 (workflows list view) — start
- C.3 (editor view, canvas + inspector) — start

**Thoth:**
- 4-agent workflow YAML finalized
- Start preparing the staging rollout doc

**Operator:**
- Review Marvin's A.1 PR / implementation, push back if needed

**Checkpoint at end of week 2:** A.2, A.3, A.4 all shipped. B.2 (simulation) shipped. WebSocket live. Merge strategies working.

### Week 3 — Integration phase (Iris can start live view, Marvin on Forge)

**Marvin:**
- B.3 (ForgeResearcher + ForgeApplier + approval card generator) — 1 week
- B.6 (morning-briefing integration step) — small, fits in the week
- C.5 (HTTP wrapper backend) — start

**Iris:**
- C.2 finishing (workflows list with filter chips, status badges)
- C.3 finishing (canvas + inspector + 14 connector config forms)
- C.4 (Run view with WebSocket live observability) — start (A.2 is done, WebSocket URL is real)

**Thoth:**
- Monitor the staging rollout prep
- Coordinate between Marvin and Iris on the WebSocket contract

**Operator:**
- (no action this week)

**Checkpoint at end of week 3:** Forge researcher + applier work. The approval card generator works. Morning-briefing reads it. The GUI's Run view is showing live agent activity.

### Week 4 — Convergence phase (the 4-agent proof)

**Marvin:**
- B.4 (Conductor workflow `forge-overnight-research.yaml`) — the integration test for A.3 + A.4
- C.5 finishing (HTTP wrapper)
- Run the Forge autoresearch end-to-end in staging

**Iris:**
- C.4 finishing (Run view polish)
- C.6 (integration with C.5, bug bash)

**Thoth:**
- Watch the first Forge autoresearch run in staging
- Verify the morning-briefing approval card surfaces correctly
- Document any bugs in the integration

**Operator:**
- Review the first staging Forge approval card
- (no production changes yet — staging only for the first 30 days per Q6)

**Checkpoint at end of week 4:** The Forge autoresearch workflow runs end-to-end in staging. The 4-agent coding workflow also runs end-to-end. The GUI shows live activity for both.

### Week 5 — Polish + production rollout

**Marvin:**
- Bug bash (integration issues between Conductor engine, HTTP wrapper, Forge, morning brief)
- Performance tuning (the WebSocket live stream needs to not flood the GUI)
- Staging hardening (operator override, rollback tested)

**Iris:**
- Final UI polish
- Deploy the React app to relay-7
- Hand off to Konan for first production use

**Thoth:**
- Write the "first 30 days in production" runbook for the operator
- Set up the daily composite-score check (Q7: auto-rollback if composite drops > 0.05)
- Set up the staging → production promotion gate

**Operator:**
- Production cutover for the Forge autoresearch (after 30 days clean staging)
- First morning brief with the approval card in production

**Checkpoint at end of week 5:** The 4-agent coding workflow runs in production. The Forge autoresearch runs nightly in production. The morning brief includes the approval card. The operator has full control via approve/reject commands.

---

## 4. The 4-agent worked-example workflow (the proof)

This is the workflow that proves the whole thing works. Drop this in `~/pantheon/conductor/workflows/claude-x-codex-marvin-hephaestus-feature.yaml` after A.1, A.3, A.4 ship:

```yaml
workflow:
  id: claude-x-codex-marvin-hephaestus-feature
  name: "Feature Implementation — 4 Agents in Tandem, Judge Picks Best"
  version: "1.0.0"
  description: "Marvin (TDD), Hephaestus (architecture), Claude Code, and Codex CLI all implement the same feature in parallel. A judge LLM picks the best. Hephaestus reviews the winner."

  steps:
    - id: spec
      god: thoth
      skill: deep-research
      input: user_request
      output: spec
      timeout: 30m

    - id: parallel-implement
      type: parallel
      fail_mode: slow
      max_concurrency: 4
      branches:
        - id: marvin-impl
          god: marvin
          skill: test-driven-development
          input_from: spec
          timeout: 4h

        - id: hephaestus-impl
          god: hephaestus
          skill: architecture-design
          input_from: spec
          timeout: 4h

        - id: claude-impl
          type: cli_tool
          tool: claude-code
          input:
            prompt: "Implement feature per spec. TDD. Write tests first."
            working_dir: /home/konan/workspace/project
            stream: true
          timeout: 4h

        - id: codex-impl
          type: cli_tool
          tool: codex
          input:
            prompt: "Implement feature per spec. TDD. Write tests first."
            working_dir: /home/konan/workspace/project
            stream: true
          timeout: 4h
      output: four-impls

    - id: pick-best
      type: merge
      inputs: [marvin-impl, hephaestus-impl, claude-impl, codex-impl]
      strategy: llm_pick_best
      strategy_config:
        judge_tool: claude-code
        judge_prompt_template: |
          Four implementations of the same feature.
          Pick the most correct, most idiomatic, best-tested.
          Return verbatim + 3-bullet summary of why.
        timeout: 30m
      output: winning-impl
      gates: [state_gate]

    - id: review
      god: hephaestus
      skill: code-review
      input_from: pick-best
      gates: [logic_gate, state_gate]
      loop:
        max_retries: 3
        on_fail: back_to_pick-best
      output: reviewed

    - id: ship
      god: marvin
      skill: shipping-and-launch
      input_from: review
      gates: [state_gate]
      output: shipped
```

**What this gives you:** a single workflow that runs Marvin, Hephaestus, Claude Code, and Codex CLI in parallel, with live observability for the CLI tools, a judge picking the winner, Hephaestus reviewing, and Marvin shipping. Wall-clock: ~5 hours instead of ~16 hours sequential.

**This is the canonical proof** that the parallel-work primitive works. Once this runs, the pattern generalizes to anything.

---

## 5. The 3 open questions (locked)

Per Konan's call on 2026-06-15, the 8 Forge open questions are now 7 (Q2 resolved by the morning-brief approval card design). The remaining open questions across both specs:

**Conductor CLI Orchestration (8 questions, all open, recommendations accepted):**

| # | Question | Recommendation |
|---|---|---|
| 1 | Default `stream: true` or `false` for `cli_tool`? | **false** (opt-in) |
| 2 | Nested `parallel`? | **Yes, max 3 levels** |
| 3 | `llm_pick_best` returns chosen + reasoning? | **Both** |
| 4 | Default `fail_mode` for `parallel`? | **`fast`** |
| 5 | WebSocket auth? | **API key query param v1** |
| 6 | `cli_tools.yaml` location? | **`~/pantheon/conductor/config/cli_tools.yaml`** |
| 7 | Multi-turn streaming input? | **No for v1** |
| 8 | Tool binary not installed? | **Fail fast** |

**Forge Autoresearch (7 remaining open questions, Q2 resolved):**

| # | Question | Recommendation |
|---|---|---|
| 1 | Default time budget? | **90 min** |
| 2 | ~~Auto-apply default?~~ | **RESOLVED:** safe = auto, controversial = morning-brief card (see §4.1) |
| 3 | Score functions location? | **Hardcoded in `ichor_forge.py`** |
| 4 | Judge: LLM or deterministic? | **Deterministic for v1** |
| 5 | Schedule: Conductor cron? | **Yes** |
| 6 | Staging only first 30 days? | **Yes** |
| 7 | Auto-rollback on regression? | **Yes, daily check** |
| 8 | Notification channel? | **NATS + Telegram bridge** |

**If any of these need to be flipped, do it now** — the spec is the contract, and changing it after Marvin starts Phase 1 is rework.

---

## 6. The risks (and what to do about them)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **A.1 slips past week 1** | Medium | High (blocks everything) | If A.1 isn't done by Friday of week 1, escalate. Have Marvin start a stub `cli_tool` that just returns `not implemented` to unblock Iris's mock design. |
| **WebSocket can't keep up with 4 parallel agents** | Medium | Medium | Rate-limit events to the GUI. Buffer in the engine. Drop low-priority events under load. Iris's UI can show a "live" indicator that turns "degraded" if events are dropping. |
| **CLI tool subprocess management is buggy** (leaked processes, orphan subprocesses) | High | Medium | Marvin writes a process supervisor in Phase A.1 that tracks all spawned subprocesses and kills them on workflow abort. Add a test that spawns 100 subprocesses and verifies cleanup. |
| **LLM judge picks the wrong winner** | Low | Low | The judge has the same four outputs to compare; the delta between "good" and "bad" is usually clear. The score function trend in the morning brief shows whether the system is actually getting better, regardless of individual judge calls. |
| **Operator gets approval-card fatigue** | Medium | Medium | If the operator rejects 5+ controversial changes in a row, the Forge's controversy classifier should be retrained. Add a "controversy rate" metric to the morning brief. |
| **Staging and production diverge** | Low | Medium | The staging config uses a different `cli_tools.yaml`, different `gates/*.yaml`, different `all.jsonl` log file. The Forge autoresearch workflow accepts a `--config-dir` flag to handle this. |

---

## 7. The success criteria (what "done" looks like)

**At end of week 5, all of the following are true:**

1. **A 4-agent coding workflow runs end-to-end.** The `claude-x-codex-marvin-hephaestus-feature.yaml` workflow starts, runs Marvin + Hephaestus + Claude Code + Codex CLI in parallel, picks the best, reviews, ships. Live observability in the GUI.

2. **The Forge autoresearch runs nightly in staging.** The 22:00 local cron fires, runs 3 parallel experiments, picks the best, auto-applies safe changes, writes an approval card. The 06:00 morning brief includes the approval card.

3. **The first 30 days of staging data shows measurable improvement.** Composite score trending up. Operator approving most controversial changes. No regressions.

4. **The Conductor GUI has 4 live screens.** Empty (soulforge start), List (workflows), Editor (canvas + inspector + soulforge chat), Run (live WebSocket events). The mock at `http://100.68.106.59:8889/` is now a production React app at `conductor.theoforgesolutions.com` (or whatever URL).

5. **The handoff documents are complete.** The 4-agent workflow is documented in the Ledger PRD's "Add-on: Coding Orchestration" section. The Forge autoresearch is documented in the Conductor v2 spec's "Appendix C: Forge Integration." Any new operator has a runbook.

6. **The system handles 1 feature/day through the 4-agent workflow without operator intervention** (except the morning approval card).

---

## 8. The documents to update as we go

**As A.1 ships:**
- `~/athenaeum/Codex-Pantheon/specs/conductor-cli-orchestration.md` — bump version to 1.1.0, mark Phase 1 done.
- `~/pantheon/conductor/v2/CHANGELOG.md` (or wherever Conductor v2 keeps its changelog) — note the new step type.

**As B.1 ships:**
- `~/athenaeum/Codex-Pantheon/specs/forge-autoresearch.md` — bump to 1.1.0, document the baseline numbers.
- `~/.hermes/ichor/forge/program.md` — include the baseline in the strategy document.

**As the 4-agent workflow runs successfully:**
- `~/projects/ledger/PRD.md` — add a section: "Coding Orchestration Add-on: 4-Agent Tandem Workflow"
- `~/projects/ledger/BUILD-PATH.md` — add the worked-example workflow to the add-on list

**As the Forge autoresearch runs in production:**
- `~/athenaeum/Codex-Pantheon/specs/forge-autoresearch.md` — bump to 1.2.0, document the rollout results
- `~/athenaeum/Codex-Pantheon/DECISIONS.md` — log the staging-to-production decision

**As Iris ships C.4 (Run view):**
- `~/projects/ledger/CONDUCTOR-UI-BUILD-PLAN.md` — mark C.1-C.4 done, link to the deployed app

---

## 9. What I need from you to start

1. **Lock the 15 open questions** (8 from CLI orchestration + 7 from Forge) with "go with your recommendations" or specific overrides. **This is the only blocker.** Once the questions are locked, the spec is the contract and Marvin can start.

2. **Provision the staging environment** for the Forge autoresearch. Either:
   - A separate config dir (`~/.hermes/ichor/forge-staging/`) with its own gates/*.yaml, all.jsonl, program.md
   - A separate machine that runs a copy of the same setup
   - (a "staging" config dir is fine for v1; v2 can promote to a real environment)

3. **Confirm Marvin is free to start A.1 and B.1 in parallel.** Check the current Conductor v2 work queue — the most recent briefs are `conductor-step-4.7-brief-1.md` and `conductor-step-4.5-brief-3.md`. Make sure those don't conflict with A.1/B.1.

4. **Confirm Iris is free to start C.1.** She has the Conductor UI build plan and the conductor-ui dir layout. The 4-agent worked-example workflow gives her concrete data to design against.

5. **(Optional but recommended)** Tell me to draft the 4-agent workflow YAML now as a real file. It's ready in §4 above; I can drop it in `~/pantheon/conductor/workflows/` today. Once A.1 ships, Marvin can run it.

**Once those are confirmed, the build starts Monday.**

---

## 10. Document history

| Date | Author | Change |
|---|---|---|
| 2026-06-16 | Thoth | v1.0 — clean build plan for parallel work, 3 streams, 5 weeks |
