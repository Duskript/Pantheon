#!/usr/bin/env python3
"""Per-surface route sweep for the phone social publisher.

WHY THIS EXISTS
---------------
`phone_social_publisher.publish_social_post()` has four routes, one per landing
surface. The script was reported as flaky, and "flaky" is not a diagnosis — it
could be one broken route, four broken routes, a device problem, or an app-update
problem. This harness exercises ONE surface at a time on the real device with
`dry_run=True`, which pauses before the final Post tap, and writes the evidence
(screenshot + hierarchy XML + result JSON) to disk so each route can be judged
individually.

It also refuses to guess the surface: the slug must be in
`pantheon/shared/content-surfaces.json`, so the sweep can never drift from the
canonical registry.

Usage:
    python3 social-route-sweep.py --surface konan-facebook
    python3 social-route-sweep.py --all
    python3 social-route-sweep.py --all --media /path/to/image.png

Nothing is ever published: `dry_run=True` is hardcoded and not parameterized.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

PHONE_BRIDGE_DIR = Path("/home/konan/projects/consignment-dashboard/phone-bridge")
REGISTRY = Path("/home/konan/pantheon/shared/content-surfaces.json")
EVIDENCE_ROOT = Path("/home/konan/pantheon/phone-queue/route-sweep")

if str(PHONE_BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(PHONE_BRIDGE_DIR))

# surface slug -> the platform string publish_social_post dispatches on
SURFACE_PLATFORM = {
    "konan-facebook": "personal facebook",
    "konan-linkedin": "personal linkedin",
    "theoforge-facebook": "business facebook",
    "theoforge-linkedin": "business linkedin",
}

SWEEP_TEXT = "Pantheon route sweep test. Nothing is published."


def load_registry() -> dict[str, Any]:
    return json.loads(REGISTRY.read_text())


def sweep(surface: str, *, media: list[str], out_root: Path, serial: str = "") -> dict[str, Any]:
    from phone_social_publisher import publish_social_post, platform_package

    if surface not in SURFACE_PLATFORM:
        raise SystemExit(
            f"unknown surface {surface!r}; known: {', '.join(sorted(SURFACE_PLATFORM))}"
        )
    registry = load_registry()
    if surface not in (registry.get("surfaces") or {}):
        raise SystemExit(f"{surface!r} is not in the canonical registry {REGISTRY}")

    platform = SURFACE_PLATFORM[surface]
    job_dir = out_root / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{surface}"
    job_dir.mkdir(parents=True, exist_ok=True)
    print(f"[sweep] surface={surface!r} platform={platform!r} -> {job_dir}", flush=True)

    started = time.time()
    try:
        result = publish_social_post(
            serial=serial,
            platform=platform,
            text=SWEEP_TEXT,
            first_comment="",
            dry_run=True,                       # hardcoded: never publish in a sweep
            media_paths=media,
            job_dir=job_dir,
        )
    except Exception as exc:
        result = {
            "ok": False,
            "status": "publisher_exception",
            "exception_type": type(exc).__name__,
            "error": str(exc),
        }
    result["_sweep"] = {
        "surface": surface,
        "platform": platform,
        "package": _safe_package(platform_package, platform),
        "media": media,
        "seconds": round(time.time() - started, 1),
        "job_dir": str(job_dir),
        "dry_run": True,
    }
    (job_dir / "sweep-result.json").write_text(json.dumps(result, indent=2, sort_keys=True))
    return result


def _safe_package(fn, platform: str) -> str:
    try:
        return fn(platform)
    except Exception as exc:
        return f"<{type(exc).__name__}: {exc}>"


def report(result: dict[str, Any]) -> str:
    s = result.get("_sweep", {})
    ok = "OK  " if result.get("ok") else "FAIL"
    return (
        f"{ok} {s.get('surface'):20} status={result.get('status')!r} "
        f"{s.get('seconds')}s pkg={s.get('package')} msg={str(result.get('message'))[:90]!r}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--surface", action="append", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--media", action="append", default=[])
    ap.add_argument("--out", default=str(EVIDENCE_ROOT))
    ap.add_argument("--serial", default=os.environ.get("PHONE_ADB_SERIAL", ""))
    args = ap.parse_args()

    surfaces = sorted(SURFACE_PLATFORM) if args.all else args.surface
    if not surfaces:
        ap.error("pass --surface <slug> (repeatable) or --all")

    media = [str(Path(m).expanduser()) for m in args.media]
    missing = [m for m in media if not Path(m).exists()]
    if missing:
        raise SystemExit(f"media not found: {missing}")

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    results = []
    for surface in surfaces:
        r = sweep(surface, media=media, out_root=out_root, serial=args.serial)
        results.append(r)
        print(report(r), flush=True)

    (out_root / "sweep-summary.json").write_text(
        json.dumps({"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "surfaces": surfaces, "media": media,
                    "results": [{k: v for k, v in r.items() if k != "steps"} for r in results]},
                   indent=2, sort_keys=True))
    passed = sum(1 for r in results if r.get("ok"))
    print(f"\n[sweep] {passed}/{len(results)} routes opened and validated "
          f"(dry_run=True: nothing was published)")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
