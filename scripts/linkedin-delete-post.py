#!/usr/bin/env python3
"""Delete a post from the TheoForge LinkedIn Company Page.

Irreversible and public, so this captures evidence at every step and refuses
rather than guessing. Locates the target post by a text fragment, finds the
"Post options" control that belongs to THAT post (the one immediately above its
text, not a neighbouring post's), opens it, and reports the menu it finds.

Usage:
  linkedin-delete-post.py --find "Draft's done" [--execute]

Without --execute it only opens the options menu and prints it (dry run).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/home/konan/projects/consignment-dashboard/phone-bridge")
import phone_social_publisher as psp  # noqa: E402

SERIAL = "21251FDF60016K"
PLATFORM = "business linkedin"
OUT = Path("/home/konan/pantheon/phone-queue/linkedin-delete-post")


def _centre(bounds: str):
    c = psp._bounds_center(bounds or "")
    return c


def _top(bounds: str) -> int:
    try:
        return int(bounds.strip("[]").split("][")[0].split(",")[1])
    except Exception:
        return 10 ** 9


def find_post_options(st: dict, fragment: str):
    """Return the 'Post options' node belonging to the post whose text contains
    `fragment`, or None. Ownership is decided by vertical position: the control
    sits immediately ABOVE the post's body text."""
    target = None
    for n in st["nodes"]:
        lab = psp._node_text(n).lower()
        if fragment.lower() in lab:
            target = n
            break
    if target is None:
        return None, None
    ty = _top(target.get("bounds", ""))
    best, best_dy = None, 10 ** 9
    for n in st["nodes"]:
        if "post options" not in psp._node_label(n).lower():
            continue
        oy = _top(n.get("bounds", ""))
        dy = ty - oy
        # the control is above the text and close to it
        if 0 < dy < 700 and dy < best_dy:
            best, best_dy = n, dy
    return best, target


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--find", required=True)
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    psp._pin_serial(SERIAL)
    pkg = psp.platform_package(PLATFORM)
    psp._force_stop(pkg)
    time.sleep(1.5)
    d = psp.connect_device(SERIAL)
    psp._wake(d)
    psp._launch_app(pkg)
    time.sleep(7)

    steps: list = []
    nav = psp._open_linkedin_page_profile(d, OUT, steps)
    print("nav:", nav.get("ok"), nav.get("status"))
    if not nav.get("ok"):
        return 2

    found = None
    for i in range(6):
        st = psp._capture_state(d, OUT, f"find-{i}")
        opt, tgt = find_post_options(st, args.find)
        if opt is not None:
            found = (opt, tgt)
            print(f"  located on screen {i}: target text={psp._node_text(tgt)[:60]!r}")
            print(f"  its Post options bounds={opt.get('bounds')} -> centre={_centre(opt.get('bounds'))}")
            break
        psp.adb("shell", "input", "swipe", "540", "1800", "540", "900", "450", timeout=10)
        time.sleep(1.5)

    if found is None:
        print("REFUSING: could not locate the target post on the Page-posts view.")
        return 3

    opt, tgt = found
    c = _centre(opt.get("bounds"))
    if c is None:
        print("REFUSING: no usable bounds for the Post options control.")
        return 4
    if c[1] > 2400 - 160:
        psp.adb("shell", "input", "swipe", "540", "1700", "540", "1250", "400", timeout=10)
        time.sleep(1.5)
        st = psp._capture_state(d, OUT, "after-raise")
        opt, tgt = find_post_options(st, args.find)
        if opt is None:
            print("REFUSING: lost the control while raising it off the bottom edge.")
            return 5
        c = _centre(opt.get("bounds"))
    print(f"tapping Post options at {c}")
    psp.adb("shell", "input", "tap", str(c[0]), str(c[1]), timeout=10)
    time.sleep(3)

    menu = psp._capture_state(d, OUT, "options-menu")
    print("--- options menu ---")
    for n in menu["nodes"]:
        lab = psp._node_label(n)
        if lab:
            print(f"    {lab[:70]:70} [{n.get('class','').split('.')[-1]:12} clk={n.get('clickable')} b={n.get('bounds')}]")

    if not args.execute:
        print("\nDRY RUN: stopping before deleting anything. Re-run with --execute.")
        return 0

    # --- destructive step -------------------------------------------------
    del_row = psp._find_visible_node(menu["nodes"], text="Delete post")
    if del_row is None:
        print("REFUSING: no 'Delete post' entry in the menu.")
        return 6
    c = _centre(del_row.get("bounds"))
    print(f"tapping 'Delete post' at {c}")
    psp.adb("shell", "input", "tap", str(c[0]), str(c[1]), timeout=10)
    time.sleep(3)

    # A confirmation dialog is expected. Only ever tap a control whose TEXT is
    # exactly "Delete" - never "Delete post" again (that would re-open the menu)
    # and never anything ambiguous.
    st = psp._capture_state(d, OUT, "confirm-dialog")
    print("--- confirmation dialog ---")
    for n in st["nodes"]:
        lab = psp._node_label(n)
        if lab:
            print(f"    {lab[:70]:70} [{n.get('class','').split('.')[-1]:12} clk={n.get('clickable')} b={n.get('bounds')}]")

    confirm = None
    for n in st["nodes"]:
        if psp._node_text(n).strip().lower() == "delete":
            confirm = n
            break
    if confirm is None:
        print("REFUSING: no exact 'Delete' confirm control found; nothing was deleted.")
        return 7
    c = _centre(confirm.get("bounds"))
    print(f"confirming deletion at {c}")
    psp.adb("shell", "input", "tap", str(c[0]), str(c[1]), timeout=10)
    time.sleep(5)

    after = psp._capture_state(d, OUT, "after-delete")
    still = any(args.find.lower() in psp._node_text(n).lower() for n in after["nodes"])
    print("post text still on this screen?", still)
    return 0 if not still else 8


if __name__ == "__main__":
    raise SystemExit(main())
