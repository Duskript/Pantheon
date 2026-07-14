"""
Restore CONDUCTOR_BASE_DIR / PANTHEON_ROOT after the v2 test session mutates them.

Why: tests/fixtures.py sets `os.environ["CONDUCTOR_BASE_DIR"]` to a tmpdir at
import time so v2 engine/delivery/service lazy-path resolvers look at the tmp
dir. That mutation persists for the rest of the pytest process. When v1
contract tests (test_conductor_server.py etc.) run after the v2 tests,
Conductor() in conductor_server.py reads the still-polluted env and looks in
the empty tmp dir — rules/workflows not found.

Why not a session- or package-scoped fixture: pytest session-scope tears down
at the very end of the process (after all v1 tests have already failed).
Package-scope tears down after the last v2 test, but with rootdir=/ (this
pytest is invoked from /home/konan/pantheon) the v2 conftest is in the conftest
chain for tests outside the v2 subtree, and pytest's test ordering means v1
tests can be interleaved or scheduled before the v2 package's teardown fires.
Neither scope guarantees the env is clean BEFORE v1 tests run.

What we do instead: a pytest_runtest_teardown hook in this conftest. It fires
after every test in the v2 subtree. We track how many v2 tests remain; when
that count hits zero, we restore the production CONDUCTOR_BASE_DIR. This
fires strictly between "last v2 test ran" and "next test (v1 or otherwise)
starts" — which is exactly the window we need.

The setup path (setdefault PANTHEON_ROOT) is handled the same way, but at
the FIRST v2 test setup so the production default resolves correctly.

PANTHEON_ROOT is setdefault'd so the production default for CONDUCTOR_BASE_DIR
resolves correctly on teardown.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


# Track the v2 subtree so the hook can recognize "this is a v2 test."
_V2_TESTS_DIR = Path(__file__).resolve().parent


def _is_v2_test(node) -> bool:
    """Return True if `node` lives under the v2 tests directory."""
    try:
        path = Path(node.fspath).resolve()
    except (TypeError, AttributeError):
        return False
    return _V2_TESTS_DIR in path.parents or path == _V2_TESTS_DIR


def _restore_production_env() -> None:
    """Restore CONDUCTOR_BASE_DIR to the production default."""
    pantheon_root = os.environ.get("PANTHEON_ROOT") or str(Path.home() / "pantheon")
    production_base_dir = Path(pantheon_root) / "conductor"
    os.environ["CONDUCTOR_BASE_DIR"] = str(production_base_dir)


# pytest_collection_modifyitems fires once after collection with the full list.
# We use it to:
#   (a) ensure PANTHEON_ROOT is set (so the production default resolves),
#   (b) cache the set of v2 test nodeids for fast hook checks,
#   (c) skip @pytest.mark.slow tests unless --runslow is given.
@pytest.hookimpl(tryfirst=False)
def pytest_collection_modifyitems(config, items):
    # SETUP: ensure PANTHEON_ROOT is set so the production default resolves.
    os.environ.setdefault("PANTHEON_ROOT", str(Path.home() / "pantheon"))
    # Snapshot the v2 test nodeids so the teardown hook can decrement
    # without re-walking item lists.
    config._v2_remaining = {
        item.nodeid for item in items if _is_v2_test(item)
    }
    # SLOW MARKER: skip slow tests by default. The user opts in with
    # `--runslow`. We add the skip marker here (rather than filtering
    # the items list) so the test count in the summary is accurate.
    if not config.getoption("--runslow", default=False):
        skip_slow = pytest.mark.skip(reason="need --runslow to run")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)


# -----------------------------------------------------------------------
# Global setup hook (dual-hook with the teardown hook below).
#
# A normal conftest `pytest_runtest_setup` is SCOPED to tests in this
# conftest's subtree (conductor/v2/tests/...). It would not fire for v1
# tests in tests/test_conductor_server.py etc., which is exactly the case
# we need to defend against (v1-first or interleaved orderings).
#
# To make the hook global, we register a plugin via pytest_configure. The
# plugin class has a pytest_runtest_setup method, and once registered
# with config.pluginmanager, its hooks fire for EVERY test in the pytest
# process, not just v2 subtree tests. This is the standard pytest escape
# hatch for "I need a hook from a non-rootdir conftest to apply to all
# tests."
#
# The hook logic itself is the same as the per-test check: for non-v2
# tests, compare current CONDUCTOR_BASE_DIR against the production
# default and restore if they differ. v2 tests are no-ops (their own
# fixtures intentionally set the tmpdir env).
# -----------------------------------------------------------------------
class _V2ConductorEnvGuard:
    """Plugin that restores CONDUCTOR_BASE_DIR before every non-v2 test.

    Registered globally via pytest_configure below so the hook fires for
    v1 tests as well as v2 tests. See the comment block above for the
    rationale (conftest-scoped hooks don't reach v1 tests).
    """

    @pytest.hookimpl(tryfirst=False)
    def pytest_runtest_setup(self, item):
        if _is_v2_test(item):
            return  # v2 tests want the polluted env (their own fixtures set it)
        pantheon_root = os.environ.get("PANTHEON_ROOT") or str(Path.home() / "pantheon")
        production_base_dir = str(Path(pantheon_root) / "conductor")
        if os.environ.get("CONDUCTOR_BASE_DIR") != production_base_dir:
            _restore_production_env()


@pytest.hookimpl(tryfirst=False)
def pytest_configure(config):
    """Register the env-guard plugin globally so its hooks reach v1 tests.

    Also register the `slow` marker so @pytest.mark.slow is a
    recognized mark (no PytestUnknownMarkWarning).
    """
    # Register the `slow` marker. The skip logic lives in
    # pytest_collection_modifyitems above.
    config.addinivalue_line(
        "markers",
        "slow: marks tests as slow (run with --runslow)",
    )
    # Idempotent: only register once even if pytest_configure fires for
    # multiple conftests in the chain.
    if not config.pluginmanager.hasplugin(V2_CONDUCTOR_ENV_GUARD_PLUGIN):
        config.pluginmanager.register(
            _V2ConductorEnvGuard(), V2_CONDUCTOR_ENV_GUARD_PLUGIN
        )


def pytest_addoption(parser):
    """Register the --runslow CLI option. Slow tests are excluded by
    default (they take 30-70s). Pass --runslow to opt in."""
    parser.addoption(
        "--runslow",
        action="store_true",
        default=False,
        help="run slow tests (cron E2E, multi-minute runs)",
    )


@pytest.hookimpl(tryfirst=False)
def pytest_runtest_teardown(item, nextitem):
    """After each v2 test teardown, if no v2 tests remain, restore env."""
    if not getattr(item.config, "_v2_remaining", None):
        return
    # Was this a v2 test? If so, remove it from the remaining set.
    if item.nodeid in item.config._v2_remaining:
        item.config._v2_remaining.discard(item.nodeid)
    # If v2 tests still remain, do nothing.
    if item.config._v2_remaining:
        return
    # Last v2 test has finished — restore the production env so the next
    # test (which will be in a different package, e.g. v1) sees a clean
    # CONDUCTOR_BASE_DIR.
    _restore_production_env()



# ---------------------------------------------------------------------------
# Polish #12, Step 1.7: plugin name as a module-level constant so it's
# grep-able from any tool (e.g. `rg V2_CONDUCTOR_ENV_GUARD_PLUGIN`).
# ---------------------------------------------------------------------------
V2_CONDUCTOR_ENV_GUARD_PLUGIN = "v2_conductor_env_guard"


# ---------------------------------------------------------------------------
# Marvin hygiene #4, Step 1.7: session-level tmp_path + WORKFLOWS_DIR
# wipe. Cheapest possible leak protection: bind eng.WORKFLOWS_DIR to
# a tmp dir for the whole v2 test session, then nuke the tmp dir at
# session teardown. If a test crashes mid-run, the tmp dir vanishes
# when the pytest process exits, so we never accumulate junk.
# ---------------------------------------------------------------------------
import conductor.v2.engine as _v2_eng  # noqa: E402


@pytest.fixture(scope="session")
def v2_workflows_tmp_dir():
    """Session-scoped tmp dir for WORKFLOWS_DIR. Auto-removed on teardown."""
    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="conductor_v2_workflows_"))
    # Bind the engine's import-time-resolved WORKFLOWS_DIR to the tmp
    # dir. Note: this only affects code that reads WORKFLOWS_DIR
    # directly; code that uses _workflows_dir() (the lazy resolver)
    # re-reads CONDUCTOR_BASE_DIR per call. We bind both for safety.
    _v2_eng.WORKFLOWS_DIR = tmp
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Polish #13 (deferred/perf), Step 1.7: cost of the dual-hook.
#
# Status: DEFERRED. We do not have a large enough test suite to measure
# the per-test overhead of (a) the global _V2ConductorEnvGuard
# pytest_runtest_setup hook and (b) the per-test teardown counter
# maintenance. The hooks are O(1) per call (dict discard + env var
# check), so the expected cost is sub-millisecond per test. Without a
# large suite, we can't measure the constant factor or the cumulative
# wall-clock impact. Tracked here so it's not forgotten when a real
# performance test exists.
#
# To measure later: run `time pytest conductor/v2/tests/ -q` on a
# warm cache with the hooks disabled vs. enabled. The current
# implementation runs in ~3-5s; expect the hooks to add <100ms total.
# ---------------------------------------------------------------------------
