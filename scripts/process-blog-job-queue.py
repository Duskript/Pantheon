#!/usr/bin/env python3
"""Drain the Pantheon blog post queue.

Approved blog-content pipeline drafts land in /home/konan/pantheon/blog-queue.
This drainer processes at most one due job per invocation. By default it creates
Ghost drafts through ghost-publish.py; --no-publish validates queue parsing and
artifact shape without network/API calls.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

QUEUE_ROOT = Path(os.environ.get("BLOG_JOB_QUEUE_ROOT", "/home/konan/pantheon/blog-queue"))
PENDING_DIR = QUEUE_ROOT / "pending"
RUNNING_DIR = QUEUE_ROOT / "running"
DONE_DIR = QUEUE_ROOT / "done"
FAILED_DIR = QUEUE_ROOT / "failed"
DRAFTS_DIR = QUEUE_ROOT / "drafts"
LOCK_PATH = QUEUE_ROOT / "blog.lock"
GHOST_PUBLISH = Path(os.environ.get("GHOST_PUBLISH_BIN", "/home/konan/pantheon/ghost-publish.py"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_dirs() -> None:
    for directory in (QUEUE_ROOT, PENDING_DIR, RUNNING_DIR, DONE_DIR, FAILED_DIR, DRAFTS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    ensure_dirs()
    tmp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def acquire_lock() -> bool:
    ensure_dirs()
    payload = {"pid": os.getpid(), "created_at": utc_now(), "expires_epoch": time.time() + 900}
    encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    try:
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        try:
            holder = read_json(LOCK_PATH)
            if float(holder.get("expires_epoch") or 0) > time.time():
                return False
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
        LOCK_PATH.unlink(missing_ok=True)
        return acquire_lock()
    with os.fdopen(fd, "wb") as handle:
        handle.write(encoded)
    return True


def release_lock() -> None:
    LOCK_PATH.unlink(missing_ok=True)


def queue_status() -> dict[str, Any]:
    ensure_dirs()
    holder = None
    if LOCK_PATH.exists():
        try:
            holder = read_json(LOCK_PATH)
        except (OSError, json.JSONDecodeError):
            holder = {"corrupt": True}
    return {
        "ok": True,
        "root": str(QUEUE_ROOT),
        "lock_path": str(LOCK_PATH),
        "holder": holder,
        "pending": len(list(PENDING_DIR.glob("*.json"))),
        "running": len(list(RUNNING_DIR.glob("*.json"))),
        "done": len(list(DONE_DIR.glob("*.json"))),
        "failed": len(list(FAILED_DIR.glob("*.json"))),
        "drafts": len(list(DRAFTS_DIR.glob("*.md"))),
    }


def pending_jobs(include_future: bool = True) -> list[dict[str, Any]]:
    ensure_dirs()
    now = utc_now()
    jobs: list[dict[str, Any]] = []
    for path in sorted(PENDING_DIR.glob("*.json")):
        try:
            job = read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        job["path"] = str(path)
        if include_future or str(job.get("due_at") or "") <= now:
            jobs.append(job)
    jobs.sort(key=lambda item: (str(item.get("due_at") or ""), str(item.get("created_at") or "")))
    return jobs


def pop_due_job() -> dict[str, Any] | None:
    ensure_dirs()
    now = utc_now()
    for job in pending_jobs(include_future=False):
        if str(job.get("due_at") or "") > now:
            continue
        src = Path(str(job["path"]))
        dst = RUNNING_DIR / src.name
        try:
            src.replace(dst)
        except FileNotFoundError:
            continue
        job["path"] = str(dst)
        job["status"] = "running"
        job["started_at"] = utc_now()
        atomic_write_json(dst, job)
        return job
    return None


def finish_job(job: dict[str, Any], *, ok: bool, result: dict[str, Any]) -> dict[str, Any]:
    src = Path(str(job["path"]))
    final_dir = DONE_DIR if ok else FAILED_DIR
    final = final_dir / src.name
    job["status"] = "done" if ok else "failed"
    job["finished_at"] = utc_now()
    job["result"] = result
    atomic_write_json(src, job)
    src.replace(final)
    job["path"] = str(final)
    return job


def redact_job(job: dict[str, Any]) -> dict[str, Any]:
    payload = dict(job.get("payload") or {})
    if "body" in payload:
        payload["body_preview"] = str(payload.pop("body"))[:240]
    return {**job, "payload": payload}


def ensure_markdown(job: dict[str, Any]) -> Path:
    payload = dict(job.get("payload") or {})
    markdown_value = str(job.get("markdown_path") or payload.get("markdown_path") or "").strip()
    if markdown_value:
        markdown = Path(markdown_value)
        if markdown.exists():
            return markdown
    title = str(payload.get("title") or "Untitled TheoForge blog draft").strip() or "Untitled TheoForge blog draft"
    body = str(payload.get("body") or "").strip()
    if not body:
        raise ValueError("blog job is missing body and markdown_path")
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    markdown = DRAFTS_DIR / f"{job.get('job_id', 'blog')}.md"
    markdown.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
    return markdown


def create_ghost_draft(job: dict[str, Any]) -> dict[str, Any]:
    payload = dict(job.get("payload") or {})
    title = str(payload.get("title") or "Untitled TheoForge blog draft").strip() or "Untitled TheoForge blog draft"
    markdown = ensure_markdown(job)
    publish_mode = str(payload.get("publish_mode") or "draft").lower()
    args = ["python3", str(GHOST_PUBLISH)]
    if publish_mode != "publish":
        args.append("--draft")
    blog_image = payload.get("blog_image") if isinstance(payload.get("blog_image"), dict) else {}
    image_path = str(blog_image.get("image_path") or payload.get("feature_image") or "").strip()
    if image_path:
        args.extend(["--feature-image", image_path])
    args.extend([title, str(markdown)])
    proc = subprocess.run(args, check=False, capture_output=True, text=True, timeout=60)
    output = (proc.stdout + "\n" + proc.stderr).strip()
    ok = proc.returncode == 0 and "Error:" not in output
    return {
        "ok": ok,
        "status": "ghost_published" if ok and publish_mode == "publish" else "ghost_draft_created" if ok else "ghost_publish_failed",
        "publish_mode": publish_mode,
        "title": title,
        "markdown_path": str(markdown),
        "feature_image": image_path or None,
        "ghost_output": output[:2000],
        "returncode": proc.returncode,
    }


def run_one(*, no_publish: bool = False) -> dict[str, Any]:
    if not acquire_lock():
        return {"ok": True, "status": "blog_queue_busy", "message": "Blog queue is busy; jobs remain pending."}
    try:
        job = pop_due_job()
        if job is None:
            return {"ok": True, "status": "empty", "queue": queue_status()}
        kind = str(job.get("kind") or "")
        if kind not in {"blog-post", "blog_post"}:
            return finish_job(job, ok=False, result={"ok": False, "status": "unsupported_kind", "kind": kind})
        markdown = ensure_markdown(job)
        if no_publish:
            result = {
                "ok": True,
                "status": "no_publish_smoke",
                "job_id": job.get("job_id"),
                "kind": kind,
                "markdown_path": str(markdown),
                "feature_image": (dict(job.get("payload") or {}).get("blog_image") or {}).get("image_path") if isinstance((dict(job.get("payload") or {}).get("blog_image") or {}), dict) else None,
                "message": "Queue parsing and markdown artifact validation succeeded; Ghost was not called.",
            }
            return finish_job(job, ok=True, result=result)
        payload = dict(job.get("payload") or {})
        destination = str(payload.get("destination") or "ghost-draft")
        if destination.startswith("ghost"):
            result = create_ghost_draft(job)
            return finish_job(job, ok=bool(result.get("ok")), result=result)
        result = {
            "ok": True,
            "status": "markdown_artifact_ready",
            "job_id": job.get("job_id"),
            "markdown_path": str(markdown),
            "message": "Blog post kept as a local Markdown artifact; no Ghost destination requested.",
        }
        return finish_job(job, ok=True, result=result)
    finally:
        release_lock()


def apply_queue_root(path: str) -> None:
    global QUEUE_ROOT, PENDING_DIR, RUNNING_DIR, DONE_DIR, FAILED_DIR, DRAFTS_DIR, LOCK_PATH
    QUEUE_ROOT = Path(path)
    PENDING_DIR = QUEUE_ROOT / "pending"
    RUNNING_DIR = QUEUE_ROOT / "running"
    DONE_DIR = QUEUE_ROOT / "done"
    FAILED_DIR = QUEUE_ROOT / "failed"
    DRAFTS_DIR = QUEUE_ROOT / "drafts"
    LOCK_PATH = QUEUE_ROOT / "blog.lock"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true", help="List queued blog jobs without publishing")
    parser.add_argument("--status", action="store_true", help="Print queue status without publishing")
    parser.add_argument("--no-publish", action="store_true", help="Drain one due job as a parser/artifact smoke test without Ghost API calls")
    parser.add_argument("--queue-root", help="Override BLOG_JOB_QUEUE_ROOT for validation/tests")
    parser.add_argument("--json", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args()
    if args.queue_root:
        apply_queue_root(args.queue_root)
    if args.status:
        result: Any = queue_status()
    elif args.list:
        result = [redact_job(job) for job in pending_jobs(include_future=True)]
    else:
        result = run_one(no_publish=args.no_publish)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(result)
    return 0 if not isinstance(result, dict) or result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
