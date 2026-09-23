"""Freshness assertions — the class-4 guard.

Four failure classes are catalogued in this codebase and the fourth is the worst:
**stale-but-plausible** — a number that is not obviously wrong, where only the
timestamp gives it away. Two confirmed instances: the Dojo reported
`overall_success_rate: 90.0` for 65 days after its writer stopped, and the Ichor
Forge improvement report was 103 days stale when it surfaced.

These tests pin the guard: a metric declares a maximum age and FAILS HARD past it.
A warning is not enough — a warning is a log line nobody reads, which is how a
metric stays stale for 65 days.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.ichor.freshness import (  # noqa: E402
    MAX_AGES, MetricStamp, StaleMetric, check_all, stamp_for_file,
)


def test_a_fresh_metric_passes():
    s = MetricStamp(name="x", written_at=time.time() - 60, max_age_s=3600)
    assert s.is_fresh
    assert s.assert_fresh() is s


def test_a_stale_metric_raises_rather_than_reporting():
    """The whole point: refuse to report, do not warn."""
    s = MetricStamp(name="dojo_metrics", written_at=time.time() - 100 * 3600,
                    max_age_s=48 * 3600, source="/x/metrics.json")
    assert not s.is_fresh
    with pytest.raises(StaleMetric) as e:
        s.assert_fresh()
    assert "dojo_metrics" in str(e.value)
    assert "Refusing to report a stale value as current" in str(e.value)


def test_a_missing_file_is_maximally_stale_not_fresh(tmp_path):
    """A missing artifact is class 3, not class 4 — but it must not read as fresh."""
    s = stamp_for_file(tmp_path / "nope.json", "dojo_metrics")
    assert s.written_at == 0.0
    assert not s.is_fresh
    with pytest.raises(StaleMetric):
        s.assert_fresh()


def test_the_real_dojo_file_would_be_caught(tmp_path):
    """Reproduce the actual 65-day case: three writes, then silence."""
    p = tmp_path / "metrics.json"
    p.write_text("[]")
    old = time.time() - 65 * 86400
    import os
    os.utime(p, (old, old))
    s = stamp_for_file(p, "dojo_metrics")
    assert 64 < s.age_s / 86400 < 66
    with pytest.raises(StaleMetric):
        s.assert_fresh()


def test_max_age_comes_from_the_central_table_not_the_caller(tmp_path):
    """A metric must not be able to pick its own lenient bound."""
    p = tmp_path / "x.json"
    p.write_text("{}")
    s = stamp_for_file(p, "l2_extraction_yield")
    assert s.max_age_s == MAX_AGES["l2_extraction_yield"]
    # an unknown family still gets a bound rather than none
    assert stamp_for_file(p, "unknown_metric").max_age_s == 24 * 3600


def test_check_all_fail_fast_stops_at_the_first():
    good = MetricStamp("good", time.time(), 3600)
    bad = MetricStamp("bad", time.time() - 10 * 3600, 3600)
    with pytest.raises(StaleMetric) as e:
        check_all([good, bad])
    assert "bad" in str(e.value)


def test_check_all_collects_every_stale_metric_when_asked():
    """A report must be able to state everything wrong at once."""
    a = MetricStamp("a", time.time() - 10 * 3600, 3600)
    b = MetricStamp("b", time.time() - 20 * 3600, 3600)
    with pytest.raises(StaleMetric) as e:
        check_all([a, b], fail_fast=False)
    assert "2 stale metric(s)" in str(e.value)
    assert "a " in str(e.value) and "b " in str(e.value)


def test_human_age_is_readable():
    assert MetricStamp("x", time.time() - 90, 999).human_age().endswith("m")
    assert MetricStamp("x", time.time() - 7200, 99999).human_age().endswith("h")
    assert MetricStamp("x", time.time() - 3 * 86400, 999999).human_age().endswith("d")


def test_as_dict_reports_the_timestamp_that_gives_a_stale_metric_away():
    """Only the timestamp distinguishes a stale number from a live one, so it
    must be in the reported payload — not omitted because the number looked fine."""
    s = MetricStamp("dojo_metrics", time.time() - 5 * 3600, 3600, source="/x/metrics.json")
    d = s.as_dict()
    assert d["fresh"] is False
    assert d["age"].endswith("h")
    assert d["source"] == "/x/metrics.json"
