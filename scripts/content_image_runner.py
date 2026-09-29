#!/usr/bin/env python3
"""Content-pipeline image runner - the 6am draft phase and the collect phase.

TWO PHASES, DELIBERATELY SEPARATE
---------------------------------
`draft`   generate image variants for a post, enqueue the publish job, and post the
          A/B/C choice to the surface's pipeline channel.
`collect` read the operator's reaction back and write the chosen variant onto the job.

They are separate because they happen at different times. The 6am run cannot wait for a
human to react, and a cron job that blocks on a reaction would either time out or -
worse - proceed with a default. So `draft` ends with a job that is publishable but has
no image selected, and `collect` supplies the selection when the operator makes it.

WHAT THIS NEVER DOES
--------------------
It never publishes. Jobs are enqueued with `dry_run` set unless `--live` is passed, and
even then the phone drainer owns the actual publish. This script has no publish path.

SURFACE MAPPING
---------------
Reads `shared/content-surfaces.json` rather than hardcoding channel ids, and derives the
platform string the publisher/verifier expects (`"<scope> <platform>"`, e.g.
`"business linkedin"`) from the same entry, so a surface cannot be half-renamed.

Usage
-----
    content_image_runner.py draft --surface theoforge-linkedin --text "..." [--tier draft]
    content_image_runner.py draft --all --text-file plan.json [--tier draft]
    content_image_runner.py collect [--json]
    content_image_runner.py status
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PANTHEON = Path("/home/konan/pantheon")
SCRIPTS = PANTHEON / "scripts"
PHONE_BRIDGE = Path("/home/konan/projects/consignment-dashboard/phone-bridge")
SURFACES_FILE = PANTHEON / "shared" / "content-surfaces.json"
STATE_FILE = Path.home() / ".hermes" / "pantheon" / "content-pipeline" / "runner_state.json"
IMAGES_ROOT = PANTHEON / "phone-queue" / "content-images"

for p in (str(SCRIPTS), str(PHONE_BRIDGE)):
    if p not in sys.path:
        sys.path.insert(0, p)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_surfaces() -> dict[str, Any]:
    return json.loads(SURFACES_FILE.read_text())["surfaces"]


def surface_entry(key: str) -> dict[str, Any]:
    surfaces = load_surfaces()
    if key not in surfaces:
        raise SystemExit(f"unknown surface {key!r}; known: {sorted(surfaces)}")
    return surfaces[key]


def platform_string(entry: dict[str, Any]) -> str:
    """The string the publisher and `verify_post_live` expect, e.g. 'business linkedin'."""
    return f"{entry['scope']} {entry['platform']}"


def load_state() -> dict[str, Any]:
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {"pending": {}}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")


# ── draft ───────────────────────────────────────────────────────────────

def draft_one(
    surface: str, text: str, *, tier: str = "draft", variants: int = 3,
    post_choice: bool = True, live: bool = False, aspect: str = "landscape",
) -> dict[str, Any]:
    """Generate variants, enqueue the job, and post the A/B/C choice.

    Ordering matters: the job is enqueued BEFORE the choice is posted, so a choice can
    never exist for a job that failed to be created. The reverse order would leave a
    posted question pointing at nothing.
    """
    import content_image_step as cis
    import reaction_choice as rc

    entry = surface_entry(surface)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = f"{surface}-{stamp}"
    out_dir = IMAGES_ROOT / slug

    manifest = cis.generate_variants(
        text, variants=variants, tier=tier, aspect=aspect, out_dir=out_dir, slug=slug)
    if not manifest["ok_count"]:
        return {"surface": surface, "ok": False,
                "error": "no image variant generated",
                "variants": manifest["variants"]}

    # enqueue the job first - see ordering note in the docstring
    from phone_job_queue import enqueue_job
    job = enqueue_job(
        kind="social-post",
        payload={
            "surface": surface,
            "platform": platform_string(entry),
            "text": text,
            "media_paths": None,
            "image_variants": [
                {k: v.get(k) for k in
                 ("variant_index", "variant_label", "modifier", "model", "path", "ok")}
                for v in manifest["variants"]
            ],
            "image_model": manifest["model"],
            "image_tier": manifest["tier"],
            "selected_image_path": None,
            "dry_run": not live,
            "workflow_id": f"content-image-{uuid.uuid4().hex[:8]}",
        },
        source="content-image-runner",
        reason="content_pipeline_draft",
    )

    choice: dict[str, Any] = {}
    if post_choice:
        images = {v["variant_label"]: Path(v["path"])
                  for v in manifest["variants"] if v["ok"] and v.get("path")}
        options = [(v["variant_label"], v["modifier"] or f"variant {v['variant_label']}")
                   for v in manifest["variants"] if v["ok"]]
        posted = rc.post_choice(
            thread_id=entry["discord_channel_id"],
            title=f"Image variants - {entry['label']}",
            body=(f"Tier `{manifest['tier']}` / model `{manifest['model']}`. "
                  f"Pick the image for this post. Nothing publishes until you choose."),
            options=options, image_paths=images, allow_urgent=True,
        )
        choice = {"message_id": posted["message_id"], "choice_id": posted["choice_id"],
                  "options": posted["options"], "reactions_failed": posted["reactions_failed"]}

    state = load_state()
    state["pending"][job["job_id"]] = {
        "surface": surface, "job_id": job["job_id"], "job_path": job["path"],
        "platform": platform_string(entry), "channel_id": entry["discord_channel_id"],
        "message_id": choice.get("message_id"), "options": choice.get("options", []),
        "tier": manifest["tier"], "model": manifest["model"],
        "variant_paths": {v["variant_label"]: v["path"]
                          for v in manifest["variants"] if v["ok"]},
        "created_at": utc_now(), "applied": False,
    }
    save_state(state)

    return {"surface": surface, "ok": True, "job_id": job["job_id"], "job_path": job["path"],
            "tier": manifest["tier"], "model": manifest["model"],
            "ok_count": manifest["ok_count"], "variants": manifest["variants"],
            "choice": choice, "dry_run": not live}


# ── collect ─────────────────────────────────────────────────────────────

def collect(*, apply_selection: bool = True) -> dict[str, Any]:
    """Read each pending choice and write the selected variant onto its job."""
    import content_image_step as cis
    import reaction_choice as rc

    state = load_state()
    results: list[dict[str, Any]] = []

    for job_id, rec in list(state["pending"].items()):
        if rec.get("applied"):
            continue
        if not rec.get("message_id"):
            results.append({"job_id": job_id, "surface": rec["surface"],
                            "status": "no_choice_posted"})
            continue
        try:
            out = rc.read_choice(
                message_id=rec["message_id"], thread_id=rec["channel_id"],
                options=rec.get("options") or None)
        except Exception as exc:  # noqa: BLE001 - one unreadable choice must not stop the rest
            results.append({"job_id": job_id, "surface": rec["surface"],
                            "status": "read_failed", "error": f"{type(exc).__name__}: {exc}"[:200]})
            continue

        row = {"job_id": job_id, "surface": rec["surface"], "status": out["status"],
               "choice": out["choice"], "actor": out["actor"], "urgent": out.get("urgent"),
               "refused": out.get("refused") or []}

        if out["status"] == "chosen" and apply_selection:
            label = out["choice"]
            path = (rec.get("variant_paths") or {}).get(label)
            if not path or not Path(path).exists():
                row["status"] = "chosen_but_variant_missing"
                row["error"] = f"variant {label} -> {path!r}"
            else:
                manifest = {
                    "variants": [{"variant_index": i, "variant_label": L, "modifier": "",
                                  "model": rec["model"], "path": p, "ok": True}
                                 for i, (L, p) in enumerate(sorted((rec["variant_paths"]).items()))],
                    "model": rec["model"], "tier": rec["tier"],
                }
                cis.attach_to_job(rec["job_path"], manifest,
                                  select=next(i for i, (L, _) in
                                              enumerate(sorted(rec["variant_paths"].items()))
                                              if L == label))
                rec["applied"] = True
                rec["applied_at"] = utc_now()
                rec["applied_choice"] = label
                rec["applied_actor"] = out["actor"]
                row["applied_path"] = path
                row["status"] = "applied"
        results.append(row)

    save_state(state)
    return {"checked": len(results), "results": results,
            "applied": sum(1 for r in results if r["status"] == "applied")}


# ── status ──────────────────────────────────────────────────────────────

def status() -> dict[str, Any]:
    state = load_state()
    pend = state.get("pending", {})
    return {
        "pending_total": len(pend),
        "awaiting_choice": [{"job_id": k, "surface": v["surface"],
                             "message_id": v.get("message_id"),
                             "created_at": v.get("created_at")}
                            for k, v in pend.items() if not v.get("applied")],
        "applied": [{"job_id": k, "surface": v["surface"],
                     "choice": v.get("applied_choice"), "actor": v.get("applied_actor"),
                     "applied_at": v.get("applied_at")}
                    for k, v in pend.items() if v.get("applied")],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Content-pipeline image runner")
    sub = ap.add_subparsers(dest="action", required=True)

    d = sub.add_parser("draft")
    d.add_argument("--surface")
    d.add_argument("--text")
    d.add_argument("--text-file", help="JSON: {surface: text} or [{\"surface\":..,\"text\":..}]")
    d.add_argument("--all", action="store_true", help="every phone surface from the registry")
    d.add_argument("--tier", default="draft")
    d.add_argument("--variants", type=int, default=3)
    d.add_argument("--aspect", default="landscape")
    d.add_argument("--no-post", action="store_true", help="skip the Discord choice (testing)")
    d.add_argument("--live", action="store_true", help="enqueue jobs that are NOT dry runs")
    d.add_argument("--json", action="store_true")

    c = sub.add_parser("collect")
    c.add_argument("--no-apply", action="store_true")
    c.add_argument("--json", action="store_true")

    sub.add_parser("status")
    args = ap.parse_args()

    if args.action == "status":
        print(json.dumps(status(), indent=2))
        return 0

    if args.action == "collect":
        out = collect(apply_selection=not args.no_apply)
        if args.json:
            print(json.dumps(out, indent=2))
        else:
            for r in out["results"]:
                print(f"  {r['surface']:22} {r['status']:28} choice={r.get('choice')} "
                      f"actor={r.get('actor')}")
            print(f"applied: {out['applied']} of {out['checked']}")
        return 0

    # draft
    if args.all:
        surfaces = load_surfaces()
        targets = [k for k, v in surfaces.items() if v.get("posting_method") == "phone"]
        texts: dict[str, str] = {}
        if args.text_file:
            raw = json.loads(Path(args.text_file).read_text())
            texts = raw if isinstance(raw, dict) else {r["surface"]: r["text"] for r in raw}
    else:
        if not args.surface:
            raise SystemExit("--surface is required unless --all is given")
        targets = [args.surface]
        if args.text_file:
            raw = json.loads(Path(args.text_file).read_text())
            texts = raw if isinstance(raw, dict) else {r["surface"]: r["text"] for r in raw}
        else:
            texts = {args.surface: args.text or ""}

    missing = [s for s in targets if not (texts.get(s) or "").strip()]
    if missing:
        # Refuse rather than draft an image for an empty post: an image generated for no
        # copy is wasted spend and a confusing card in the channel.
        raise SystemExit(f"no text supplied for surface(s): {missing}")

    out = []
    for s in targets:
        out.append(draft_one(s, texts[s], tier=args.tier, variants=args.variants,
                             post_choice=not args.no_post, live=args.live,
                             aspect=args.aspect))
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        for r in out:
            if r.get("ok"):
                ch = r.get("choice") or {}
                print(f"  {r['surface']:22} job={r['job_id']} {r['ok_count']} variants "
                      f"tier={r['tier']} dry_run={r['dry_run']} "
                      f"choice_msg={ch.get('message_id')}")
            else:
                print(f"  {r['surface']:22} FAILED: {r['error']}")
    return 0 if all(r.get("ok") for r in out) else 1


if __name__ == "__main__":
    raise SystemExit(main())
