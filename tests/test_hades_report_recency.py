"""Regression: ``hades_get_report`` must not serve a stale report.

The bug this pins
-----------------
``hades_get_report()`` (``pantheon-core/mcp_server.py``) picked the most recent
report with a bare lexicographic filename sort:

    reports = sorted(_HADES_REPORTS.glob("hades-*.md"), reverse=True)
    report_path = reports[0]

The reports directory holds two families of filename:

    hades-YYYY-MM-DD.md                 <- the canonical daily series
    hades-cron-<date>-<slot>.md         <- cron-slot runs
    hades-<date>-compile.md / -rebuild.md

ASCII ``'c'`` (0x63) sorts above ``'2'`` (0x32), so
``hades-cron-2026-06-11-night.md`` outranked *every* daily report for all time.
The tool therefore answered "the most recent Hades report" with a June file
while Hades was healthy and writing daily — a false-alarm generator that fed
"I-no Hades run since June" into the 2026-09-24 Dawn Patrol archive report, and
had been recurring since at least 2026-09-13.

What is pinned
--------------
The fix constrains the glob to the canonical date-shaped series and orders by
the parsed date, so these properties must hold forever:

  * non-date stems never win the "most recent" lookup
  * an explicit ``report_date`` still resolves exactly as before
  * if ONLY non-date stems exist, the tool reports no reports rather than
    silently falling back to a lexicographic winner

The first test fails against the pre-fix implementation; see the module-level
comment in the committing message for the falsification run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PANTHEON_ROOT = Path(__file__).resolve().parent.parent
PANTHEON_CORE = PANTHEON_ROOT / "pantheon-core"
for _p in (str(PANTHEON_ROOT), str(PANTHEON_CORE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import mcp_server  # noqa: E402  (path setup must precede this import)


# The exact filename set that triggered the bug: three non-date stems, one of
# which ('cron-2026-06-11-night') wins a lexicographic sort over every daily
# report, plus a realistic tail of the daily series.
TRAP_FILENAMES = [
    "hades-cron-2026-06-11-night.md",
    "hades-2026-05-17-compile.md",
    "hades-2026-06-18-rebuild.md",
    "hades-2026-06-11.md",
    "hades-2026-09-22.md",
    "hades-2026-09-23.md",
]
NEWEST_DAILY = "hades-2026-09-23.md"
LEXICOGRAPHIC_WINNER = "hades-cron-2026-06-11-night.md"


@pytest.fixture
def reports_dir(tmp_path, monkeypatch):
    """Point the tool at a synthetic reports directory.

    ``_ATHENAEUM_ROOT`` is redirected as well because the tool reports
    ``report_path`` relative to it — leaving the real root in place makes
    ``relative_to`` raise for a tmp dir and masks the assertion under test.
    """
    def _build(names):
        for name in names:
            (tmp_path / name).write_text(f"# {name}\n")
        monkeypatch.setattr(mcp_server, "_HADES_REPORTS", tmp_path)
        monkeypatch.setattr(mcp_server, "_ATHENAEUM_ROOT", tmp_path)
        return tmp_path

    return _build


def _call(**kwargs) -> dict:
    return json.loads(mcp_server.hades_get_report(**kwargs))


# ── the core regression ─────────────────────────────────────────────────────

def test_most_recent_ignores_non_date_stems(reports_dir):
    """The trap filename must not win the 'most recent' lookup."""
    reports_dir(TRAP_FILENAMES)

    payload = _call()

    assert payload.get("error") is None, payload
    assert payload["report_path"] == NEWEST_DAILY
    assert payload["report_date"] == "2026-09-23"
    assert payload["report_path"] != LEXICOGRAPHIC_WINNER


def test_most_recent_is_the_max_date_not_the_max_string(reports_dir):
    """Chronological order, demonstrated on a set where stems disagree.

    A non-date stem that sorts above the newest daily report is the whole bug;
    this asserts the returned file is the greatest *date*, period.
    """
    reports_dir(TRAP_FILENAMES + ["hades-cron-2029-01-01-morning.md"])

    payload = _call()

    assert payload["report_path"] == NEWEST_DAILY, (
        "a future-dated non-canonical cron stem must not become 'most recent'"
    )


# ── explicit report_date must keep working ──────────────────────────────────

def test_explicit_date_still_resolves(reports_dir):
    reports_dir(TRAP_FILENAMES)

    payload = _call(report_date="2026-06-11")

    assert payload.get("error") is None, payload
    assert payload["report_path"] == "hades-2026-06-11.md"
    assert payload["report_date"] == "2026-06-11"


def test_explicit_date_missing_returns_error(reports_dir):
    reports_dir(TRAP_FILENAMES)

    payload = _call(report_date="1999-01-01")

    assert "error" in payload
    assert "1999-01-01" in payload["error"]


# ── degenerate directories ──────────────────────────────────────────────────

def test_only_non_date_stems_yields_no_reports(reports_dir):
    """No silent fallback to a lexicographic winner when nothing is canonical."""
    reports_dir(["hades-cron-2026-06-11-night.md", "hades-2026-05-17-compile.md"])

    payload = _call()

    assert payload.get("error") == "No Hades reports found", payload


def test_empty_directory_yields_no_reports(reports_dir):
    reports_dir([])

    payload = _call()

    assert payload.get("error") == "No Hades reports found", payload


def test_missing_directory_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "_HADES_REPORTS", tmp_path / "does-not-exist")

    payload = _call()

    assert "error" in payload


# ── the real deployment ─────────────────────────────────────────────────────

@pytest.mark.skipif(
    not mcp_server._HADES_REPORTS.is_dir(),
    reason="no live reports directory on this host",
)
def test_live_reports_directory_returns_a_canonical_daily_file():
    """Guard the real directory shape: whatever it holds, the answer is dated.

    This does not assert a specific date (the fleet is live and moves daily);
    it asserts the *shape* of the answer, which is what went wrong.
    """
    payload = _call()

    assert payload.get("error") is None, payload
    assert mcp_server._HADES_REPORT_DATE_RE.match(
        Path(payload["report_path"]).name
    ), f"non-canonical report served as most recent: {payload['report_path']}"
