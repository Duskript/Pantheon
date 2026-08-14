"""Contract tests for disposable canary profile handling.

The profile-bootstrap applier has two different audiences:

* production/default bootstrap runs, which should only touch the real Pantheon
  god fleet; and
* explicitly scoped disposable canary runs, which may target ``ichor-canary``
  while we validate the Ichor context-pack integration.

A regression here is risky in both directions. Rejecting ``--god ichor-canary``
breaks the live disposable canary path. Including ``ichor-canary`` in default
runs silently promotes test infrastructure into the production bootstrap fleet.
These tests pin the intended boundary: explicit canary allowed, default canary
excluded.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "conductor" / "scripts" / "profile-bootstrap-apply.py"


def load_module():
    """Load the hyphenated script filename as a Python module for direct tests."""
    spec = importlib.util.spec_from_file_location("profile_bootstrap_apply", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_skill(root: Path) -> None:
    """Create one canonical skill so dry-run output has deterministic rows."""
    skill = root / "devops" / "example-skill" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: example-skill\n---\n\n# Example\n", encoding="utf-8")


def write_no_canon(path: Path) -> None:
    """Create the required no-canon report with no filtered profile/skill tuples."""
    path.write_text("# empty no-canon report for test\n", encoding="utf-8")


def test_explicit_ichor_canary_profile_is_allowed_in_dry_run(tmp_path, capsys):
    module = load_module()
    canonical_root = tmp_path / "canonical"
    profiles_root = tmp_path / "profiles"
    no_canon = tmp_path / "no-canon.txt"
    write_skill(canonical_root)
    write_no_canon(no_canon)

    rc = module.main([
        "--god", "ichor-canary",
        "--canonical-root", str(canonical_root),
        "--profiles-root", str(profiles_root),
        "--no-canon-report", str(no_canon),
        "--json",
    ])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    payload = json.loads(captured.out)
    assert payload["results"]
    assert {row["god"] for row in payload["results"]} == {"ichor-canary"}


def test_default_profile_bootstrap_excludes_disposable_canary(tmp_path, capsys):
    module = load_module()
    canonical_root = tmp_path / "canonical"
    profiles_root = tmp_path / "profiles"
    no_canon = tmp_path / "no-canon.txt"
    write_skill(canonical_root)
    write_no_canon(no_canon)

    rc = module.main([
        "--canonical-root", str(canonical_root),
        "--profiles-root", str(profiles_root),
        "--no-canon-report", str(no_canon),
        "--json",
    ])

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    payload = json.loads(captured.out)
    gods = {row["god"] for row in payload["results"]}
    assert "ichor-canary" not in gods
    assert gods == set(module.TARGET_PROFILES)
