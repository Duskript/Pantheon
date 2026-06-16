"""
Step 1.7 polish #11 — explicit pollution-scenario cases for v2 tests.

Why: the dual-hook in conftest.py (the global _V2ConductorEnvGuard plugin
PLUS the per-test teardown counter) is non-trivial machinery. It's load-
bearing for the v1+v2 combined pytest, but its correctness depends on a
specific invariant: after the LAST v2 test in the process finishes,
CONDUCTOR_BASE_DIR is restored to the production default.

This file exercises that invariant with four explicit orderings:

  1. test_v2_then_v1:  simulate v2-first ordering — set the tmp dir, run a
     no-op "v2 test", then assert the env-guard restores the production
     default before any v1 code reads it.
  2. test_v1_then_v2:  simulate v1-first ordering — verify the env-guard
     fires before the v2 test setup overrides the env.
  3. test_interleaved:  simulate interleaved v1/v2 tests by alternating
     assertions on the env-guard's behavior.
  4. test_env_var_cleanup: directly inspect os.environ to confirm
     CONDUCTOR_BASE_DIR is exactly the production default after the
     full pytest session (or after the last v2 test in this file).

The tests use the `_V2ConductorEnvGuard` class directly via the conftest
plugin manager — no need to launch a real pytest subprocess. That keeps
the test fast (<1s) and deterministic.

The session-scoped `v2_workflows_tmp_dir` fixture (Marvin hygiene #4)
is auto-picked-up here so the import-time WORKFLOWS_DIR binding gets
overridden for the whole test_isolation session.
"""
from __future__ import annotations

import importlib.util
import os
import tempfile
from pathlib import Path
from typing import Any

import pytest


# Mirror the production default computation in conftest._restore_production_env.
def _production_base_dir() -> str:
    pantheon_root = os.environ.get("PANTHEON_ROOT") or str(Path.home() / "pantheon")
    return str(Path(pantheon_root) / "conductor")


def _load_conftest() -> Any:
    """Import the v2 conftest module by file path. Returns the module."""
    conftest_path = Path(__file__).resolve().parent / "conftest.py"
    spec = importlib.util.spec_from_file_location("v2_conftest_isolation", conftest_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_env_guard() -> Any:
    """Instantiate the conftest's _V2ConductorEnvGuard for direct testing."""
    return _load_conftest()._V2ConductorEnvGuard()


def _v2_fake_path(name: str) -> Path:
    """Build a fspath under the v2 tests dir so _is_v2_test returns True.

    The conftest's _is_v2_test checks `Path(node.fspath).resolve()` against
    the v2 tests directory tree. The fspath doesn't have to actually exist
    on disk — resolve() handles non-existent paths. We just need the
    resolved path to fall under the v2 tests dir.
    """
    return Path(__file__).resolve().parent / name


class _FakeItem:
    """Minimal stand-in for a pytest Item — just enough for the env-guard hook.

    The hook reads `item.nodeid` and `item.fspath`. The teardown hook also
    reads `item.config._v2_remaining`, so we expose `config` as a settable
    attribute on a small `_FakeConfig` class.
    """
    def __init__(self, nodeid: str, fspath: Path, config: Any = None) -> None:
        self.nodeid = nodeid
        self.fspath = fspath
        self.config = config if config is not None else _FakeConfig()


class _FakeConfig:
    """Minimal stand-in — pytest's Config has many attributes; we only need _v2_remaining."""
    def __init__(self) -> None:
        self._v2_remaining: set = set()


@pytest.fixture
def fresh_env(monkeypatch):
    """Start each test with a clean CONDUCTOR_BASE_DIR set to a tmp dir."""
    tmp = Path(tempfile.mkdtemp(prefix="isolation_test_"))
    monkeypatch.setenv("CONDUCTOR_BASE_DIR", str(tmp))
    yield tmp
    # monkeypatch will restore the previous value on teardown


# ---------------------------------------------------------------------------
# Case 1: v2-then-v1
# ---------------------------------------------------------------------------
def test_v2_then_v1_env_restored(fresh_env):
    """After a v2 test runs (pollutes env to tmpdir), the next v1 test
    must see the production default. The env-guard fires on v1's setup
    and restores the production base dir."""
    guard = _build_env_guard()

    # Sanity: fresh_env sets the env to a tmp dir; guard restores to prod.
    v1_item = _FakeItem("tests/test_conductor_server.py::test_x", Path("/tmp/fake/v1.py"))
    guard.pytest_runtest_setup(v1_item)

    assert os.environ["CONDUCTOR_BASE_DIR"] == _production_base_dir(), (
        "v2-then-v1 ordering: env-guard did not restore production default"
    )


# ---------------------------------------------------------------------------
# Case 2: v1-then-v2
# ---------------------------------------------------------------------------
def test_v1_then_v2_env_unchanged():
    """When a v1 test runs first, the env-guard is a no-op (env was never
    polluted). Then a v2 test pollutes the env. Subsequent v1 tests must
    see the restored default."""
    guard = _build_env_guard()

    # v1 test fires first, env is at production default — guard is a no-op.
    v1_item = _FakeItem("tests/test_conductor_server.py::test_a", Path("/tmp/fake/v1.py"))
    guard.pytest_runtest_setup(v1_item)
    assert os.environ["CONDUCTOR_BASE_DIR"] == _production_base_dir()

    # Now a v2 test pollutes the env. The guard skips v2 tests
    # (their fixtures set the env intentionally).
    v2_tmp = Path(tempfile.mkdtemp(prefix="v2_pollute_"))
    os.environ["CONDUCTOR_BASE_DIR"] = str(v2_tmp)
    v2_item = _FakeItem(
        "conductor/v2/tests/test_engine.py::test_y",
        _v2_fake_path("test_engine.py"),
    )
    guard.pytest_runtest_setup(v2_item)
    # v2 test should still see the polluted env (its fixture set it).
    assert os.environ["CONDUCTOR_BASE_DIR"] == str(v2_tmp)

    # Next v1 test fires — guard restores production.
    v1_item2 = _FakeItem("tests/test_conductor_server.py::test_b", Path("/tmp/fake/v1.py"))
    guard.pytest_runtest_setup(v1_item2)
    assert os.environ["CONDUCTOR_BASE_DIR"] == _production_base_dir()


# ---------------------------------------------------------------------------
# Case 3: interleaved
# ---------------------------------------------------------------------------
def test_interleaved_ordering():
    """v1, v2, v1, v2, v1 — every v1 test sees the production default;
    every v2 test sees its own polluted env."""
    guard = _build_env_guard()

    # v1 first
    v1 = _FakeItem("tests/test_conductor_server.py::test_i1", Path("/tmp/v1.py"))
    guard.pytest_runtest_setup(v1)
    assert os.environ["CONDUCTOR_BASE_DIR"] == _production_base_dir()

    # v2 pollutes
    v2_tmp1 = Path(tempfile.mkdtemp(prefix="v2_int_1_"))
    os.environ["CONDUCTOR_BASE_DIR"] = str(v2_tmp1)
    v2 = _FakeItem("conductor/v2/tests/test_engine.py::test_i2", _v2_fake_path("test_engine.py"))
    guard.pytest_runtest_setup(v2)
    assert os.environ["CONDUCTOR_BASE_DIR"] == str(v2_tmp1)

    # v1 again — guard restores
    v1 = _FakeItem("tests/test_conductor_server.py::test_i3", Path("/tmp/v1.py"))
    guard.pytest_runtest_setup(v1)
    assert os.environ["CONDUCTOR_BASE_DIR"] == _production_base_dir()

    # v2 pollutes again (different tmp)
    v2_tmp2 = Path(tempfile.mkdtemp(prefix="v2_int_2_"))
    os.environ["CONDUCTOR_BASE_DIR"] = str(v2_tmp2)
    v2 = _FakeItem("conductor/v2/tests/test_engine.py::test_i4", _v2_fake_path("test_engine.py"))
    guard.pytest_runtest_setup(v2)
    assert os.environ["CONDUCTOR_BASE_DIR"] == str(v2_tmp2)

    # Final v1 sees restored
    v1 = _FakeItem("tests/test_conductor_server.py::test_i5", Path("/tmp/v1.py"))
    guard.pytest_runtest_setup(v1)
    assert os.environ["CONDUCTOR_BASE_DIR"] == _production_base_dir()


# ---------------------------------------------------------------------------
# Case 4: env-var cleanup after v2 teardown
# ---------------------------------------------------------------------------
def test_env_var_cleanup_after_v2_teardown(fresh_env):
    """Direct assertion: the conftest's pytest_runtest_teardown hook
    restores CONDUCTOR_BASE_DIR to the production default after the
    last v2 test in its tracked set finishes.

    The hook only fires the restore when BOTH:
      (a) item.config._v2_remaining is truthy (the collection hook set it)
      (b) the current item is a v2 test (its nodeid is in _v2_remaining)
      (c) after discard, _v2_remaining is empty (this is the LAST v2 test)
    """
    conftest = _load_conftest()

    # Pollute the env to simulate v2 fixture setup.
    v2_tmp = Path(tempfile.mkdtemp(prefix="v2_cleanup_"))
    os.environ["CONDUCTOR_BASE_DIR"] = str(v2_tmp)
    assert os.environ["CONDUCTOR_BASE_DIR"] == str(v2_tmp)

    # Build a config that knows about exactly one v2 test.
    config = _FakeConfig()
    only_v2 = "conductor/v2/tests/test_x.py::test_y"
    config._v2_remaining = {only_v2}
    v2_item = _FakeItem(only_v2, _v2_fake_path("test_engine.py"), config=config)

    # Drive the teardown hook once: this is the LAST v2 test, so the
    # discard empties the set and the restore fires.
    conftest.pytest_runtest_teardown(v2_item, None)

    assert os.environ["CONDUCTOR_BASE_DIR"] == _production_base_dir(), (
        "After last v2 test teardown, env-var cleanup did not restore "
        "CONDUCTOR_BASE_DIR to the production default"
    )


def test_env_var_cleanup_no_restore_when_v2_remain(fresh_env):
    """Negative case: if v2 tests still remain after this teardown,
    the env is NOT restored. The dispatch may still want the polluted
    env for subsequent v2 tests."""
    conftest = _load_conftest()

    v2_tmp = Path(tempfile.mkdtemp(prefix="v2_still_remain_"))
    os.environ["CONDUCTOR_BASE_DIR"] = str(v2_tmp)

    config = _FakeConfig()
    config._v2_remaining = {
        "conductor/v2/tests/test_x.py::test_y",
        "conductor/v2/tests/test_x.py::test_z",  # second v2 test still pending
    }
    v2_item = _FakeItem(
        "conductor/v2/tests/test_x.py::test_y",
        _v2_fake_path("test_engine.py"),
        config=config,
    )
    conftest.pytest_runtest_teardown(v2_item, None)

    # Env should still be polluted — restore only fires after the LAST v2 test.
    assert os.environ["CONDUCTOR_BASE_DIR"] == str(v2_tmp), (
        "Env was restored while v2 tests still remained; should stay polluted"
    )
