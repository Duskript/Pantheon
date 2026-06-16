# Clawforge Pass 3 — running log

Last update: 2026-06-11 18:00 MDT

## Phases shipped
- **Phase 1** (2026-06-11): all 4 new registries on Relay-7 verified live
- **Phase 2** (2026-06-11): NATS subscribers + apply flow on Pantheon
- **Phase 3** (2026-06-11): per-instance exporters on Pantheon — forge
  adjustment exporter ships real data; memory/dojo deferred to Pass 3.1
- **Phase 4** (2026-06-11): 3 weekly systemd user timers scheduled
  (Mon memory / Tue forge / Wed dojo at 03:00 UTC); sentinel-file
  opt-in per exporter; forge verified end-to-end
- **Phase 5** (2026-06-11): end-to-end smoke test, 4/4 assertions
  pass. See journal `2026-06-11-clawforge-pass3-phase5-smoke.md`

## Deferred to Pass 3.1
- `pattern_exporter.py` (memory patterns) — no source data API yet
- `learning_exporter.py` (dojo learnings) — no source data API yet

## Outstanding
- Phase 6: `PATTERN_SHARING_GUIDE.md` + `CONNECT_ENTERPRISE.md` delta
  + `PASS1_PLAN.md` Pass 3 status section
- 4.5: natural fire verification — fires already observed on Mon
  (memory), Tue (forge), Wed (dojo) at 03:00 UTC; just need to confirm
  the next 3 weekly cycles

## Phase 6 — PAUSED (per user direction 2026-06-11)

Phase 6 docs are blocked until BOTH of these land:
1. **Memory side complete** — the docs need to describe what an
   instance gets out of pattern sharing *with* the full memory
   pipeline. The Entity-Relationship Graph design (Thoth, 2026-06-11)
   and any subsequent memory-side work is in scope.
2. **GitHub delta known** — Tallon (Enterprise) runs PatternSharing
   via the proxy and may need GitHub-side updates. Need to confirm
   what's in the relevant repos before writing install/upgrade
   instructions.

Reason: writing the docs now would mean a second pass to revise
them once the memory and GitHub work is in. Better to wait and write
once.

## Operator action
- Remove `smoke_test_*` entries from all 4 registries on Relay-7
  (smoke test left 6 forge-adjustments + 2 pattern-effectiveness
  test entries; they don't affect real patterns but should be cleaned
  before Pass 3.1 begins)
