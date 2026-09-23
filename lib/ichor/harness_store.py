"""Versioned harness store with apply/revert for automated edits.

Design
------
The store is a **git repository separate from the live tree**
(`~/pantheon-harness-store`). It holds a mirror of the harness artifacts that
matter — god `SOUL.md` files, `SKILL.md` files, cron prompts, gate configs — one
commit per applied edit, with **tags for promoted versions**.

The live files are *materialized* from the store, not read out of it. That
ordering matters: `apply_edit` writes the new bytes to the live path and commits
the same bytes to the store, so a revert is "check out the previous revision and
put those bytes back", which restores the file **byte-for-byte** rather than
approximately.

Scope of the guarantee
----------------------
Phase 1 delivers **reversibility and provenance**. It does *not* deliver trust
separation: the agent can still write the live path directly. True separation —
the editing agent having no write path to the ledger, the store, or guardrail
config — is a documented prerequisite before any T1 auto-apply is enabled (the
plan's "split trust domains", plus the note that some Pantheon profiles have no
systemd sandbox). Do not read this module as having closed that gap.

What it fixes
-------------
The one live applier appends a marked block to god `SOUL.md` files and skips on a
single marker string, so a re-application is a **silent** no-op and an unwanted
change is unrecoverable. Here a repeat application is detected, **recorded as a
no-op**, and reported; and every applied edit has a revision to return to.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from lib.ichor import edit_ledger

log = logging.getLogger("ichor.harness_store")

_HOME = Path.home()

#: The store lives OUTSIDE ~/.hermes and outside the pantheon repo.
STORE_DIR = Path(os.environ.get("ICHOR_HARNESS_STORE", str(_HOME / "pantheon-harness-store")))
#: Live paths under this root are mirrored as `hermes/<relative>`.
LIVE_ROOT = Path(os.environ.get("ICHOR_LIVE_ROOT", str(_HOME / ".hermes")))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_backup_artifact(rel: str) -> bool:
    """True when a store-relative path lives in a backup directory.

    The store IS the version history, so tracking a backup copy adds a second
    artifact that can silently drift from the one it copies while nothing reads
    it. It can only ever produce a confusing diff — e.g.
    `profiles/_bootstrap-backups/SOUL.md` tracking `SOUL.md`.
    """
    for seg in rel.split("/"):
        s = seg.lower()
        if s in ("backup", "backups") or s.endswith("-backups") or s.endswith("_backups"):
            return True
    return False


def _atomic_write(path: Path, data: bytes) -> None:
    """Atomically write `data` to `path`, writing THROUGH a symlink.

    `os.replace` operates on the link itself: given a symlink path it replaces
    the LINK with a regular file. An edit to `profiles/hermes/SOUL.md` (a symlink
    to the shared `~/.hermes/SOUL.md`) would therefore not update the shared
    artifact — it would silently detach that profile from it, leaving the global
    file untouched and the profile holding a private copy. The store keys the
    edit on the RESOLVED path, so the bytes would also land somewhere other than
    where the ledger says. Resolve first so the write reaches the real artifact.
    """
    path = Path(path)
    if path.is_symlink():
        path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp-harness")
    tmp.write_bytes(data)
    os.replace(tmp, path)


class HarnessStoreError(RuntimeError):
    pass


class HarnessStore:
    """Git-backed version store for harness artifacts."""

    def __init__(
        self,
        repo_dir: Optional[Path] = None,
        live_root: Optional[Path] = None,
        ledger_path: Optional[Path] = None,
    ) -> None:
        self.repo = Path(repo_dir) if repo_dir else STORE_DIR
        self.live_root = Path(live_root) if live_root else LIVE_ROOT
        self.ledger_path = Path(ledger_path) if ledger_path else edit_ledger.LEDGER_PATH
        self._ensure_repo()

    # ── git plumbing ───────────────────────────────────────────────────────

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        r = subprocess.run(["git", *args], cwd=str(self.repo),
                           capture_output=True, text=True)
        if check and r.returncode != 0:
            raise HarnessStoreError(f"git {' '.join(args)} failed: {r.stderr.strip()[:300]}")
        return r

    def _ensure_repo(self) -> None:
        if (self.repo / ".git").exists():
            return
        self.repo.mkdir(parents=True, exist_ok=True)
        self._git("init", "-q")
        # Commits need an identity; scope it to this repo only.
        self._git("config", "user.name", "pantheon-harness-store")
        self._git("config", "user.email", "harness-store@pantheon.local")
        readme = self.repo / "README.md"
        readme.write_text(
            "# Pantheon harness store\n\n"
            "Versioned copies of harness artifacts (god SOUL.md, SKILL.md, cron\n"
            "prompts, gate configs). One commit per applied edit; tags mark\n"
            "promoted versions. The live tree is materialized FROM this store.\n\n"
            "Every commit corresponds to an `edit-ledger.jsonl` record. Do not\n"
            "edit files here by hand — use lib/ichor/harness_store.py so the\n"
            "ledger and the store stay consistent.\n"
        )
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "chore(harness-store): initialise empty store")

    def head(self) -> str:
        r = self._git("rev-parse", "HEAD", check=False)
        return r.stdout.strip() if r.returncode == 0 else ""

    def resolve(self, rev: str) -> str:
        """Resolve a revision to a COMMIT sha.

        Peels to `^{commit}` on purpose: `git rev-parse <annotated-tag>` returns
        the tag OBJECT's sha, not the commit it points at, so a promoted version
        would resolve to something that is not a tree-ish you can check out.
        """
        return self._git("rev-parse", rev + "^{commit}").stdout.strip()

    def tag(self, name: str, message: str = "") -> str:
        args = ["tag", "-f", "-a", name, "-m", message or f"promoted {name}"]
        self._git(*args)
        return self.resolve(name)

    # ── path mapping ───────────────────────────────────────────────────────

    def rel_for(self, live_path: Path) -> str:
        """Store-relative path for a live artifact path."""
        live_path = Path(live_path).resolve()
        try:
            return "hermes/" + str(live_path.relative_to(self.live_root.resolve()))
        except ValueError:
            return "abs" + str(live_path)

    def store_path(self, rel: str) -> Path:
        return self.repo / rel

    # ── core operations ────────────────────────────────────────────────────

    def profiles_sharing(self, resolved: Path) -> List[str]:
        """Profile names whose SOUL.md resolves to this same file.

        Enumerates the real blast radius of an edit to a symlinked artifact:
        editing the global SOUL.md changes every profile that points at it.
        """
        out: List[str] = []
        base = Path(self.live_root) / "profiles"
        if not base.is_dir():
            return out
        for prof in sorted(base.iterdir()):
            soul = prof / "SOUL.md"
            try:
                if soul.is_file() and soul.resolve() == resolved:
                    out.append(prof.name)
            except OSError:
                continue
        return out

    def snapshot_paths(self, paths: List[Path], message: str) -> str:
        """Copy live bytes into the store and commit. Returns the commit sha."""
        self.last_skips = []
        for p in paths:
            p = Path(p)
            if not p.is_file():
                continue
            rel = self.rel_for(p)
            if is_backup_artifact(rel):
                # Recorded, never silent: an unexplained absence from the store
                # is indistinguishable from a failed import. The lesson from the
                # forge appender's marker no-op applies here too.
                self.last_skips.append({"rel": rel, "reason": "backup directory"})
                log.info("harness store: skipped backup artifact %s", rel)
                continue
            _atomic_write(self.store_path(rel), p.read_bytes())
        self._git("add", "-A")
        r = self._git("commit", "-q", "-m", message, check=False)
        if r.returncode != 0 and "nothing to commit" not in (r.stdout + r.stderr):
            raise HarnessStoreError(r.stderr.strip()[:300])
        return self.head()

    def snapshot_artifact(self, live_path: Path, message: Optional[str] = None) -> str:
        live_path = Path(live_path)
        msg = message or f"snapshot: {self.rel_for(live_path)}"
        return self.snapshot_paths([live_path], msg)

    def bytes_at(self, rel: str, rev: str) -> bytes:
        """Exact bytes of a store file at a revision.

        Uses `cat-file` in binary mode, not `git show`: reverts must restore
        byte-identical content, and a text-mode read would risk normalising line
        endings and silently breaking that guarantee.
        """
        proc = subprocess.run(["git", "cat-file", "-p", f"{rev}:{rel}"],
                              cwd=str(self.repo), capture_output=True)
        if proc.returncode != 0:
            raise HarnessStoreError(
                f"{rel} not present at {rev}: {proc.stderr.decode('utf-8', 'replace').strip()[:200]}"
            )
        return proc.stdout

    def materialize(self, rel: str, rev: str, live_path: Optional[Path] = None) -> bytes:
        """Write the store's bytes for `rel` at `rev` onto the live path (atomic)."""
        data = self.bytes_at(rel, rev)
        target = Path(live_path) if live_path else (
            self.live_root / rel[len("hermes/"):] if rel.startswith("hermes/") else Path("/" + rel[4:])
        )
        _atomic_write(target, data)
        return data

    # ── apply / revert ─────────────────────────────────────────────────────

    def apply_edit(
        self,
        live_path: Path,
        new_bytes: bytes,
        author_god: str,
        trigger: str,
        target_artifact_class: str,
        rationale: str,
        expected_improvement: Dict[str, str],
        inputs_read: List[str],
        human_approver: Optional[str] = None,
        marker: str = "",
        tag_as: str = "",
        eval_baseline_ref: str = "",
        allow_symlink: bool = False,
    ) -> Dict[str, Any]:
        """Apply an edit under the ledger's rules. Returns a result dict.

        `marker` enables idempotence: if the live file already contains it, the
        application is a **logged no-op** rather than a silent skip.

        Raises `edit_ledger.EditRejected` when the record fails admission, and
        `HarnessStoreError` when the artifact class is frozen.
        """
        live_path = Path(live_path)
        if not live_path.is_file():
            raise HarnessStoreError(f"artifact not found: {live_path}")

        if edit_ledger.is_frozen(target_artifact_class, self.ledger_path):
            raise HarnessStoreError(
                f"artifact class {target_artifact_class!r} is frozen to human-only "
                f"({edit_ledger.frozen_classes(self.ledger_path)[target_artifact_class]})"
            )

        # Symlinked targets. `profiles/hermes/SOUL.md -> ~/.hermes/SOUL.md`, and
        # `rel_for` keys on the RESOLVED path — correct for the store, but it
        # means an edit made through the profile path writes the file every
        # profile shares. If the ledger recorded the caller's path as-is, it
        # would name one profile while the bytes changed for all of them: the
        # diff would understate its own blast radius, which is the one thing
        # `expected_improvement.blast_radius` exists to prevent. So: refuse
        # unless the caller opts in, and when it does, record the real scope.
        symlink_extra: Dict[str, Any] = {}
        if live_path.is_symlink():
            resolved = live_path.resolve()
            sharers = self.profiles_sharing(resolved)
            if not allow_symlink:
                raise HarnessStoreError(
                    f"{live_path} is a symlink to {resolved} — editing it changes "
                    f"{len(sharers)} profile(s): {', '.join(sharers)}. Pass "
                    f"allow_symlink=True to accept that scope, or target the "
                    f"resolved path directly."
                )
            symlink_extra = {
                "resolved_target": str(resolved),
                "shared_with": sharers,
                "symlink_accepted": True,
            }

        rel = self.rel_for(live_path)
        before = live_path.read_bytes()

        # ── no-op detection, RECORDED not skipped ─────────────────────────
        if marker and marker.encode("utf-8") in before:
            entry = edit_ledger.record_noop(
                target_path=str(live_path),
                target_artifact_class=target_artifact_class,
                author_god=author_god,
                reason="marker already present",
                detail=marker[:80],
                path=self.ledger_path,
            )
            log.info("no-op: %s already contains the marker", live_path)
            return {"no_op": True, "reason": "marker already present", "event": entry}
        if new_bytes == before:
            entry = edit_ledger.record_noop(
                target_path=str(live_path),
                target_artifact_class=target_artifact_class,
                author_god=author_god,
                reason="content identical to live bytes",
                detail=f"sha256={sha256_bytes(before)[:16]}",
                path=self.ledger_path,
            )
            log.info("no-op: %s unchanged", live_path)
            return {"no_op": True, "reason": "content identical", "event": entry}

        diff = _unified_diff(before, new_bytes, str(live_path))

        # Admission BEFORE any side effect. Validating after the snapshot would
        # leave a git commit behind for a rejected edit, which contradicts
        # "nothing is written until the record is acceptable". The parent
        # revision is a placeholder here and is filled in once we know it.
        draft = edit_ledger.build_record(
            author_god=author_god,
            trigger=trigger,
            target_artifact_class=target_artifact_class,
            target_path=str(live_path),
            inputs_read=inputs_read,
            rationale=rationale,
            expected_improvement=expected_improvement,
            parent_version="pending",
            diff=diff,
            human_approver=human_approver,
            eval_baseline_ref=eval_baseline_ref,
            extra=symlink_extra or None,
        )

        # Now safe to touch the store: the pre-state is committed so a revert
        # has an exact revision to return to.
        parent_version = self.snapshot_artifact(live_path, f"pre-edit: {rel}")
        draft["parent_version"] = parent_version
        record = edit_ledger.append_record(draft, self.ledger_path)

        _atomic_write(live_path, new_bytes)
        new_sha = self.snapshot_paths(
            [live_path], f"edit {record['edit_id']}: {rel}"
        )
        promoted_tag = ""
        if tag_as:
            self.tag(tag_as, f"promoted after {record['edit_id']}")
            promoted_tag = tag_as

        return {
            "no_op": False,
            "edit_id": record["edit_id"],
            "version": new_sha,
            "parent_version": parent_version,
            "promoted_tag": promoted_tag,
            "before_sha256": sha256_bytes(before),
            "after_sha256": sha256_bytes(new_bytes),
            "rel": rel,
        }

    def revert(self, edit_id: str, reason: str, automatic: bool = False,
               live_path: Optional[Path] = None) -> Dict[str, Any]:
        """Restore the artifact to the revision captured before `edit_id`.

        Returns a dict including `byte_identical` — an assertion that the file
        now matches the recorded pre-edit bytes exactly. This is the acceptance
        test from the plan, surfaced as a runtime guarantee.
        """
        edits = {e["edit_id"]: e for e in edit_ledger.load_edits(self.ledger_path)}
        rec = edits.get(edit_id)
        if rec is None:
            raise HarnessStoreError(f"unknown edit_id {edit_id!r}")
        if rec.get("reverted"):
            raise HarnessStoreError(f"edit {edit_id} is already reverted")

        rel = self.rel_for(Path(rec["target_path"]))
        parent = rec["parent_version"]
        expected = self.bytes_at(rel, parent)
        restored = self.materialize(rel, parent, live_path=live_path)
        live = Path(rec["target_path"]).read_bytes()

        self.snapshot_paths([Path(rec["target_path"])], f"revert {edit_id}: {rel}")
        edit_ledger.record_revert(
            edit_id=edit_id, reason=reason, restored_version=parent,
            automatic=automatic, path=self.ledger_path,
        )
        frozen = edit_ledger.frozen_classes(self.ledger_path)
        return {
            "edit_id": edit_id,
            "restored_version": parent,
            "restored_sha256": sha256_bytes(restored),
            "live_sha256": sha256_bytes(live),
            "byte_identical": byte_identical(restored, expected),
            "artifact_class": rec.get("target_artifact_class"),
            "class_now_frozen": rec.get("target_artifact_class") in frozen,
            "freeze_reason": frozen.get(rec.get("target_artifact_class", ""), ""),
        }

    def invalidate_by_input(self, artifact_path: str, reason: str,
                            automatic: bool = True) -> List[Dict[str, Any]]:
        """Revert every live edit whose `inputs_read` touched `artifact_path`."""
        results = []
        for e in edit_ledger.edits_reading_artifact(artifact_path, self.ledger_path):
            if e.get("reverted"):
                continue
            try:
                results.append(self.revert(e["edit_id"], reason, automatic=automatic))
            except HarnessStoreError as exc:
                log.warning("could not revert %s: %s", e["edit_id"], exc)
        return results


def byte_identical(a: bytes, b: bytes) -> bool:
    """Exact byte equality.

    Named explicitly so a caller cannot mistake it for a fuzzy or
    newline-tolerant comparison. The revert guarantee is byte-exact, and the
    acceptance test asserts it.
    """
    return a == b


def _unified_diff(before: bytes, after: bytes, label: str) -> str:
    import difflib
    a = before.decode("utf-8", "replace").splitlines(keepends=True)
    b = after.decode("utf-8", "replace").splitlines(keepends=True)
    return "".join(difflib.unified_diff(a, b, fromfile=label + " (before)",
                                        tofile=label + " (after)"))
