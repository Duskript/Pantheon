"""Deterministic structural claim extraction for Ichor.

Phase 0D watches session text and git logs for boring infrastructure facts that
LLMs often skip: paths, ports, environment variables, flags, and dependency
mentions. Extracted claims are persisted through ``ClaimStore`` with
``extracted_by='structural'`` and a fixed confidence score.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from lib.ichor import schema_v2
from lib.ichor.contracts import Claim, ClaimStore, Evidence

DEFAULT_SESSION_DIR = Path.home() / ".hermes" / "sessions"
DEFAULT_DB_PATH = Path.home() / ".hermes" / "ichor.db"
DEFAULT_STATE_PATH = Path.home() / ".hermes" / "structural_extractor_state.json"
DEFAULT_SESSION_LIMIT = 5
DEFAULT_GIT_DEPTH = 20
DEFAULT_CONFIDENCE = 0.85
DEFAULT_EXTRACTED_BY = "structural"

_PATH_RE = re.compile(r"(?:~/|/)[^\s\]\)>,;]{4,}")
_PORT_RE = re.compile(r"(?:--port\s+|port(?:\s*[:=]|\s+)\s*)(\d{2,5})", re.IGNORECASE)
_ENV_ASSIGN_RE = re.compile(r"\b([A-Z][A-Z0-9_]{2,})=([^\s,;]+)")
_ENV_WORD_RE = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")
_FLAG_RE = re.compile(r"(--[A-Za-z0-9][\w-]*)(?:[=\s]+([^\s,;]+))?")
_DEP_RE = re.compile(
    r"(?i)\b(?:uses|depends on|requires)\s+([A-Za-z0-9_.\-/]+(?:\s+v?\d[\w.\-+]*)?)"
)
_DEP_CHANGE_RE = re.compile(
    r"(?i)\b(?:bump|upgrade|update|pin|switch(?:ed)?\s+to)\s+([A-Za-z0-9_.\-/]+)(?:\s+(?:to|at)\s+v?([\d][\w.\-+]*))?"
)


@dataclass(frozen=True)
class StructuralClaimCandidate:
    kind: str
    text: str
    excerpt: str
    source_session_id: str


@dataclass(frozen=True)
class SourceBundle:
    source_id: str
    text: str
    source_path: Path


def _flatten_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                for key in ("text", "content", "value"):
                    if item.get(key):
                        parts.append(str(item[key]))
                        break
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    if isinstance(content, dict):
        for key in ("text", "content", "value", "message"):
            value = content.get(key)
            if value:
                return _flatten_content(value)
    return str(content)


def _session_id_from_text(text: str, fallback: str) -> str:
    match = re.search(r'^session_id:\s*"?([^"\n]+)"?', text, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return fallback


def load_source_bundle(path: Path) -> SourceBundle:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".json":
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            session_id = str(parsed.get("session_id") or parsed.get("id") or path.stem)
            messages = parsed.get("messages", [])
            chunks: list[str] = []
            if isinstance(messages, list):
                for message in messages:
                    if not isinstance(message, dict):
                        continue
                    role = str(message.get("role") or "message").strip()
                    content = _flatten_content(message.get("content"))
                    if content.strip():
                        chunks.append(f"[{role}] {content.strip()}")
            elif raw.strip():
                chunks.append(raw.strip())
            return SourceBundle(session_id, "\n".join(chunks), path)
    session_id = _session_id_from_text(raw, path.stem)
    return SourceBundle(session_id, raw, path)


def _ensure_claim_schema(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        vendor_path = Path.home() / ".hermes" / "vendor" / "py311"
        if str(vendor_path) not in sys.path:
            sys.path.insert(0, str(vendor_path))
        conn.enable_load_extension(True)
        try:
            import sqlite_vec
            sqlite_vec.load(conn)
        finally:
            conn.enable_load_extension(False)
        conn.executescript(schema_v2.SCHEMA_SQL)
    finally:
        conn.close()


def _normalize_path_claim(path_text: str) -> str:
    cleaned = path_text.rstrip(").,;]")
    return f"Path referenced: {cleaned}"


def _normalize_port_claim(port: str) -> str:
    return f"Port referenced: {port}"


def _normalize_env_claim(key: str) -> str:
    return f"Environment variable referenced: {key}"


def _normalize_flag_claim(flag: str, value: str | None = None) -> str:
    if value:
        return f"Flag referenced: {flag} {value}"
    return f"Flag referenced: {flag}"


def _normalize_dependency_claim(name: str, version: str | None = None) -> str:
    if version:
        return f"Dependency referenced: {name} v{version}"
    return f"Dependency referenced: {name}"


def _is_env_context(line: str) -> bool:
    lowered = line.lower()
    return any(token in lowered for token in ("env", "environment", "secret", "token", "config", "variable")) or "→" in line or "=>" in line


def extract_structural_candidates(text: str, source_session_id: str) -> list[StructuralClaimCandidate]:
    candidates: list[StructuralClaimCandidate] = []
    seen: set[tuple[str, str, str]] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        for match in _PATH_RE.finditer(line):
            claim_text = _normalize_path_claim(match.group(0))
            key = ("path", claim_text, line)
            if key not in seen:
                candidates.append(StructuralClaimCandidate("path", claim_text, line, source_session_id))
                seen.add(key)

        for match in _PORT_RE.finditer(line):
            claim_text = _normalize_port_claim(match.group(1))
            key = ("port", claim_text, line)
            if key not in seen:
                candidates.append(StructuralClaimCandidate("port", claim_text, line, source_session_id))
                seen.add(key)

        for match in _ENV_ASSIGN_RE.finditer(line):
            claim_text = _normalize_env_claim(match.group(1))
            key = ("env", claim_text, line)
            if key not in seen:
                candidates.append(StructuralClaimCandidate("env", claim_text, line, source_session_id))
                seen.add(key)

        if _is_env_context(line):
            for key_name in _ENV_WORD_RE.findall(line):
                if key_name in {"HTTP", "HTTPS", "UTC", "JSON", "CLI", "SQL", "API"}:
                    continue
                claim_text = _normalize_env_claim(key_name)
                key = ("env", claim_text, line)
                if key not in seen:
                    candidates.append(StructuralClaimCandidate("env", claim_text, line, source_session_id))
                    seen.add(key)

        for match in _FLAG_RE.finditer(line):
            flag = match.group(1)
            value = match.group(2)
            if flag == "--":
                continue
            claim_text = _normalize_flag_claim(flag, value)
            key = ("flag", claim_text, line)
            if key not in seen:
                candidates.append(StructuralClaimCandidate("flag", claim_text, line, source_session_id))
                seen.add(key)

        for match in _DEP_RE.finditer(line):
            dep = match.group(1).strip()
            claim_text = _normalize_dependency_claim(dep)
            key = ("dependency", claim_text, line)
            if key not in seen:
                candidates.append(StructuralClaimCandidate("dependency", claim_text, line, source_session_id))
                seen.add(key)

        for match in _DEP_CHANGE_RE.finditer(line):
            dep = match.group(1).strip()
            version = match.group(2).strip() if match.group(2) else None
            claim_text = _normalize_dependency_claim(dep, version)
            key = ("dependency", claim_text, line)
            if key not in seen:
                candidates.append(StructuralClaimCandidate("dependency", claim_text, line, source_session_id))
                seen.add(key)

    return candidates


def _discover_session_files(session_dir: Path, limit: int = DEFAULT_SESSION_LIMIT) -> list[Path]:
    if not session_dir.exists():
        return []
    files = [p for p in session_dir.iterdir() if p.is_file() and p.suffix.lower() in {".json", ".md", ".txt"}]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def _connect_store(db_path: Path | None = None) -> tuple[sqlite3.Connection, ClaimStore]:
    path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn, ClaimStore(path)


def _claim_exists(conn: sqlite3.Connection, source_session_id: str, claim_text: str) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM ichor_claims
        WHERE extracted_by = ? AND source_session_id = ? AND text = ?
        LIMIT 1
        """,
        (DEFAULT_EXTRACTED_BY, source_session_id, claim_text),
    ).fetchone()
    return row is not None


def persist_candidates(
    store: ClaimStore,
    candidates: Iterable[StructuralClaimCandidate],
    *,
    confidence: float = DEFAULT_CONFIDENCE,
    dry_run: bool = False,
) -> dict[str, Any]:
    path = Path(store.db_path)
    _ensure_claim_schema(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    created = 0
    skipped = 0
    by_kind: dict[str, int] = {}
    inserted: list[dict[str, Any]] = []
    try:
        for candidate in candidates:
            if _claim_exists(conn, candidate.source_session_id, candidate.text):
                skipped += 1
                continue
            by_kind[candidate.kind] = by_kind.get(candidate.kind, 0) + 1
            inserted.append(
                {
                    "kind": candidate.kind,
                    "text": candidate.text,
                    "excerpt": candidate.excerpt,
                    "source_session_id": candidate.source_session_id,
                }
            )
            if dry_run:
                created += 1
                continue
            claim = Claim(
                text=candidate.text,
                type=candidate.kind,
                confidence=confidence,
                extracted_by=DEFAULT_EXTRACTED_BY,
                source_session_id=candidate.source_session_id,
            )
            claim_id = store.insert_claim(
                claim,
                evidence=[
                    Evidence(
                        source_session_id=candidate.source_session_id,
                        excerpt=candidate.excerpt,
                    )
                ],
            )
            created += 1
            inserted[-1]["claim_id"] = claim_id
        conn.commit()
    finally:
        conn.close()
    return {
        "created": created,
        "skipped": skipped,
        "by_kind": by_kind,
        "claims": inserted,
        "dry_run": dry_run,
    }


def extract_from_bundle(bundle: SourceBundle) -> list[StructuralClaimCandidate]:
    return extract_structural_candidates(bundle.text, bundle.source_id)


def extract_from_source_file(path: Path) -> SourceBundle:
    return load_source_bundle(path)


def _load_state(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        return {"git_heads": {}}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {"git_heads": {}}


def _save_state(state_path: Path, state: dict[str, Any]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _git_head(repo: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception:
        return None
    head = result.stdout.strip()
    return head or None


def _git_log(repo: Path, since_head: str | None, depth: int = DEFAULT_GIT_DEPTH) -> str:
    cmd = ["git", "-C", str(repo), "log", "--oneline"]
    if since_head:
        cmd.append(f"{since_head}..HEAD")
    else:
        cmd.extend(["-n", str(depth), "HEAD"])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except Exception:
        return ""
    return result.stdout.strip()


def extract_from_git_repo(repo: Path, state: dict[str, Any], depth: int = DEFAULT_GIT_DEPTH) -> tuple[str | None, list[StructuralClaimCandidate]]:
    head = _git_head(repo)
    if head is None:
        return None, []
    repo_state = state.setdefault("git_heads", {})
    since_head = repo_state.get(str(repo))
    log_text = _git_log(repo, since_head, depth=depth)
    if not log_text:
        repo_state[str(repo)] = head
        return head, []

    source_id = f"git:{repo.name}:{head}"
    candidates = extract_structural_candidates(log_text, source_id)
    repo_state[str(repo)] = head
    return head, candidates


def run(
    *,
    session_dir: Path = DEFAULT_SESSION_DIR,
    session_limit: int = DEFAULT_SESSION_LIMIT,
    project_dirs: Iterable[Path] = (),
    db_path: Path = DEFAULT_DB_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    dry_run: bool = False,
    git_depth: int = DEFAULT_GIT_DEPTH,
) -> dict[str, Any]:
    store = ClaimStore(db_path)
    _ensure_claim_schema(db_path)
    summary: dict[str, Any] = {
        "sources": [],
        "claims_created": 0,
        "claims_skipped": 0,
        "by_kind": {},
        "dry_run": dry_run,
    }

    # Session files: process the newest N files, but dedupe against the claim table.
    for fp in _discover_session_files(session_dir, limit=session_limit):
        bundle = load_source_bundle(fp)
        candidates = extract_from_bundle(bundle)
        persisted = persist_candidates(store, candidates, dry_run=dry_run)
        summary["sources"].append(
            {
                "source": str(fp),
                "source_id": bundle.source_id,
                "candidates": len(candidates),
                **persisted,
            }
        )
        summary["claims_created"] += persisted["created"]
        summary["claims_skipped"] += persisted["skipped"]
        for kind, count in persisted["by_kind"].items():
            summary["by_kind"][kind] = summary["by_kind"].get(kind, 0) + count

    # Git logs: only scan repos that exist and look like git repos.
    state = _load_state(state_path)
    git_hits: list[dict[str, Any]] = []
    for repo in project_dirs:
        if not repo.exists() or not (repo / ".git").exists():
            continue
        head, candidates = extract_from_git_repo(repo, state, depth=git_depth)
        if head is None:
            continue
        persisted = persist_candidates(store, candidates, dry_run=dry_run)
        git_hits.append(
            {
                "source": str(repo),
                "head": head,
                "candidates": len(candidates),
                **persisted,
            }
        )
        summary["claims_created"] += persisted["created"]
        summary["claims_skipped"] += persisted["skipped"]
        for kind, count in persisted["by_kind"].items():
            summary["by_kind"][kind] = summary["by_kind"].get(kind, 0) + count

    if not dry_run:
        _save_state(state_path, state)
    summary["git_sources"] = git_hits
    summary["processed_at"] = datetime.now(timezone.utc).isoformat()
    return summary


def _default_project_dirs() -> list[Path]:
    env = os.environ.get("STRUCTURAL_EXTRACTOR_PROJECT_DIRS", "")
    if env.strip():
        return [Path(item).expanduser() for item in env.split(os.pathsep) if item.strip()]
    return [Path.home() / "pantheon", Path.home() / "athenaeum"]


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Ichor structural claim extractor")
    parser.add_argument("--session-dir", type=Path, default=DEFAULT_SESSION_DIR)
    parser.add_argument("--session-limit", type=int, default=DEFAULT_SESSION_LIMIT)
    parser.add_argument("--project-dir", action="append", type=Path, default=[])
    parser.add_argument("--git-depth", type=int, default=DEFAULT_GIT_DEPTH)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary only")
    args = parser.parse_args(argv)

    project_dirs = args.project_dir or _default_project_dirs()
    summary = run(
        session_dir=args.session_dir.expanduser(),
        session_limit=args.session_limit,
        project_dirs=[p.expanduser() for p in project_dirs],
        db_path=args.db_path.expanduser(),
        state_path=args.state_path.expanduser(),
        dry_run=args.dry_run,
        git_depth=args.git_depth,
    )
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "claims_created": summary["claims_created"],
                    "claims_skipped": summary["claims_skipped"],
                    "by_kind": summary["by_kind"],
                    "session_sources": len(summary["sources"]),
                    "git_sources": len(summary["git_sources"]),
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
