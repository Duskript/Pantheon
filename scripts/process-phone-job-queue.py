#!/usr/bin/env python3
"""Drain the shared phone job queue.

Default behavior is conservative: process at most one due job per invocation. A
future systemd timer/cron can call this every minute; concurrent invocations are
serialized by phone_job_queue's lease. Use --no-phone for parser/queue smoke tests
that must not touch ADB or open apps.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PHONE_BRIDGE_DIR = Path("/home/konan/projects/consignment-dashboard/phone-bridge")
if str(PHONE_BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(PHONE_BRIDGE_DIR))

# Allow validation/tests to redirect the file-backed queue before phone_job_queue
# imports its QUEUE_ROOT constant.
if "--queue-root" in sys.argv:
    idx = sys.argv.index("--queue-root")
    if idx + 1 < len(sys.argv):
        os.environ["PHONE_JOB_QUEUE_ROOT"] = sys.argv[idx + 1]

from phone_job_queue import FAILED_DIR, RUNNING_DIR, acquire_lease, finish_job, pending_jobs, pop_due_job, queue_status, release_lease, utc_now  # noqa: E402
from phone_social_publisher import publish_social_post, require_device, verify_post_live  # noqa: E402
from phone_post_guard import validate_post_payload  # noqa: E402
from google_lens_phone import identify_with_google_lens  # noqa: E402

STALE_RUNNING_SECONDS = int(os.environ.get("PHONE_JOB_STALE_RUNNING_SECONDS", "900"))


def _parse_ts(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def recover_stale_running_jobs(*, max_age_seconds: int = STALE_RUNNING_SECONDS) -> list[dict[str, Any]]:
    recovered: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).timestamp()
    for path in sorted(RUNNING_DIR.glob("*.json")):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        started = _parse_ts(job.get("started_at")) or _parse_ts(job.get("created_at")) or path.stat().st_mtime
        age = now - started
        if age < max_age_seconds:
            continue
        job["status"] = "failed"
        job["finished_at"] = utc_now()
        job["result"] = {
            "ok": False,
            "status": "stale_running_recovered",
            "message": f"Phone queue job was stuck in running for {int(age)}s and was moved to failed for operator review.",
            "stale_age_seconds": int(age),
        }
        final = FAILED_DIR / path.name
        path.write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")
        path.replace(final)
        job["path"] = str(final)
        recovered.append(job)
    return recovered


def redact_job(job: dict[str, Any]) -> dict[str, Any]:
    payload = dict(job.get("payload") or {})
    if "text" in payload:
        payload["text_preview"] = str(payload.pop("text"))[:160]
    if "draft" in payload:
        payload["draft_preview"] = str(payload.pop("draft"))[:160]
    if "image_base64" in payload:
        payload["image_base64"] = "[base64 omitted]"
    return {**job, "payload": payload}


def run_one(*, no_phone: bool = False) -> dict[str, Any]:
    owner = "process-phone-job-queue"
    recovered = recover_stale_running_jobs()
    lease = acquire_lease(owner)
    if not lease.acquired:
        return {
            "ok": True,
            "status": "phone_busy",
            "holder": lease.holder,
            "message": "Phone lane is busy; queued jobs remain pending.",
        }
    try:
        job = pop_due_job()
        if job is None:
            result = {"ok": True, "status": "empty", "queue": queue_status()}
            if recovered:
                result["recovered_stale_running"] = len(recovered)
            return result
        payload = dict(job.get("payload") or {})
        kind = str(job.get("kind") or "")
        if no_phone:
            result = {
                "ok": True,
                "status": "no_phone_smoke",
                "kind": kind,
                "job_id": job.get("job_id"),
                "media_paths": payload.get("media_paths") if isinstance(payload.get("media_paths"), list) else [],
                "message": "Queue parsing succeeded; no phone action was performed.",
            }
            return finish_job(job, ok=True, result=result)
        if kind in {"google-lens-identify", "google_lens_identify"}:
            try:
                result = identify_with_google_lens(payload)
            except Exception as exc:
                result = {
                    "ok": False,
                    "status": "lens_exception",
                    "error": str(exc),
                    "exception_type": type(exc).__name__,
                    "message": "Phone Google Lens raised before returning a result; job was marked failed.",
                }
                return finish_job(job, ok=False, result=result)
            return finish_job(job, ok=bool(result.get("ok")), result=result)
        if kind not in {"social-post", "social_post"}:
            result = {"ok": False, "status": "unsupported_kind", "kind": kind}
            return finish_job(job, ok=False, result=result)
        platform = str(payload.get("platform") or payload.get("surface") or "")
        # Only the final APPROVED body may be published. The old
        # `or payload.get("draft")` fallback meant a job with no `text` silently
        # published a raw draft - the same defect class that leaked an artifact
        # envelope onto a live Company Page. Refuse instead of falling back.
        post_text = str(payload.get("text") or "")
        if not post_text.strip():
            result = {
                "ok": False,
                "status": "payload_missing_approved_text",
                "message": (
                    "Job carries no 'text' field. The publish step accepts only the final "
                    "approved post body; it will not fall back to a raw 'draft'."
                ),
            }
            return finish_job(job, ok=False, result=result)
        # Refuse pipeline plumbing before the phone is touched.
        guard = validate_post_payload(post_text, platform)
        if not guard.get("ok"):
            return finish_job(job, ok=False, result={
                **guard,
                "platform": platform,
                "message": guard.get("message", "post text refused by the publish guard"),
            })
        dry_run = bool(payload.get("dry_run"))
        try:
            serial = require_device()
            result = publish_social_post(
                serial=serial,
                platform=platform,
                text=post_text,
                first_comment=str(payload.get("first_comment") or ""),
                dry_run=dry_run,
                media_paths=payload.get("media_paths") if isinstance(payload.get("media_paths"), list) else [],
                job_dir=Path(job["path"]).with_suffix(""),
            )
        except Exception as exc:
            result = {
                "ok": False,
                "status": "publisher_exception",
                "error": str(exc),
                "exception_type": type(exc).__name__,
                "message": "Phone publisher raised before returning a result; job was marked failed instead of being left in running/.",
            }
            return finish_job(job, ok=False, result=result)

        # ── LIVE VERIFICATION ────────────────────────────────────────────────
        # publish_social_post ends at status="submitted" with ok=bool(post_tapped).
        # A tapped button is NOT a live post, so the job is not allowed to report
        # success on the strength of the tap alone. Read the post back off the
        # account; only a positive read-back makes the job ok.
        if result.get("ok") and not dry_run and post_text.strip():
            try:
                verification = verify_post_live(
                    serial=serial,
                    platform=platform,
                    text=post_text,
                    job_dir=Path(job["path"]).with_suffix("") / "verify",
                )
            except Exception as exc:
                verification = {
                    "ok": False,
                    "status": "verify_exception",
                    "exception_type": type(exc).__name__,
                    "error": str(exc),
                }
            result["live_verification"] = verification
            if not verification.get("ok"):
                result["status"] = f"published_unverified:{verification.get('status')}"
                result["message"] = (
                    "The post action was submitted but could NOT be read back off the "
                    "account - treat as NOT live until proven."
                )
                return finish_job(job, ok=False, result=result)
            result["status"] = "published_and_verified_live"
        return finish_job(job, ok=bool(result.get("ok")), result=result)
    finally:
        release_lease(owner)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true", help="List queued jobs without touching the phone")
    parser.add_argument("--status", action="store_true", help="Print queue status without touching the phone")
    parser.add_argument("--no-phone", action="store_true", help="Drain one due job as a parser smoke test without ADB/app actions")
    parser.add_argument("--queue-root", help="Override PHONE_JOB_QUEUE_ROOT for validation/tests")
    parser.add_argument("--json", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args()

    if args.status:
        result: Any = queue_status()
    elif args.list:
        result = [redact_job(job) for job in pending_jobs(include_future=True)]
    else:
        result = run_one(no_phone=args.no_phone)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(result)
    return 0 if not isinstance(result, dict) or result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
