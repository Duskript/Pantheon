"""Conductor v2 `merge` step strategies.

Companion to engine.py — implements the 4 non-LLM merge strategies from
spec §2.3:

  - `concat`         — concatenate inputs in order, separated by headers
  - `first`          — first successful input (in `inputs` order)
  - `diff`           — structured diff between inputs (≥2 inputs)
  - `vote`           — majority on structured data, ties broken by order

The 2 LLM-merge strategies (`llm_summarize`, `llm_pick_best`) are
implemented in engine.py as `_exec_merge` because they reuse the engine's
`llm_call` path (a subprocess invocation per brief locked decision #4).
This module is pure-function and LLM-free so the test suite can hit it
without mocking an LLM.

Output contract for every strategy (per spec §2.3):
  {
    "strategy":  <strategy name>,
    "merged_value": <the actual merged output — type depends on strategy>,
    "sources":   [list of step IDs that contributed],
  }
`llm_pick_best` extends this with `chosen_source` and `judge_output` —
see engine._exec_merge for that path.

All strategies accept `inputs` (a list of step_id strings, in declared
order) and `values` (a parallel list of the corresponding resolved
output dicts from `inst.context_bag`). The engine resolves step IDs to
their outputs before calling the strategy — this module never touches
the instance directly. Keeping the boundary clean means the strategies
are testable with plain dicts.
"""

from __future__ import annotations

from difflib import unified_diff
from typing import Any, Callable


# Type alias: an LLM-merge function takes the inputs + values and returns
# a dict with the chosen output and any judge metadata. Defined here so
# the engine can pass an LLM-calling function into the dispatcher.
LLMMergeFn = Callable[[list[str], list[Any], dict[str, Any]], dict[str, Any]]


# -----------------------------------------------------------------------------
# Public dispatcher
# -----------------------------------------------------------------------------

# Strategies that this module handles. The engine routes the LLM ones
# to `_call_llm` instead, but lists them here for validation parity.
NON_LLM_STRATEGIES = ("concat", "first", "diff", "vote")
ALL_STRATEGIES = NON_LLM_STRATEGIES + ("llm_summarize", "llm_pick_best")


def run_merge(
    strategy: str,
    inputs: list[str],
    values: list[Any],
    strategy_config: dict[str, Any] | None = None,
    llm_fn: LLMMergeFn | None = None,
) -> dict[str, Any]:
    """Run `strategy` over the resolved step outputs.

    Args:
        strategy: one of the 6 strategy names from spec §2.3
        inputs:   list of step_ids in declared order (preserved by `vote` tiebreak)
        values:   parallel list of resolved step outputs (may be None for
                  failed/unresolved steps — strategies handle gracefully)
        strategy_config: strategy-specific config (judge_prompt_template,
                          timeout, etc.) — used by LLM strategies
        llm_fn:   callable that takes (inputs, values, strategy_config) and
                  returns a merge result dict; required for `llm_*`
                  strategies. If omitted and strategy is LLM, raises.

    Returns:
        dict with the standard merge output schema. `llm_pick_best` adds
        `chosen_source` and `judge_output`.

    Raises:
        ValueError: unknown strategy, mismatched input lengths, or missing
                    llm_fn for an LLM strategy
    """
    if strategy not in ALL_STRATEGIES:
        raise ValueError(
            f"unknown merge strategy {strategy!r}; valid: {ALL_STRATEGIES}"
        )
    if len(inputs) != len(values):
        raise ValueError(
            f"merge inputs/values length mismatch: {len(inputs)} ids, "
            f"{len(values)} values"
        )
    if not inputs:
        raise ValueError("merge requires at least one input")

    cfg = strategy_config or {}

    if strategy == "concat":
        return _concat(inputs, values)
    if strategy == "first":
        return _first(inputs, values)
    if strategy == "diff":
        return _diff(inputs, values)
    if strategy == "vote":
        return _vote(inputs, values)
    # LLM strategies — delegate.
    if llm_fn is None:
        raise ValueError(
            f"strategy {strategy!r} requires an llm_fn (engine's LLM path)"
        )
    return llm_fn(inputs, values, cfg)


# -----------------------------------------------------------------------------
# Non-LLM strategies
# -----------------------------------------------------------------------------

def _concat(inputs: list[str], values: list[Any]) -> dict[str, Any]:
    """Concatenate non-None inputs in declared order, separated by headers.

    Each input is rendered via `str(value)` and prefixed with a header
    line `=== <step_id> ===`. None values are skipped (failed inputs
    don't break the concatenation). The merged_value is a string.
    """
    parts: list[str] = []
    sources: list[str] = []
    for sid, val in zip(inputs, values):
        if val is None:
            continue
        sources.append(sid)
        parts.append(f"=== {sid} ===\n{val}")
    return {
        "strategy": "concat",
        "merged_value": "\n\n".join(parts),
        "sources": sources,
    }


def _first(inputs: list[str], values: list[Any]) -> dict[str, Any]:
    """First non-None input wins (in `inputs` order). Sources is a single
    element — the chosen step id."""
    for sid, val in zip(inputs, values):
        if val is not None:
            return {
                "strategy": "first",
                "merged_value": val,
                "sources": [sid],
            }
    # All inputs failed — return None with empty sources. The engine
    # treats a merge with all-None inputs as failed (no winner).
    return {
        "strategy": "first",
        "merged_value": None,
        "sources": [],
    }


def _diff(inputs: list[str], values: list[Any]) -> dict[str, Any]:
    """Structured diff between inputs.

    For text inputs (str): produces a unified diff of the strings in
    declared order (N-1 diffs). For dict inputs: produces a key-by-key
    diff (added/removed/changed keys). Mixed types fall back to string
    representation.

    Output schema:
      {
        "strategy": "diff",
        "merged_value": <dict of per-pair diffs>,
        "sources": [list of all input ids that participated],
      }
    """
    if len(inputs) < 2:
        raise ValueError(
            f"merge strategy 'diff' requires >=2 inputs, got {len(inputs)}"
        )
    # Skip None values from participating (they have nothing to diff).
    # Track which inputs are present so the sources list is honest.
    pairs: list[tuple[str, Any]] = [
        (sid, val) for sid, val in zip(inputs, values) if val is not None
    ]
    if len(pairs) < 2:
        raise ValueError(
            "merge strategy 'diff' requires >=2 non-None inputs"
        )
    sources = [sid for sid, _ in pairs]
    merged: dict[str, Any] = {}
    for i in range(len(pairs) - 1):
        sid_a, val_a = pairs[i]
        sid_b, val_b = pairs[i + 1]
        key = f"{sid_a}__vs__{sid_b}"
        merged[key] = _diff_pair(val_a, val_b, sid_a, sid_b)
    return {
        "strategy": "diff",
        "merged_value": merged,
        "sources": sources,
    }


def _diff_pair(a: Any, b: Any, id_a: str, id_b: str) -> dict[str, Any]:
    """Produce a single diff between two values, dispatched by type."""
    if isinstance(a, str) and isinstance(b, str):
        # unified_diff expects newline-terminated lines.
        a_lines = a.splitlines(keepends=True)
        b_lines = b.splitlines(keepends=True)
        if a_lines and not a_lines[-1].endswith("\n"):
            a_lines[-1] += "\n"
        if b_lines and not b_lines[-1].endswith("\n"):
            b_lines[-1] += "\n"
        diff_text = "".join(unified_diff(
            a_lines, b_lines, fromfile=id_a, tofile=id_b, lineterm="",
        ))
        return {"type": "text", "diff": diff_text}
    if isinstance(a, dict) and isinstance(b, dict):
        return {"type": "dict", "changes": _dict_diff(a, b)}
    # Mixed or scalar — fall back to string equality check.
    return {
        "type": "scalar",
        "from_id": id_a,
        "to_id": id_b,
        "equal": a == b,
        "from": a,
        "to": b,
    }


def _dict_diff(a: dict[str, Any], b: dict[str, Any]) -> dict[str, list[str]]:
    """Key-by-key dict diff: lists of added, removed, changed keys."""
    a_keys = set(a.keys())
    b_keys = set(b.keys())
    added = sorted(b_keys - a_keys)
    removed = sorted(a_keys - b_keys)
    changed = sorted(k for k in (a_keys & b_keys) if a[k] != b[k])
    return {
        "added": [k for k in added],
        "removed": [k for k in removed],
        "changed": changed,
    }


def _vote(inputs: list[str], values: list[Any]) -> dict[str, Any]:
    """Majority result on structured data; ties broken by `inputs` order.

    Each non-None value gets a vote. The value with the most votes wins.
    Ties are broken by the EARLIEST position in `inputs` — so if A and B
    both have 2 votes each, the one that appears first in `inputs` wins
    (matches the spec table's "ties broken by `inputs` order (first
    wins)" note for `vote`).

    Equality is structural for both hashable and unhashable types.
    Hashable values (str, int, float, tuple, etc.) are grouped by
    `hash(val)`. Unhashable values (dict, list, set) are grouped by a
    canonical JSON form with sorted keys, so two distinct dicts with
    the same content count as the same value. Use `concat` if you
    need textual voting.
    """
    counts: dict[str, list[str]] = {}  # canonical key -> [step_id, ...]
    value_map: dict[str, Any] = {}
    for sid, val in zip(inputs, values):
        if val is None:
            continue
        # Produce a canonical key for grouping equal values together.
        # Hashable types (str, int, float, tuple, ...) get keyed by
        # their hash. Unhashable types (dict, list, set) get keyed by
        # a json.dumps canonical form with sorted keys — so two
        # distinct dicts with the same content land in the same
        # bucket regardless of object identity. Non-JSON-serializable
        # values fall through to repr() so vote still functions on
        # exotic types (custom objects, file handles, etc.).
        try:
            hash(val)
            key: str = f"h:{hash(val)}"
        except TypeError:
            try:
                import json as _json
                key = f"j:{_json.dumps(val, sort_keys=True, default=str)}"
            except (TypeError, ValueError):
                key = f"r:{repr(val)}"
        counts.setdefault(key, []).append(sid)
        value_map[key] = val
    if not counts:
        return {"strategy": "vote", "merged_value": None, "sources": []}
    # Pick the value with the highest vote count; tiebreak by earliest
    # position in `inputs` (smallest min_index in the per-value list).
    # Score semantics: higher tuple wins under `max()`. First element
    # is the raw count (more votes = larger first element = wins).
    # Second element is `-min_index` so a SMALLER min_index produces a
    # LARGER (less negative) second element, winning the tiebreak.
    def score(key: str) -> tuple[int, int]:
        ids = counts[key]
        min_index = min(inputs.index(s) for s in ids)
        return (len(ids), -min_index)
    winner_key = max(counts.keys(), key=score)
    return {
        "strategy": "vote",
        "merged_value": value_map[winner_key],
        "sources": counts[winner_key],
    }
