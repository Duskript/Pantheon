"""
test_bootstrap_detect.py — pytest gate for profile-bootstrap-detect.py

GATE TEST (Phase 4 Step 4.4 hotfix, 2026-06-16).

Why this exists: the bash test (test_profile_bootstrap_detect.sh) covers
the 6-step brief verification, but it's a separate process invocation.
The previous Brief 1.5 fix was approved by Thoth QA (msg_20260616_022848)
as "correct", but the QA was run on a post-apply filesystem where every
per-profile path was already a symlink — so the broken
`is_symlink()` short-circuit masked a real bug in the inode check.
Codex review on PR #33 caught it; the bash test was actually failing
(Test 6) but the QA pass didn't run the bash test.

This pytest test exercises `detect_drift()` directly (no subprocess,
no bash) with real fixture files covering all four per-profile states:
  1. missing     → in output (needs symlink)
  2. symlink     → not in output, not in stderr
  3. regular file (drift) → not in output, IN stderr  ← the regression
  4. hardlink    → not in output, NOT in stderr (functionally equivalent to symlink)

The hardlink case is brand new — the bash test never covered it. It's
critical because the inode check exists to distinguish case 3 from case 4.
If the inode check is wrong (like the Brief 1.5 bug), case 3 is silently
suppressed AND case 4 would be incorrectly logged as drift. This test
catches both regressions.

Also: this test uses `tmp_path` (pytest builtin) and is fully isolated
from `~/.hermes/`. No real production files are touched.

Loading the module: the script file is named `profile-bootstrap-detect.py`
(hyphen, not a valid Python identifier) so we use importlib to load it
from a non-package directory. We do this once per test module via
`pytest_collection_modifyitems`-style caching — see `_load_detect()`.
"""
from __future__ import annotations

import importlib.util
import io
import os
from contextlib import redirect_stderr
from pathlib import Path
from types import ModuleType

import pytest


# Path to the script under test. We resolve at import time so a moved
# tree (e.g. worktree) doesn't break the test silently.
_DETECT_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "profile-bootstrap-detect.py"
)

# Module-level cache (cleared per-test for isolation).
_cached_detect_module: ModuleType | None = None


def _load_detect() -> ModuleType:
    """Load the profile-bootstrap-detect.py module by path.

    Hyphens in the filename make `import` impossible, so we use
    importlib. The module is loaded on demand and cached at module
    scope; the `detect_module` fixture clears the cache per-test.
    """
    global _cached_detect_module
    if _cached_detect_module is not None:
        return _cached_detect_module
    spec = importlib.util.spec_from_file_location(
        "profile_bootstrap_detect", str(_DETECT_SCRIPT)
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load spec for {_DETECT_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _cached_detect_module = module
    return module


@pytest.fixture
def detect_module():
    """The detect module, freshly loaded per-test for isolation."""
    global _cached_detect_module
    _cached_detect_module = None
    return _load_detect()


@pytest.fixture
def fixture_tree(tmp_path):
    """Build a minimal but real (cat, skill) tree:

        tmp_path/canon/<cat>/<skill>/SKILL.md
        tmp_path/profiles/<god>/skills/<cat>/<skill>/SKILL.md   (state varies per test)

    Returns a factory: call it with (state, content=None) to set the
    per-profile file's state for a specific (god, cat, skill).
    """
    cat = "dev"
    skill = "ci-test-skill"
    canon = tmp_path / "canon" / cat / skill / "SKILL.md"
    canon.parent.mkdir(parents=True)
    canon.write_text(f"canonical content for {skill}")

    # Only one god profile in scope — keeps test math simple and the
    # test doesn't care about multi-profile. The detect function
    # iterates all TARGET_PROFILES by default; we override with
    # profiles=("test-god",) in each test.
    god = "test-god"

    def set_state(state: str, content: str = None):
        """state in {"missing", "symlink", "regular_file", "hardlink"}.

        - missing:        per-profile path does not exist
        - symlink:        per-profile path is a symlink to canonical
        - regular_file:   per-profile path is a real file with the
                          given content (drift if content != canonical)
        - hardlink:       per-profile path is a hardlink to canonical
                          (shares canonical inode, NOT drift)
        """
        per = tmp_path / "profiles" / god / "skills" / cat / skill / "SKILL.md"
        per.parent.mkdir(parents=True, exist_ok=True)
        if per.is_symlink() or per.exists():
            per.unlink()
        if state == "missing":
            return  # path does not exist
        if state == "symlink":
            os.symlink(str(canon), str(per))
        elif state == "regular_file":
            per.write_text(content if content is not None else "drift content")
        elif state == "hardlink":
            # `link(2)` creates a hardlink — both paths share an inode.
            os.link(str(canon), str(per))
        else:
            raise ValueError(f"unknown state: {state!r}")

    return {
        "tmp_path": tmp_path,
        "cat": cat,
        "skill": skill,
        "god": god,
        "canon": canon,
        "set_state": set_state,
    }


def _capture_detect(detect_module, fixture, profiles=("test-god",)):
    """Run detect_drift with the fixture's canonical_root/profiles_root.

    Returns (findings, stderr_text). Captures stderr so we can assert
    on the drift log without polluting test output.
    """
    err = io.StringIO()
    with redirect_stderr(err):
        findings = detect_module.detect_drift(
            profiles=profiles,
            canonical_root=fixture["tmp_path"] / "canon",
            profiles_root=fixture["tmp_path"] / "profiles",
        )
    return findings, err.getvalue()


# =============================================================================
# 1. The 4 per-profile state cases
# =============================================================================


def test_missing_path_is_in_output(detect_module, fixture_tree):
    """Per-profile path does not exist → in output, no stderr drift log."""
    fixture_tree["set_state"]("missing")
    findings, err = _capture_detect(detect_module, fixture_tree)
    assert findings == [
        {"god": "test-god", "category": "dev", "skill_name": "ci-test-skill"}
    ]
    assert "regular file" not in err, f"unexpected drift log: {err!r}"


def test_symlink_is_silent(detect_module, fixture_tree):
    """Per-profile path is a symlink → not in output, not in stderr."""
    fixture_tree["set_state"]("symlink")
    findings, err = _capture_detect(detect_module, fixture_tree)
    assert findings == []
    assert "regular file" not in err, f"unexpected drift log: {err!r}"


def test_regular_file_with_different_content_logs_drift(
    detect_module, fixture_tree
):
    """Per-profile path is a regular file with content != canonical →
    NOT in output, but IS in stderr with the [drift] marker.

    This is THE regression test for the P2 #2 hotfix. The previous
    Brief 1.5 inode check (per_profile.stat().st_ino ==
    per_profile.resolve().st_ino) was tautologically True for any
    regular file, so this case was silently suppressed. Codex caught
    it; if this test fails, the detector is broken again.
    """
    fixture_tree["set_state"]("regular_file", content="DRIFT — different content")
    findings, err = _capture_detect(detect_module, fixture_tree)
    # Path IS present (so not in output as "missing"), but IS drift
    assert findings == [], f"regular-file drift should NOT be in output: {findings}"
    # Stderr must contain the drift log for this specific (god, cat, skill)
    assert "test-god" in err, f"drift log missing god name: {err!r}"
    assert "dev" in err, f"drift log missing category: {err!r}"
    assert "ci-test-skill" in err, f"drift log missing skill: {err!r}"
    assert "regular file" in err, f"drift log missing reason: {err!r}"


def test_hardlink_to_canonical_is_silent(detect_module, fixture_tree):
    """Per-profile path is a HARDLINK to canonical (shares inode) →
    not in output, NOT in stderr. Functionally equivalent to a symlink.

    The hardlink case is what the inode check exists to defend. If
    this test ever fails, the detector is logging real hardlinks as
    drift, which is wrong (a hardlink is a perfect mirror of the
    canonical file — no human action needed).
    """
    fixture_tree["set_state"]("hardlink")
    findings, err = _capture_detect(detect_module, fixture_tree)
    assert findings == []
    assert "regular file" not in err, (
        f"hardlink should NOT be logged as drift: {err!r}"
    )


# =============================================================================
# 2. Regression tests — the specific bugs Codex flagged
# =============================================================================


def test_p2_hotfix_drift_not_suppressed_by_broken_inode_check(
    detect_module, fixture_tree
):
    """REGRESSION: the previous Brief 1.5 inode check
    (per_profile.stat().st_ino == per_profile.resolve().stat().st_ino)
    was True for any regular file, suppressing drift. This test
    fails on the broken check and passes on the fixed check.
    """
    fixture_tree["set_state"]("regular_file", content="drift")
    findings, err = _capture_detect(detect_module, fixture_tree)
    # The drift must be visible
    assert "regular file" in err, (
        "P2 #2 REGRESSION: drift is being suppressed. The broken "
        "Brief 1.5 inode check (per vs per.resolve() inodes) is "
        "back, or the fix was applied wrong."
    )


def test_regular_file_with_same_content_as_canonical_is_still_drift(
    detect_module, fixture_tree
):
    """A regular file with content identical to canonical IS STILL DRIFT.

    The inode check looks at *file identity* (shared inode = hardlink),
    not *content equality*. A regular file with the same content but a
    different inode is a divergent copy that will go stale — it is
    drift, and the operator (or Brief 2) needs to know.

    This guards against a "smart" future refactor that swaps the inode
    check for a content hash, which would silently miss this case.
    """
    canonical_content = fixture_tree["canon"].read_text()
    fixture_tree["set_state"]("regular_file", content=canonical_content)
    findings, err = _capture_detect(detect_module, fixture_tree)
    assert "regular file" in err, (
        "regular file with same content but different inode IS drift "
        "— inode check is not a content check"
    )


# =============================================================================
# 3. The 4 states combined (one god per state, simultaneously)
# =============================================================================


def test_all_four_states_combined(detect_module, tmp_path):
    """Run all 4 states in a single detect_drift call to make sure they
    don't interfere. Output: one finding per 'missing' state, stderr:
    one drift line per 'regular_file' state, nothing for symlink or
    hardlink. This is the integration test the bash fixture also
    exercises — but at the Python level so it shows up in pytest.

    Setup: ONE canonical skill, FOUR god profiles, each profile
    represents a different state for that same skill. The detector
    iterates (cat, skill) × profile, so each profile is checked
    against the same single canonical entry.
    """
    cat = "dev"
    skill = "ci-test"
    canon = tmp_path / "canon" / cat / skill / "SKILL.md"
    canon.parent.mkdir(parents=True)
    canon.write_text("canonical")

    states = {
        "god-missing": "missing",
        "god-symlink": "symlink",
        "god-drift": "regular_file",
        "god-hardlink": "hardlink",
    }
    profiles = tuple(states.keys())

    for god, state in states.items():
        per = tmp_path / "profiles" / god / "skills" / cat / skill / "SKILL.md"
        per.parent.mkdir(parents=True, exist_ok=True)
        if per.exists() or per.is_symlink():
            per.unlink()
        if state == "symlink":
            os.symlink(str(canon), str(per))
        elif state == "regular_file":
            per.write_text("drift content")
        elif state == "hardlink":
            os.link(str(canon), str(per))
        # missing: do nothing

    err = io.StringIO()
    with redirect_stderr(err):
        findings = detect_module.detect_drift(
            profiles=profiles,
            canonical_root=tmp_path / "canon",
            profiles_root=tmp_path / "profiles",
        )
    stderr_text = err.getvalue()

    # Only the "missing" god should appear in output (one entry total)
    assert {f["god"] for f in findings} == {"god-missing"}, (
        f"unexpected findings: {findings}"
    )
    # Only the "drift" god should appear in stderr as drift
    assert "god-drift" in stderr_text, f"drift log missing: {stderr_text!r}"
    assert "god-symlink" not in stderr_text, (
        f"symlink was logged as drift: {stderr_text!r}"
    )
    assert "god-hardlink" not in stderr_text, (
        f"hardlink was logged as drift: {stderr_text!r}"
    )
    assert "god-missing" not in stderr_text, (
        f"missing path was logged as drift: {stderr_text!r}"
    )
