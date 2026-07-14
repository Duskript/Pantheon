# Clawforge Pass 3 — Exporter API Contract

**Date:** 2026-06-11
**Status:** LOCKED — exporters must call only the functions in this file.
**Plan ref:** `PASS3_PLAN.md` Phase 3.0 (pre-flight API audit)

---

## What the spec assumed vs. what exists

The meta-learning spec (`clawforge-revision-meta-learning.md`) sketched
3 exporter modules (`pattern_exporter.py`, `adjustment_exporter.py`,
`learning_exporter.py`) and listed the functions they would call. The
audit confirmed: **0 of 8 assumed functions exist**. The spec was
written aspirationally.

What does exist (verified 2026-06-11):

| Spec assumed | Reality | Verdict |
|---|---|---|
| `get_recent_outcomes(days)` | Does not exist | **DEFERRED to Pass 3.1** — no outcome-tracking system in Pantheon yet |
| `extract_patterns_from_outcomes()` | Does not exist | DEFERRED with above |
| `compute_retrieval_stats()` | Does not exist | DEFERRED with above |
| `detect_tier_a_coverage_gaps()` | Does not exist | DEFERRED with above |
| `get_recent_interventions()` | Exists as `ForgeAnalyzer.load_records(days, god)` | **USE THIS** |
| `extract_applied_adjustments()` | Exists as `ForgeAnalyzer.suggest_adjustments(records, patterns)` | **USE THIS** |
| `compute_gate_health()` | Exists as `ForgeAnalyzer.compute_metrics(records)` | **USE THIS** |
| `get_recent_learnings()` | Does not exist (no phronesis/dojo signal source) | **DEFERRED to Pass 3.1** |

**Builder decisions made in this audit (locked):**

1. `pattern_exporter.py` (memory patterns) — **DEFERS to Pass 3.1** because
   no outcome tracking system exists. The function is real and useful
   once Ichor's hybrid backend exposes a "last N queries + outcome
   rating" API. The spec wrote it as if the function existed; the
   audit caught that it doesn't.

2. `adjustment_exporter.py` (forge adjustments) — **SHIPS**. The
   `ichor_forge` module already has the full pipeline
   (`ForgeAnalyzer.analyze()`). 65 real records already exist in
   `~/.hermes/ichor/forge/all.jsonl`. Phase 3.3 will call
   `analyze()` (with the bug workaround noted below) and emit real
   `forge.adjustment.submitted` entries.

3. `learning_exporter.py` (phronesis/dojo learnings) — **DEFERS to Pass 3.1**.
   No "agent self-improvement signal" exists. `ichor_patterns.py`
   is regex patterns for FTS5, not the learning events the spec
   described. Phronesis (formerly Hermes Dojo) might emit something useful in the future;
   we wait for that source.

4. `instance_id.py` — **SHIPS** regardless. It's a 30-line utility;
   cheap to build and Pass 3.1/3.2 exporters will need it.

## Known bug in `ichor_forge.ForgeAnalyzer.analyze()`

`analyze()` at `ichor_forge.py:395` calls
`load_records(days=days, god=god)`, but the caller may have already
passed in pre-loaded `records`. When you call `analyze(records=...)`
the bug fires (it tries to subtract a list from a float).

**Workaround in Pass 3.3:** call each pipeline stage directly:

    analyzer = ForgeAnalyzer()
    records = analyzer.load_records(days=7)
    metrics = analyzer.compute_metrics(records)
    patterns = analyzer.detect_patterns(records, metrics)
    adjustments = analyzer.suggest_adjustments(records, patterns)

This bypasses the broken `analyze()` aggregator and is the
recommended usage until the upstream bug is fixed.

## Locked function signatures (what the exporters call)

### Adjustment exporter (forge) — `adjustment_exporter.py`

Imports: `from ichor_forge import ForgeAnalyzer, ForgeAdjustment`

```python
def export_forge_adjustments(instance_id: str, days: int = 7) -> dict:
    """Build the forge-adjustments.json submission entry from local
    intervention data.

    Returns: dict matching the `forge.adjustment.submitted` schema:
      {
        "schema_version": 1,
        "instance_id": <sha256(machine_id)[:12]>,
        "submitted_at": <iso8601>,
        "span_days": days,
        "total_interventions": int,
        "adjustments": [
          {
            "type": "model_threshold" | "intent_keywords" | "phase_keywords" | ...,
            "gate": "logic_gate" | "state_gate" | ...,
            "target": str,                # what's being tuned
            "old_value": Any,
            "new_value": Any,
            "reason": str,
            "effectiveness": {            # computed from current data, not a "before/after"
              "instances_tested": 1,     # always 1 for an exporter (this instance)
              "interventions": int,
              "block_rate_before": float,
              "interventions_after": int, # not available; omit if so
              "reduction_pct": float | None,
            }
          }, ...
        ],
        "gate_health": {
          "<gate_name>": {
            "interventions": int,
            "block_rate": float,
            "healthy": bool
          }, ...
        }
      }
    """
```

**Anonymization guarantee (per spec §9, verified by tests):**
- No `session_id` in the output
- No raw event text
- No `user_intent` text (we use it as a counter key but never emit it)
- `instance_id` = first 12 hex of `sha256(machine_id)` (see instance_id.py)

### Memory pattern exporter — DEFERRED

Status: deferred to Pass 3.1 (after Ichor exposes outcome API).

When the API exists, the contract will be:

```python
def export_memory_patterns(instance_id: str, days: int = 7) -> dict:
    """Build the memory-patterns.json submission from local outcome data.
    Returns the spec's `memory.pattern.submitted` payload shape.
    """
```

### Phronesis learning exporter — DEFERRED (formerly: Dojo learning exporter)

Status: deferred to Pass 3.1 (no source signal exists).

### Instance ID — `instance_id.py`

```python
def get_instance_id() -> str:
    """Return the first 12 hex chars of sha256(machine_id).
    Consistent across restarts; cannot be reversed to identify the host.
    Falls back to a synthetic hash if /etc/machine-id is missing
    (containers, non-Linux).
    """
```

## Test contract

For every exporter, the file ships with a self-test (`if __name__ ==
"__main__":`) that:
1. Calls the export function
2. Asserts the output has no forbidden keys (`session_id`, raw
   `user_intent` text, `query` text, etc.)
3. Asserts `instance_id` matches the expected length/format
4. Prints a sample entry to stdout

This is the gate. No exporter ships without a green self-test.

## Out of scope (Pass 3.0 → 3.4)

- Real-time pattern sync (weekly cadence per spec)
- Auto-publish of recommendations (execute_flag is the safety model)
- Pattern marketplace / monetization
- LLM in any exporter
- Cross-instance multi-tenancy at the exporter level (instance_id
  handles it)

---

**End of contract. Builders proceed to Phase 3.1+ against this file.**
