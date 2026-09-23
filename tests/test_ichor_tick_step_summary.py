"""Regression tests for the ichor_tick step-summary reporting fixes (2026-09-22).

Both defects were the same class as the clawforge egress bug: a log line that
reported success — or an absence of data — while meaning nothing. A loop must
assert that it *did* something, not that it exited cleanly.

These tests exercise the real production helpers (`_fmt_verify`,
`_fmt_improve`) and the real step function (`_step_verify`), not copies of them.
"""
from __future__ import annotations

import json

import pytest

from lib import ichor_tick as t


# ── D6: verify summary must render the value the step returns ──────────────

def test_fmt_verify_renders_present_recall_value():
    """A present recall value must be rendered, never swallowed as 'no data'."""
    assert t._fmt_verify({"benchmark": {"recall_at_5": 0.45}}) == "recall=0.45"
    assert t._fmt_verify({"benchmark": {"recall_at_5": 1.0}}) == "recall=1.0"


def test_fmt_verify_says_no_data_only_when_there_is_none():
    assert t._fmt_verify({"benchmark": {"recall_at_5": 0.0}}) == "no data"
    assert t._fmt_verify({}) == "no data"
    assert t._fmt_verify({"benchmark": None}) == "no data"


def test_verify_step_output_survives_the_formatter(tmp_path, monkeypatch):
    """End-to-end: the real step's return value must not render as 'no data'.

    This is the guard that would have caught the original bug — the step
    returned `benchmark`, the formatter read `benchmark_results`/`recall`.
    """
    home = tmp_path
    (home / ".hermes").mkdir(parents=True)
    (home / ".hermes" / "ichor_weights_history.json").write_text(json.dumps({
        "baseline": {}, "current": {},
        "cycles": [{"current_recall": 0.62, "drift": {}, "weights_after": {}}],
    }))
    monkeypatch.setattr(t, "_HOME", home)

    step_result = t._step_verify(dry_run=True)

    assert step_result["benchmark"]["recall_at_5"] == 0.62
    assert t._fmt_verify(step_result) == "recall=0.62"


# ── D5: improve summary must report real movement, not a truthy ────────────

def test_fmt_improve_reports_zero_when_nothing_moved():
    """A stalled loop must be visible as drift=0 — never as drift=1."""
    rendered = t._fmt_improve({"drift_applied": {}}, dry=False)
    assert rendered == "drift=0 weights adjusted"
    assert rendered != "drift=1 weights adjusted"


def test_fmt_improve_counts_real_per_key_drift():
    rendered = t._fmt_improve(
        {"drift_applied": {"fts5": 0.000123}}, dry=False
    )
    assert rendered == "drift=1 weights adjusted"

    rendered = t._fmt_improve(
        {"drift_applied": {"fts5": 0.000123, "graph": -0.000045}}, dry=False
    )
    assert rendered == "drift=2 weights adjusted"


def test_fmt_improve_dry_run_lists_weights():
    rendered = t._fmt_improve(
        {"weights_after": {"fts5": 0.09, "graph": 0.73}}, dry=True
    )
    assert rendered == "weights: fts5=0.09, graph=0.73"


def test_step_improve_no_longer_returns_a_boolean_drift():
    """Source guard: the literal that produced the bogus count must be gone."""
    src = (t.__file__ and open(t.__file__).read()) or ""
    assert '"drift_applied": True' not in src, (
        "_step_improve regressed to returning a boolean; the summary would "
        "again report 'drift=1 weights adjusted' for no movement"
    )


# ── The retired 0-byte decoy must not come back ───────────────────────────

def test_ichor_decoy_path_is_retired():
    """`~/.hermes/ichor/ichor.db` was a 0-byte decoy that failed silently.

    The real DB is `~/.hermes/ichor.db`. If the decoy path ever exists again,
    scripts resolving it read nothing without erroring.
    """
    from pathlib import Path

    decoy = Path.home() / ".hermes" / "ichor" / "ichor.db"
    assert not decoy.exists(), (
        f"{decoy} exists again — it must stay retired; the real DB is "
        f"~/.hermes/ichor.db"
    )
