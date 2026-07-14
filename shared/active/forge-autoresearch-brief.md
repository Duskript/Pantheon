# Forge Autoresearch — Build Brief

**Spec:** `~/athenaeum/Codex-Pantheon/specs/forge-autoresearch.md` (v1.0.0)
**Status:** pending → in-progress on Marvin's ack
**Owner:** Marvin (engine + simulation + workflow), Thoth (forge-program.md + coordination)
**Spec author:** Thoth, 2026-06-15
**Date:** 2026-06-15
**Pattern reference:** Karpathy's `autoresearch` (github.com/karpathy/autoresearch)

---

## TL;DR

Convert the Ichor Forge from operator-triggered analysis to a **closed-loop autoresearch system**. Each night, a Conductor workflow runs three parallel experiments (max-precision, max-recall, max-composite) that each propose 10 candidate gate-config changes, simulate each against the last 7 days of intervention logs, and pick the best. A judge picks the winner across the three experiments. Safe changes are auto-applied; controversial ones are queued for operator review. The Forge gets measurably better every night, with the operator waking up to a NATS notification.

## What came before (context)

- **The Ichor Forge exists and works** at `~/pantheon/lib/ichor_forge.py` (849 LOC, v0.4). It has `ForgeAnalyzer`, `ForgeSmith`, `ForgeReport` — read logs, propose changes, generate summaries.
- **The intervention log** is at `~/.hermes/ichor/forge/all.jsonl`. Each line is a JSONL intervention record (timestamp, gate, passed, message, recovery_hint, model, session_id, user_intent, god).
- **The five gate config files** (what the Forge proposes changes to) live at `~/.hermes/ichor/gates/` — `intent_keywords.yaml`, `phase_patterns.yaml`, `phase_tools.yaml`, `logic_patterns.yaml`, `cap_config.yaml`.
- **Today the Forge is operator-triggered.** `forge.analyze()` is run on demand, reports findings, proposes changes. Operator reads, decides, applies. No closed loop, no measurement, no overnight improvement.
- **The Karpathy `autoresearch` pattern (March 2026)** is the missing piece: `program.md` (strategy doc) + `train.py` (the code) + a score function. Forge = train.py, forge-program.md = program.md, precision/recall = val_bpb.

## What this brief is

This is the build brief for `forge-autoresearch.md`. Six phases per spec §10:

| Phase | What | Owner | Estimate |
|---|---|---|---|
| 1 | Score functions (precision, recall, override) + baseline | Marvin | 1 week |
| 2 | Simulation harness (`analyze_with_config(test_config, days)`) | Marvin | 1 week |
| 3 | ForgeResearcher + ForgeApplier (experiment loop, controversy classifier) | Marvin | 1 week |
| 4 | Conductor workflow (`forge-overnight-research.yaml`) | Marvin + Thoth | 1 week |
| 5 | `forge-program.md` (the strategy document) | Thoth | 1 day |
| 6 | Monitor + iterate | Operator (Konan) + Thoth | 2 weeks, ongoing |

Phases 1-3 are sequential (each builds on the previous). Phase 4 can start once Phase 3 is done. Phase 5 happens in parallel with Phase 4. Phase 6 is the production rollout.

## Your task (Phase 1 only, this brief)

**Add the three score functions to the Forge, and establish the current baseline.** Per spec §3 and §10.1:

1. Extend `ichor_forge.py` with a new method:
   ```python
   def compute_score_functions(
       self,
       interventions: list[InterventionRecord],
       lookback_days: int = 7
   ) -> ScoreMetrics:
       """Compute precision, recall, override_rate, composite from intervention log."""
   ```
2. Define `ScoreMetrics` as a new dataclass:
   ```python
   @dataclass
   class ScoreMetrics:
       precision: float             # correct_blocks / total_blocks (target ≥ 0.95)
       recall: float                # blocks_that_should_have_fired / events_that_should_have_been_blocked (target ≥ 0.90)
       override_rate: float         # operator_overrides / total_interventions (target ≤ 0.02)
       composite: float             # 0.4 * precision + 0.4 * recall + 0.2 * (1 - override_rate)
       sample_size: int             # how many interventions informed this
       window_start: float
       window_end: float
   ```
3. Add the score metrics to the existing `analyze()` output. New field: `analyze_result.score_metrics: ScoreMetrics`
4. Define "correct block" and "should have blocked" precisely (spec §3.1-3.2). The recovery_hint field and override flag are your signals.
5. Run `analyze()` against the **last 30 days** of `all.jsonl` to establish a baseline. Save the result to `~/.hermes/ichor/forge/baseline-2026-06-15.json` (or whatever today's date is).
6. Document the baseline in a new file `~/.hermes/ichor/forge/baseline-history.jsonl` — append a JSONL line per baseline run with the timestamp and metrics.
7. Tests: synthetic intervention data → known score functions. Edge cases: zero interventions, all-pass, all-block, mixed.

**~150 LOC in `ichor_forge.py` extension** per spec estimate.

### Validation

```bash
# After implementing, you should be able to:
python3 -m pytest tests/test_ichor_forge.py -q -k "score"
# Should pass with ≥ 6 tests covering the spec's behavioral contract

# And hand-test the baseline:
python3 -c "
from lib.ichor_forge import IchorForge
forge = IchorForge()
result = forge.analyze(days=30)
print(f'Precision: {result.score_metrics.precision:.3f}')
print(f'Recall:    {result.score_metrics.recall:.3f}')
print(f'Override:  {result.score_metrics.override_rate:.3f}')
print(f'Composite: {result.score_metrics.composite:.3f}')
"
# Should print the baseline numbers; save them to baseline-2026-06-15.json
```

### What you do NOT need to do in Phase 1

- Don't implement the simulation harness (`analyze_with_config`) — that's Phase 2
- Don't implement `ForgeResearcher` or `ForgeApplier` — that's Phase 3
- Don't write the Conductor workflow — that's Phase 4
- Don't write `forge-program.md` — that's my Phase 5
- Don't run the autoresearch loop yet — that's Phase 6

## Open questions needing your decision

The spec §11 has 8 open questions. My recommendations:

| # | Question | Recommendation |
|---|---|---|
| 1 | Default time budget per experiment cycle? | **90 minutes** |
| 2 | Auto-apply enabled by default? | **RESOLVED 2026-06-15:** Safe changes (additive, low-variance) auto-apply. Controversial changes (destructive, high-variance) queue for operator approval via the morning-briefing approval card. No CLI flag. See spec §4.1. |
| 3 | Score function definitions in `program.md` or hardcoded? | **Hardcoded in `ichor_forge.py`** |
| 4 | Judge: LLM or deterministic? | **Deterministic for v1** (cheaper, no LLM variance) |
| 5 | Schedule: Conductor cron or system cron? | **Conductor cron** (visible in workflow YAML) |
| 6 | Staging only first 30 days, then promote? | **Yes, staging only first** |
| 7 | Auto-rollback if composite drops > 0.05? | **Yes, daily composite check + auto-rollback** |
| 8 | Notification: NATS, Telegram, or both? | **NATS for machine, Telegram for human** (via existing bridge) |

Confirm or push back before starting Phase 1. The most important: Q3 (score function location) and Q4 (judge type) affect the Phase 1 code structure.

## Reference files

- **Spec (full):** `~/athenaeum/Codex-Pantheon/specs/forge-autoresearch.md`
- **Existing Forge:** `~/pantheon/lib/ichor_forge.py` (the file to extend)
- **Clawforge mechanics:** `~/pantheon/lib/clawforge/` (the underlying data layer)
- **Intervention log:** `~/.hermes/ichor/forge/all.jsonl` (the data source)
- **Gate config files:** `~/.hermes/ichor/gates/*.yaml` (what the Forge proposes changes to)
- **Karpathy's reference:** github.com/karpathy/autoresearch (the pattern; we don't share code)

## Dependency on the CLI Orchestration spec

The Phase 4 Conductor workflow uses the `cli_tool` + `parallel` + `merge` step types from `conductor-cli-orchestration.md`. **You can do Phases 1-3 of this spec without waiting for the CLI orchestration work.** Phase 4 is the only one that needs the new step types.

The two briefs can run in parallel:
- **You (Marvin):** start Forge autoresearch Phase 1 (score functions) AND start CLI orchestration Phase 1 (cli_tool step type) in parallel. Both are 1 week. They don't conflict.
- **Thoth (me):** write the Conductor workflow in Phase 4 once both Phase 1s ship.

## What this means for the rest of Pantheon

When this lands:
- **The Ichor harness improves measurably every night.** The score functions give a real number; the operator queue is small; the rollout is observable.
- **The Forge stops being "operator runs it once a month."** It becomes a continuously self-improving system.
- **The pattern is reusable.** Once Forge autoresearch works, the same pattern can be applied to other Pantheon subsystems: Conductor itself (optimize workflow routing), Hermes (optimize message prioritization), or any other component with measurable outputs.

## Contact

- Spec questions / changes / pushback → Thoth
- Engine implementation questions → Marvin (you)
- `forge-program.md` author → Thoth (after Phase 3)
- Conductor workflow → Thoth (after Phase 1s of both specs ship)
- Operator review of the queue during Phase 6 → Konan
