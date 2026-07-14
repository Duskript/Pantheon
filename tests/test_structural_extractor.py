"""Tests for the deterministic structural extractor."""
from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import sqlite_vec

from lib.ichor import schema_v2
from lib.ichor.contracts import ClaimStore
from lib.extractors.structural_extractor import (
    _discover_session_files,
    extract_from_bundle,
    extract_from_source_file,
    extract_structural_candidates,
    persist_candidates,
    run,
)


def _store(tmp_path: Path) -> ClaimStore:
    db_path = tmp_path / "ichor.db"
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.executescript(schema_v2.SCHEMA_SQL)
    conn.close()
    return ClaimStore(db_path)


def test_extract_structural_candidates_finds_paths_ports_env_flags_and_dependencies() -> None:
    text = """
    relay-7:/srv/olympus-btst/olympus-btst-app --port 3137
    export OLYMPUS_ADMIN_SECRET=redacted
    --resume --port 8080
    uses fastembed v0.8.0
    depends on sqlite-vec v0.1.6
    """

    candidates = extract_structural_candidates(text, "session-1")
    kinds = {candidate.kind for candidate in candidates}
    assert {"path", "port", "env", "flag", "dependency"} <= kinds
    assert any("/srv/olympus-btst/olympus-btst-app" in candidate.text for candidate in candidates)
    assert any("Port referenced: 8080" == candidate.text for candidate in candidates)


def test_extract_and_persist_session_bundle(tmp_path: Path) -> None:
    store = _store(tmp_path)
    session_file = tmp_path / "session.json"
    session_file.write_text(
        json.dumps(
            {
                "session_id": "sess-123",
                "messages": [
                    {"role": "user", "content": "Use /opt/pantheon/app and --port 3137."},
                    {"role": "assistant", "content": "Set OLYMPUS_ADMIN_SECRET=redacted and depends on sqlite-vec v0.1.6."},
                ],
            }
        ),
        encoding="utf-8",
    )

    bundle = extract_from_source_file(session_file)
    assert bundle.source_id == "sess-123"
    candidates = extract_from_bundle(bundle)
    result = persist_candidates(store, candidates, dry_run=False)

    assert result["created"] >= 4
    assert result["by_kind"]["path"] >= 1
    assert result["by_kind"]["port"] >= 1
    assert result["by_kind"]["env"] >= 1
    assert result["by_kind"]["dependency"] >= 1

    # Idempotent per source session + claim text.
    second = persist_candidates(store, candidates, dry_run=False)
    assert second["created"] == 0
    assert second["skipped"] >= result["created"]


def test_run_scans_sessions_and_git_repos(tmp_path: Path) -> None:
    store = _store(tmp_path)
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    (session_dir / "20260711_000001_abc.json").write_text(
        json.dumps(
            {
                "session_id": "session-a",
                "messages": [
                    {"role": "user", "content": "Project uses /srv/app and --port 9000"},
                ],
            }
        ),
        encoding="utf-8",
    )

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "README.md").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "bump fastembed to 0.8.0"], cwd=repo, check=True, capture_output=True, text=True)

    state_path = tmp_path / "state.json"
    summary = run(
        session_dir=session_dir,
        session_limit=10,
        project_dirs=[repo],
        db_path=store.db_path,
        state_path=state_path,
        dry_run=False,
        git_depth=10,
    )

    assert summary["claims_created"] >= 2
    assert summary["by_kind"]["path"] >= 1
    assert summary["by_kind"]["port"] >= 1
    assert summary["git_sources"]
    assert state_path.exists()

    # Second run should not duplicate claims from the same session or git head.
    second = run(
        session_dir=session_dir,
        session_limit=10,
        project_dirs=[repo],
        db_path=store.db_path,
        state_path=state_path,
        dry_run=False,
        git_depth=10,
    )
    assert second["claims_created"] == 0


def test_discover_session_files_orders_newest_first(tmp_path: Path) -> None:
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    old = session_dir / "old.json"
    new = session_dir / "new.json"
    old.write_text(json.dumps({"session_id": "old"}), encoding="utf-8")
    new.write_text(json.dumps({"session_id": "new"}), encoding="utf-8")
    old.touch()
    new.touch()

    files = _discover_session_files(session_dir, limit=1)
    assert files[0].name == "new.json"
