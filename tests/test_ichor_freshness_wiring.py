"""The freshness guard must be WIRED, not merely built.

`lib/ichor/freshness.py` was written, tested, and then **imported by nothing**, so
it caught nothing. A guard that is not wired is a guard that does not exist — and
it is worse than no guard, because its presence is cited as coverage.

The concrete failure this pins down: `scripts/pantheon-improvement-report.py`
rendered the Dojo's `current_success_rate` and its 7/30-day deltas from a file that
had not been written in **65 days**. It did not error and it did not warn — it
printed a plausible number from a dead source, which is indistinguishable from a
live reading.

FALSIFICATION (verified, 2026-09-23)
------------------------------------
Write the same metrics content twice and vary ONLY the mtime:

    A. mtime 65 days ago  ->  available=False, current_success_rate=None,
                              stale=True, age_days=65.0
    B. mtime 1 hour ago   ->  available=True,  current_success_rate=88.0,
                              stale=False

With the gate removed from `get_dojo_metrics()`, case A returns
`available=True, current_success_rate=88.0` — the number reappears. That is the
falsification: the test fails for the right reason without the wiring.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts/pantheon-improvement-report.py"


def _load_report():
    """Import the report script as a module (it is not on the package path)."""
    spec = importlib.util.spec_from_file_location("_improvement_report_probe", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def metrics_file(tmp_path):
    def _make(mtime_days_ago: float) -> Path:
        p = tmp_path / "metrics.json"
        p.write_text(json.dumps([
            {"timestamp": time.time() - 86400 * 40, "overall_success_rate": 71.0, "weakest_tools": []},
            {"timestamp": time.time() - 86400 * 39, "overall_success_rate": 88.0, "weakest_tools": []},
        ]))
        when = time.time() - mtime_days_ago * 86400
        os.utime(p, (when, when))
        return p
    return _make


def test_a_stale_source_reports_no_numbers(metrics_file):
    """The regression: a 65-day-old file must not yield a current-looking rate."""
    mod = _load_report()
    mod.DOJO_DATA = metrics_file(65)
    r = mod.get_dojo_metrics()

    assert r["stale"] is True
    assert r["age_days"] == pytest.approx(65.0, abs=0.2)
    assert r["current_success_rate"] is None, "a stale source must not report a rate"
    assert r["delta_7d"] is None
    assert r["delta_30d"] is None
    assert "stale_reason" in r and "dojo_metrics" in r["stale_reason"]


def test_a_fresh_source_reports_normally(metrics_file):
    """The guard must not block healthy data — otherwise it gets removed."""
    mod = _load_report()
    mod.DOJO_DATA = metrics_file(1 / 24)
    r = mod.get_dojo_metrics()

    assert r["stale"] is False
    assert r["available"] is True
    assert r["current_success_rate"] == 88.0


def test_the_two_cases_differ_only_by_mtime(metrics_file):
    """Proves the gate is what changed the outcome, not the file contents."""
    mod = _load_report()
    mod.DOJO_DATA = metrics_file(65)
    stale = mod.get_dojo_metrics()
    mod.DOJO_DATA = metrics_file(1 / 24)
    fresh = mod.get_dojo_metrics()

    assert stale["current_success_rate"] is None
    assert fresh["current_success_rate"] == 88.0


def test_an_absent_source_is_stale_not_fresh(metrics_file, tmp_path):
    """Class 3: absent must not read as 'fine'. Reporting nothing is the outcome."""
    mod = _load_report()
    mod.DOJO_DATA = tmp_path / "does-not-exist.json"
    r = mod.get_dojo_metrics()
    assert r["stale"] is True
    assert "absent" in r["stale_reason"]


def test_the_guard_is_actually_imported_by_the_report():
    """A guard that nothing imports is the bug this file exists to prevent."""
    src = SCRIPT.read_text()
    # `lib.ichor.freshness`, not `ichor.freshness`: `lib/ichor/__init__.py` needs the
    # REPO ROOT on sys.path (it does `from lib.ichor.migrations... import ...`), so
    # importing as `ichor.freshness` with `lib/` on the path raises
    # ModuleNotFoundError on `lib.ichor.migrations` — which silently disabled the guard.
    assert "from lib.ichor.freshness import" in src, "the freshness guard is not imported"
    assert "from ichor.freshness import" not in src, (
        "importing as `ichor.freshness` breaks when run as a script"
    )
    assert "_freshness_gate(" in src
    assert src.count("_freshness_gate(") >= 3, "the gate must be defined AND called"


def test_the_guard_never_raises_into_a_report():
    """A report that raises produces nothing, and 'nothing' looks like 'no problem'."""
    src = SCRIPT.read_text()
    assert "def _freshness_gate" in src
    i = src.index("def _freshness_gate")
    body = src[i:i + 2000]
    assert "raise" not in body.split("\n\n")[0], "_freshness_gate must not raise"


# ── The test that would have caught the bug ─────────────────────────────
# The tests above load the script as a MODULE, where sys.path happened to resolve
# the guard. Run as a SCRIPT — which is how cron and every human invoke it — the
# import failed, my `except` swallowed it, the guard fell back to OFF, and the
# report printed `Success rate: 90.0%` from an unguarded source. Every test above
# passed while production was unguarded.
#
# So: exercise the real entry point, in a subprocess, exactly as it is run.

def _run_report(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=str(REPO), timeout=180,
    )


def test_the_guard_actually_loads_when_run_as_a_script():
    """The regression. `lib/ichor/__init__.py` needs the REPO ROOT on sys.path."""
    r = _run_report("--json")
    combined = r.stdout + r.stderr
    assert "guard UNAVAILABLE" not in combined, (
        "the freshness guard failed to import when run as a script — "
        "the report is running unguarded"
    )
    assert "No module named 'lib.ichor" not in combined
    assert r.returncode == 0, combined[-500:]


def test_run_as_a_script_it_reports_freshness_state():
    """The JSON must carry `stale`/`age_days` per section — proof the gate ran."""
    r = _run_report("--json")
    assert r.returncode == 0, r.stderr[-400:]
    payload = json.loads(r.stdout)
    for section in ("dojo", "forge"):
        assert "stale" in payload[section], f"{section} did not pass through the gate"
        assert "age_days" in payload[section]


def test_strict_exits_non_zero_on_a_stale_source(tmp_path):
    """`--strict` is the cron contract: never exit 0 while reporting from a dead source."""
    r = _run_report("--json", "--strict")
    payload = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}
    stale = [n for n, s in payload.items() if isinstance(s, dict) and s.get("stale")]
    if stale:
        assert r.returncode == 2, f"stale sources {stale} but exit code was {r.returncode}"
    else:
        assert r.returncode == 0

