#!/usr/bin/env python3
"""Content-pipeline image step: generate post image variants in two cost tiers.

WHERE THIS SITS
---------------
Between "copy approved" and "publish". A post needs image variants, one of which is
selected and handed to the phone publisher as `media_paths`. This module produces
those variants and records them against the job in the shape the queue already
understands (`variant_index`, `variant_label`, `selected_image_path`).

TWO TIERS
---------
`draft` - Z-Image Turbo, ~4s, $0.005/MP. This is the default: three variants of one
          prompt for pennies, fast enough that a 5-surface daily run is under a minute
          of generation time.
`hero`  - Nano Banana Pro, ~19s, $0.15/image. For a post that has earned it.
`text`  - Ideogram V4 Fast, ~11s. For images that must CONTAIN legible words.

TEXT IS THE TRAP (measured 2026-09-26)
--------------------------------------
The first run of this module produced images with GARBLED NONSENSE LETTERFORMS where
documents were. The prompt said "reviewing paperwork" and "no text", and the models
rendered simulated text anyway.

What was tested, and what actually worked:

  prompt asked for documents, no suppression      -> 2 of 3 variants garbled
  prompt asked for documents + suppression suffix -> 2 of 3 variants STILL garbled
  documents/screens removed from the scene        -> 3 of 3 clean
  real headline via Ideogram                      -> legible, correctly spelled

So the prop is the cause and the suffix is only a partial mitigation. `lint_prompt()`
warns when a prompt contains a text-inviting prop, so the caller learns this BEFORE
spending. If the image is meant to contain readable words, use a `text` tier - the photo
models cannot spell.

The tier is a parameter, not a config edit, so a single run can draft every surface
and promote one post to hero without touching config.yaml.

WHY VARIANT MODIFIERS
---------------------
Three generations of one prompt with three seeds gives three compositions of the SAME
idea. For marketing that is often not what you want - you want genuinely different
treatments to choose between. So each variant gets a distinct seed AND a distinct
composition modifier ("wide establishing shot" / "close-up detail" / "overhead
flat-lay"). Pass `modifiers=[]` to fall back to seed-only variation.

ENVIRONMENT
-----------
The `fal` extra only imports from Hermes' COMMITTED GENERATION venv, not the base
install venv. Unattended runs cannot be expected to know that, so this module
re-execs itself onto the correct interpreter automatically rather than failing.

Usage
-----
    content-image-step.py --prompt "..." [--variants 3] [--tier draft|hero]
                          [--aspect landscape|square|portrait] [--out DIR]
                          [--job PATH] [--select 0] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

HERMES_REPO = "/home/konan/.hermes/hermes-agent"

# Tier -> catalogue model id. Both verified working through the Nous managed gateway.
TIERS: dict[str, str] = {
    "draft": "fal-ai/z-image/turbo",          # ~4s,  $0.005/MP
    "draft_flux": "fal-ai/flux-2/klein/9b",   # ~6s,  $0.006/MP
    "hero": "fal-ai/nano-banana-pro",         # ~19s, $0.15/image (1K)
    # For images that must CONTAIN legible words. Ideogram is the text-rendering
    # specialist: verified spelling "GET BACK YOUR WEEK" / "TheoForge Solutions"
    # correctly in both v4-fast and v3, where the photo models produced nonsense
    # letterforms. Use this tier, not a photo model, whenever copy must be readable.
    "text": "ideogram/v4/fast",               # ~11s
    "text_instant": "ideogram/v4/instant",    # ~8s
}

# Tiers where the image is SUPPOSED to contain text - suppression is skipped for these,
# otherwise the suffix would fight the caller's own instruction.
TEXT_TIERS = frozenset({"text", "text_instant"})

# Appended to every non-text prompt. Measured 2026-09-26: a prompt saying "reviewing
# paperwork" produced documents full of garbled nonsense letterforms in 2 of 3 variants,
# because image models render any document/screen as SIMULATED text. A bare "no text"
# instruction was not enough - the fix is to forbid the props that invite it.
TEXT_SUPPRESSION = (
    "No documents, no paperwork, no screens, no monitors, no signage, no labels, "
    "no lettering, no writing, no text of any kind."
)

# Composition modifiers, one per variant. These make the three outputs genuinely
# different choices rather than three rolls of the same dice.
DEFAULT_MODIFIERS = [
    "wide establishing shot",
    "close-up detail",
    "overhead flat-lay",
]

VARIANT_LABELS = ["A", "B", "C", "D", "E", "F"]

# Deterministic seeds: same prompt + same tier reproduces the same three images,
# which makes a re-run comparable instead of a fresh lottery.
BASE_SEED = 20260926


# Props that FORCE text into the frame. Measured 2026-09-26: the suppression suffix
# alone did NOT fix gibberish - the original "reviewing paperwork" prompt still produced
# garbled letterforms in 2 of 3 variants WITH suppression active, because the scene
# contains documents and the model renders text-like marks on any document it draws.
# Removing the props produced 3 of 3 clean. So the prop is the cause; the suffix is only
# a partial mitigation, and this lint is how the caller finds out BEFORE spending.
TEXT_INVITING_PROPS: tuple[str, ...] = (
    "paperwork", "document", "documents", "form", "forms", "contract", "contracts",
    "report", "reports", "spreadsheet", "invoice", "invoices", "receipt", "receipts",
    "notebook", "clipboard", "screen", "monitor", "laptop", "computer", "tablet",
    "sign", "signage", "signboard", "label", "labels", "whiteboard", "chalkboard",
    "newspaper", "magazine", "poster", "banner", "menu", "book", "books", "chart",
)


def lint_prompt(prompt: str, tier: str = "draft") -> list[str]:
    """Warnings about prompt content that will produce unreadable text artifacts.

    Returns human-readable warnings; empty means the prompt is clear of known causes.
    """
    if tier in TEXT_TIERS:
        return []  # the image is meant to contain text; the model is a text specialist
    low = prompt.lower()
    hits = sorted({w for w in TEXT_INVITING_PROPS if w in low})
    if not hits:
        return []
    return [
        f"prompt mentions {hits} - these force documents/screens into the scene, and image "
        f"models render text-like marks on them that come out as GARBLED NONSENSE. The "
        f"text-suppression suffix only partly helps (measured: 2 of 3 variants still "
        f"garbled). Remove these props from the scene, or use a text tier "
        f"({sorted(TEXT_TIERS)}) if the image is meant to contain legible words."
    ]


def ensure_environment() -> None:
    """Re-exec onto Hermes' committed generation venv when `fal` is unavailable.

    The fal extra lives only in that venv. Refusing would be correct but useless for an
    unattended 6am run, so re-exec silently (with one line to stderr) instead.
    """
    try:
        import fal_client  # noqa: F401
        return
    except ImportError:
        pass

    sys.path.insert(0, HERMES_REPO)
    try:
        from pm.environments import selected_venv
        venv_python = selected_venv(Path(HERMES_REPO)) / "bin" / "python3"
    except Exception as exc:  # noqa: BLE001 - report and stop; never guess a path
        raise SystemExit(
            f"cannot import 'fal' and could not resolve the committed generation venv "
            f"via pm.environments ({type(exc).__name__}: {exc}). "
            f"Run this from a Hermes session or install the extra with `hermes pm install`."
        ) from exc

    if not venv_python.exists():
        raise SystemExit(f"resolved venv python does not exist: {venv_python}")

    print(f"[image-step] re-exec onto {venv_python}", file=sys.stderr)
    os.execv(str(venv_python), [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]])


def _download(url: str, dest: Path) -> int:
    """Fetch a generated image to `dest`; returns bytes written."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = resp.read()
    dest.write_bytes(data)
    return len(data)


def generate_variants(
    prompt: str,
    *,
    variants: int = 3,
    tier: str = "draft",
    aspect: str = "landscape",
    out_dir: str | Path,
    modifiers: list[str] | None = None,
    slug: str = "post",
    suppress_text: bool = True,
) -> dict[str, Any]:
    """Generate `variants` images for `prompt` and return a manifest dict.

    Never raises for a single failed variant - a partial set is still usable, and the
    caller sees exactly which variant failed and why.
    """
    if not prompt or not prompt.strip():
        raise ValueError("prompt is required and must be non-empty")
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}; expected one of {sorted(TIERS)}")
    if not 1 <= variants <= len(VARIANT_LABELS):
        raise ValueError(f"variants must be between 1 and {len(VARIANT_LABELS)}")

    mods = DEFAULT_MODIFIERS if modifiers is None else modifiers
    model_id = TIERS[tier]
    dest_dir = Path(out_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Imported here, not at module scope: these need the correct environment, which
    # ensure_environment() has already guaranteed by this point.
    sys.path.insert(0, HERMES_REPO)
    from tools.image_generation_catalog import FAL_MODELS
    from tools.image_generation_tool import (
        _load_fal_client,
        _prepare_fal_request,
        _submit_fal_request,
        _wait_fal_result,
    )

    _load_fal_client()
    meta = FAL_MODELS[model_id]

    results: list[dict[str, Any]] = []
    for i in range(variants):
        label = VARIANT_LABELS[i]
        modifier = mods[i % len(mods)] if mods else ""
        parts = [prompt.strip()]
        if modifier:
            parts.append(modifier)
        # Suppression goes last so it reads as a constraint on everything before it, and
        # is skipped for text tiers where the caller WANTS words in the image.
        if suppress_text and tier not in TEXT_TIERS:
            parts.append(TEXT_SUPPRESSION)
        full_prompt = ", ".join(parts)
        row: dict[str, Any] = {
            "variant_index": i,
            "variant_label": label,
            "modifier": modifier,
            "model": model_id,
            "tier": tier,
            "prompt": full_prompt,
            "seed": BASE_SEED + i,
            "ok": False,
            "path": None,
            "error": None,
            "seconds": None,
            "bytes": None,
        }
        t0 = time.time()
        try:
            endpoint, arguments = _prepare_fal_request(
                model_id, meta, full_prompt, aspect, row["seed"], {}, [])
            handler = _submit_fal_request(endpoint, arguments)
            payload = _wait_fal_result(handler)
            images = (payload or {}).get("images") or []
            if not images:
                raise RuntimeError(f"no images in response: {str(payload)[:180]}")
            url = images[0].get("url")
            if not url:
                raise RuntimeError(f"image entry carries no url: {str(images[0])[:180]}")
            dest = dest_dir / f"{slug}-variant-{label}.png"
            row["bytes"] = _download(url, dest)
            row.update(ok=True, path=str(dest), url=url)
        except Exception as exc:  # noqa: BLE001 - one bad variant must not kill the set
            row["error"] = f"{type(exc).__name__}: {exc}"[:300]
        row["seconds"] = round(time.time() - t0, 1)
        results.append(row)

    ok_rows = [r for r in results if r["ok"]]
    return {
        "tier": tier,
        "model": model_id,
        "aspect": aspect,
        "prompt": prompt,
        "suppress_text": bool(suppress_text and tier not in TEXT_TIERS),
        "variants": results,
        "prompt_warnings": lint_prompt(prompt, tier),
        "ok_count": len(ok_rows),
        "failed_count": len(results) - len(ok_rows),
        "total_seconds": round(sum(r["seconds"] or 0 for r in results), 1),
        "selected_image_path": None,
        "manifest_path": str(dest_dir / f"{slug}-image-manifest.json"),
    }


def attach_to_job(job_path: str | Path, manifest: dict[str, Any], select: int | None = None) -> dict[str, Any]:
    """Write the variant set into a phone-queue job so the publisher can use it.

    Sets `image_variants`, and `selected_image_path` + `media_paths` when a variant is
    chosen. Without a selection the job stays publishable-but-imageless rather than
    silently picking one.
    """
    p = Path(job_path)
    job = json.loads(p.read_text())
    payload = job.setdefault("payload", {})
    # Keep only the fields the publisher and the approval surface need; drop prompts
    # and seeds so the job file stays small and readable.
    keep = ("variant_index", "variant_label", "modifier", "model", "path", "ok")
    payload["image_variants"] = [
        {k: v.get(k) for k in keep} for v in manifest["variants"]
    ]
    payload["image_model"] = manifest["model"]
    payload["image_tier"] = manifest["tier"]

    if select is not None:
        chosen = next((v for v in manifest["variants"] if v["variant_index"] == select), None)
        if chosen is None or not chosen.get("ok"):
            raise ValueError(f"cannot select variant {select}: not present or generation failed")
        payload["selected_image_path"] = chosen["path"]
        payload["media_paths"] = [chosen["path"]]

    p.write_text(json.dumps(job, indent=2))
    return job


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate post image variants in two cost tiers.")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--variants", type=int, default=3)
    ap.add_argument("--tier", default="draft", choices=sorted(TIERS))
    ap.add_argument("--aspect", default="landscape", choices=["landscape", "square", "portrait"])
    ap.add_argument("--out", required=True, help="directory to write variants into")
    ap.add_argument("--slug", default="post")
    ap.add_argument("--job", help="phone-queue job JSON to attach the variants to")
    ap.add_argument("--select", type=int, help="variant_index to select (requires --job)")
    ap.add_argument("--seed-only", action="store_true", help="drop composition modifiers")
    ap.add_argument("--no-text-suppression", action="store_true",
                    help="allow documents/screens in the scene (re-enables gibberish risk)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    ensure_environment()

    manifest = generate_variants(
        args.prompt,
        variants=args.variants,
        tier=args.tier,
        aspect=args.aspect,
        out_dir=args.out,
        modifiers=[] if args.seed_only else None,
        slug=args.slug,
        suppress_text=not args.no_text_suppression,
    )
    Path(manifest["manifest_path"]).write_text(json.dumps(manifest, indent=2))

    if args.job:
        attach_to_job(args.job, manifest, select=args.select)

    if args.json:
        print(json.dumps(manifest, indent=2))
    else:
        for w in manifest.get("prompt_warnings") or []:
            print(f"  WARNING: {w}")
        print(f"tier={manifest['tier']} model={manifest['model']} "
              f"{manifest['ok_count']}/{len(manifest['variants'])} variants in "
              f"{manifest['total_seconds']}s")
        for v in manifest["variants"]:
            state = "OK  " if v["ok"] else "FAIL"
            print(f"  [{state}] {v['variant_label']} {v['modifier'][:28]:30} "
                  f"{(v['path'] or v['error'] or '')[:70]}")
    return 0 if manifest["ok_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
