#!/usr/bin/env python3
"""
fb-poster — Post to Facebook (personal timeline, Page, or group) via a
patched Firefox (invisible-playwright) exiting through CachyOS as a
residential SOCKS5 proxy.

Usage:
    post.py --login                       # one-time login, persists cookies
    post.py "Hello from a real human"     # post to personal timeline
    post.py --group "Pocatello Business" "Hey locals"
    post.py --page "Theoforge" "New demo out"
    post.py --check-ip                    # verify exit IP
    post.py --dry-run "text"              # walk the flow without posting
"""
import argparse
import random
import sys
import time
from pathlib import Path

import yaml
from invisible_playwright import InvisiblePlaywright

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.yaml"
PROFILE_DIR = ROOT / "profiles" / "default"
LOGS_DIR = ROOT / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Selectors Facebook has used for the composer / post button. We try
# each in order — they break every few weeks, the rotating list buys
# time without a code change.
COMPOSER_SELECTORS = [
    '[aria-label="Create a post"]',
    '[aria-label="Write something..."]',
    'div[contenteditable="true"][role="textbox"]',
    'div.notranslate[contenteditable="true"]',
]
POST_BUTTON_SELECTORS = [
    '[aria-label="Post"]:not([disabled])',
    'div[aria-label="Post"][role="button"]:not([aria-disabled="true"])',
    'span:has-text("Post") >> .. >> [role="button"]:not([aria-disabled="true"])',
]


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        sys.exit(f"missing config: {CONFIG_PATH}")
    return yaml.safe_load(CONFIG_PATH.read_text())


def jitter(min_s: float, max_s: float) -> None:
    time.sleep(random.uniform(min_s, max_s))


def human_typing(page, selector: str, text: str) -> None:
    """Type one char at a time with human-like jitter so the keystroke
    pattern doesn't look like a paste/fill."""
    el = page.locator(selector).first
    el.click()
    jitter(0.4, 1.1)
    for ch in text:
        page.keyboard.type(ch, delay=random.randint(40, 140))
        if random.random() < 0.04:
            jitter(0.2, 0.6)


def find_and_click(page, selectors: list[str], label: str) -> bool:
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            if loc.count() and loc.is_visible():
                loc.click()
                print(f"  ✓ clicked {label} via {sel}")
                return True
        except Exception:
            continue
    print(f"  ✗ could not find {label}")
    return False


def open_target(page, target: str, kind: str) -> None:
    if kind == "timeline":
        page.goto("https://www.facebook.com/")
    elif kind == "group":
        page.goto(f"https://www.facebook.com/groups/{target}/")
    elif kind == "page":
        page.goto(f"https://www.facebook.com/{target}/")
    else:
        sys.exit(f"unknown target kind: {kind}")
    page.wait_for_load_state("domcontentloaded")
    jitter(2.5, 4.5)


def do_login(page) -> None:
    print("→ login flow — log in manually in the Firefox window")
    page.goto("https://www.facebook.com/login")
    page.wait_for_load_state("domcontentloaded")
    # Wait for the user to land on the home feed (cookies set).
    print("  waiting for login to complete (you'll see the feed)...")
    try:
        page.wait_for_url("**/facebook.com/**", timeout=300_000)
        # crude check: presence of the home nav
        page.wait_for_selector('[aria-label="Home"]', timeout=60_000)
    except Exception as e:
        sys.exit(f"login wait failed: {e}")
    print("  ✓ logged in — cookies will persist for next run")


def check_ip(page) -> None:
    page.goto("https://api.ipify.org?format=json")
    page.wait_for_load_state("networkidle")
    body = page.locator("body").inner_text()
    print(f"  exit IP: {body}")
    page.goto("https://ipinfo.io/json")
    page.wait_for_load_state("networkidle")
    print(f"  geo:     {page.locator('body').inner_text()}")


def post_text(page, text: str, dry_run: bool) -> None:
    print("→ opening composer")
    if not find_and_click(page, COMPOSER_SELECTORS, "composer"):
        sys.exit("could not open the post composer — Facebook changed the UI again")
    jitter(1.2, 2.4)

    print(f"→ typing {len(text)} chars")
    # After clicking the composer, focus is on a contenteditable div
    human_typing(page, 'div[contenteditable="true"]', text)
    jitter(1.5, 3.0)

    if dry_run:
        print("→ DRY RUN — not clicking Post")
        return

    print("→ clicking Post")
    if not find_and_click(page, POST_BUTTON_SELECTORS, "Post button"):
        sys.exit("could not find the Post button")
    jitter(3.5, 6.0)
    print("  ✓ post submitted (verify in your feed)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", help="post body (quoted string)")
    ap.add_argument("--group", help="group slug or name fragment")
    ap.add_argument("--page", help="Page username/slug")
    ap.add_argument("--login", action="store_true", help="interactive login + save cookies")
    ap.add_argument("--check-ip", action="store_true", help="print exit IP and geo only")
    ap.add_argument("--dry-run", action="store_true", help="type but do not post")
    ap.add_argument("--seed", type=int, default=42, help="fingerprint seed (default 42)")
    ap.add_argument("--headless", action="store_true", help="run Firefox headless (default off; turn on for CI/TUI)")
    args = ap.parse_args()

    cfg = load_config()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    # Build proxy dict from config
    proxy_cfg = cfg.get("proxy", {})
    proxy = None
    if proxy_cfg.get("enabled", False):
        proxy = {
            "server": proxy_cfg["server"],
            "username": proxy_cfg.get("username"),
            "password": proxy_cfg.get("password"),
        }

    # Note: post.sh already ensures the SOCKS5 tunnel is up before
    # invoking this script. If you call post.py directly, run
    # bin/tunnel.sh first.

    kwargs = dict(
        seed=args.seed,
        timezone=cfg.get("timezone", "America/Boise"),
        headless=args.headless,
        # Running in a TUI / container without unprivileged user
        # namespaces — Firefox's sandbox refuses to start otherwise.
        # These flags are standard for headless Firefox in CI.
        extra_args=["-no-sandbox", "-disable-dev-shm-usage"],
    )
    if proxy:
        kwargs["proxy"] = proxy

    with InvisiblePlaywright(**kwargs) as browser:
        # Reuse the on-disk profile so cookies / fingerprint stay
        # consistent across runs.
        context = browser.new_context(storage_state=str(PROFILE_DIR / "state.json") if (PROFILE_DIR / "state.json").exists() else None)
        page = context.new_page()

        if args.check_ip:
            check_ip(page)
            return 0

        if args.login:
            do_login(page)
            context.storage_state(path=str(PROFILE_DIR / "state.json"))
            print(f"  saved state → {PROFILE_DIR / 'state.json'}")
            return 0

        if not args.text:
            ap.error("provide post text, or use --login / --check-ip")

        # Decide target
        if args.group:
            kind, target = "group", args.group
        elif args.page:
            kind, target = "page", args.page
        else:
            kind, target = "timeline", None

        open_target(page, target, kind)
        post_text(page, args.text, args.dry_run)

        # Always save storage state so login sticks
        try:
            context.storage_state(path=str(PROFILE_DIR / "state.json"))
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
