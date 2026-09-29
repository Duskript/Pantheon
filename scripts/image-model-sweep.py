#!/usr/bin/env python3
"""Generate one example image from EVERY model in the managed image catalogue.

One identical prompt across every model, so the results are comparable rather than
26 unrelated pictures. Writes a manifest so the contact sheet can label them.

Usage: image-model-sweep.py [--aspect landscape|square|portrait] [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, "/home/konan/.hermes/hermes-agent")

from tools.image_generation_catalog import FAL_MODELS  # noqa: E402
from tools.image_generation_tool import (  # noqa: E402
    _load_fal_client,
    _prepare_fal_request,
    _submit_fal_request,
    _wait_fal_result,
)

# One prompt for every model. Deliberately a real marketing-usable scene (Konan's
# business-systems content) rather than a generic test pattern, so the comparison
# answers "which of these would I actually ship?" and not just "does it work?".
PROMPT = (
    "A small business owner at a tidy desk reviewing paperwork, warm morning light "
    "through a window, shallow depth of field, professional editorial photography, "
    "muted blue and amber tones, no text, no watermark"
)


def _require_fal_environment() -> None:
    """Fail fast and actionably when run from the wrong interpreter.

    The `fal` extra is only importable from Hermes' COMMITTED GENERATION venv, not the
    base install venv at /usr/local/lib/hermes-agent/venv. Hermes refuses a lazy install
    from any other interpreter ("lazy installs are disabled"), which surfaces as an
    ImportError deep inside the tool.

    Without this guard the sweep catches that per-model, marks all 25 models failed, and
    exits reporting "0/25 rendered" - which reads like a catalogue problem when it is
    purely an environment problem. Measured 2026-09-26: the first sweep returned 0 images
    for exactly this reason and cost a full run to diagnose.
    """
    try:
        import fal_client  # noqa: F401
        return
    except ImportError:
        pass

    try:
        sys.path.insert(0, "/home/konan/.hermes/hermes-agent")
        from pm.environments import selected_venv
        venv = selected_venv(Path("/home/konan/.hermes/hermes-agent"))
        good = venv / "bin" / "python3"
    except Exception:  # noqa: BLE001 - the guard must still speak plainly if pm is unavailable
        good = None

    print("REFUSING TO SWEEP: the 'fal' extra is not importable from this interpreter.")
    print(f"  running: {sys.executable}")
    if good is not None and good.exists():
        print(f"  correct: {good}")
        print(f"\nRe-run as:\n  {good} {Path(__file__).resolve()} --aspect landscape")
    else:
        print("  could not resolve the committed generation venv via pm.environments.")
    print("\nThe fal extra lives in Hermes' committed generation venv (Python 3.14), not the")
    print("base install venv. Every model would otherwise fail and report 0 rendered.")
    raise SystemExit(2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aspect", default="landscape", choices=["landscape", "square", "portrait"])
    ap.add_argument("--out", default="/home/konan/pantheon/phone-queue/image-model-sweep")
    args = ap.parse_args()

    _require_fal_environment()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    _load_fal_client()

    models = list(FAL_MODELS.items())
    print(f"sweeping {len(models)} models, aspect={args.aspect}")
    print(f"prompt: {PROMPT[:70]}...\n")

    manifest = []
    for i, (model_id, meta) in enumerate(models, 1):
        display = meta.get("display", model_id)
        row = {"model": model_id, "display": display, "price": meta.get("price", ""),
               "ok": False, "error": None, "file": None, "url": None, "seconds": None}
        t0 = time.time()
        try:
            endpoint, arguments = _prepare_fal_request(
                model_id, meta, PROMPT, args.aspect, None, {}, [])
            handler = _submit_fal_request(endpoint, arguments)
            result = _wait_fal_result(handler)
            images = (result or {}).get("images") or []
            if not images:
                raise RuntimeError(f"no images in response: {str(result)[:200]}")
            url = images[0].get("url")
            if not url:
                raise RuntimeError(f"image entry has no url: {str(images[0])[:200]}")
            safe = model_id.replace("/", "__")
            dest = out / f"{safe}.png"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                dest.write_bytes(r.read())
            row.update(ok=True, file=str(dest), url=url)
            print(f"[{i:2}/{len(models)}] OK   {display:34} {dest.stat().st_size/1e6:5.2f}MB  {time.time()-t0:5.1f}s")
        except Exception as exc:  # noqa: BLE001 - one bad model must not stop the sweep
            row["error"] = f"{type(exc).__name__}: {exc}"[:300]
            print(f"[{i:2}/{len(models)}] FAIL {display:34} {row['error'][:90]}")
        row["seconds"] = round(time.time() - t0, 1)
        manifest.append(row)

    mf = out / "manifest.json"
    mf.write_text(json.dumps(manifest, indent=2))
    ok = [r for r in manifest if r["ok"]]
    print(f"\n=== {len(ok)}/{len(manifest)} models produced an image ===")
    print(f"manifest: {mf}")
    for r in manifest:
        if not r["ok"]:
            print(f"  FAILED {r['display']}: {r['error'][:110]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
