"""Dry-run/apply contract tests for Hindsight maintenance scripts."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.ichor_db import IchorDB  # noqa: E402


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{REPO_ROOT}:{env.get('PYTHONPATH', '')}"
    return env


def _run(script: str, *args: str) -> str:
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / script), *args],
        cwd=str(REPO_ROOT), env=_env(), text=True, capture_output=True, check=True,
    )
    return proc.stdout


def test_backfill_scripts_dry_run_and_apply_are_safe(tmp_path) -> None:
    db_path = str(tmp_path / "ichor.db")
    db = IchorDB(db_path=db_path)
    db.connect()
    db.insert_event(
        session_id="s1", event_type="preference", subject="Konan",
        object="event driven over polling", raw_text="Konan prefers event driven over polling.",
        god_name="hermes", confidence=0.9,
    )
    db.insert_event(
        session_id="s2", event_type="preference", subject="Konan",
        object="event driven over polling", raw_text="Konan prefers event driven over polling.",
        god_name="thoth", confidence=0.8,
    )
    db.close()

    out = _run("ichor_backfill_tags.py", "--db-path", db_path, "--dry-run", "--pantheon-scope")
    assert "DRY-RUN" in out and "inserted=0" in out
    with sqlite3.connect(db_path) as conn:
        before = conn.execute("SELECT COUNT(*) FROM ichor_event_tags WHERE tag = 'scope:pantheon'").fetchone()[0]
    assert before == 0

    out = _run("ichor_backfill_tags.py", "--db-path", db_path, "--apply", "--pantheon-scope")
    assert "inserted=" in out
    out_again = _run("ichor_backfill_tags.py", "--db-path", db_path, "--apply", "--pantheon-scope")
    assert "inserted=0" in out_again

    out = _run("ichor_temporal_backfill.py", "--db-path", db_path, "--dry-run")
    assert "DRY-RUN" in out
    out = _run("ichor_temporal_backfill.py", "--db-path", db_path, "--apply")
    assert "updated=" in out
    out_again = _run("ichor_temporal_backfill.py", "--db-path", db_path, "--apply")
    assert "updated=0" in out_again

    out = _run("ichor_consolidate_observations.py", "--db-path", db_path, "--dry-run", "--limit", "100")
    assert "DRY-RUN" in out and "written=False" in out
    with sqlite3.connect(db_path) as conn:
        obs_count = conn.execute("SELECT COUNT(*) FROM ichor_observations").fetchone()[0]
    assert obs_count == 0
