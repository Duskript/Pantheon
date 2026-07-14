"""Batch 1 scrape — fixed to reuse an existing Vivaldi tab.

The previous version failed because new_page() on a long-running remote
Chromium is unreliable. This version hijacks an existing non-essential tab,
navigates to the search URL, scrapes, then restores the tab to its original
URL when done (so browser state is preserved).
"""
import asyncio
import csv
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/home/konan/pantheon/tools/fb-poster")
from scrape_groups import (
    search_group_for_phrase,
    human_pause,
    GROUPS,
    PHRASES,
    OUT_CSV,
    dismiss_human_wall,
)

BATCH = GROUPS[:6]


async def run():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        ctx = browser.contexts[0]
        target = None
        for page in ctx.pages:
            if "chrome-extension" not in page.url and "facebook.com" not in page.url:
                target = page
                break
        if target is None:
            print("[batch1] No safe tab to hijack — aborting.")
            await browser.close()
            return
        original_url = target.url
        original_title = await target.title()
        print(f"[batch1] Hijacked tab: '{original_title[:50]}' | {original_url[:80]}")
        print(f"[batch1] Starting at {datetime.now().isoformat()}")
        print(f"[batch1] Groups in this batch: {BATCH}")
        all_results = []
        for group in BATCH:
            print(f"\n[batch1] === Group: {group} ===")
            for phrase in PHRASES:
                print(f"[batch1]   Phrase: {phrase!r}")
                try:
                    await search_group_for_phrase(target, group, phrase, all_results)
                except Exception as e:
                    print(f"[batch1]   ERR during search: {e}")
                    if await dismiss_human_wall(target):
                        input("[batch1] Press Enter after resolving the wall...")
                await human_pause(4, 9)
            await human_pause(8, 18)
        seen = set()
        deduped = []
        for r in all_results:
            if r["post_url"] not in seen:
                seen.add(r["post_url"])
                deduped.append(r)
        with open(OUT_CSV, "w", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["group", "phrase", "post_url", "post_text", "scraped_at"]
            )
            writer.writeheader()
            writer.writerows(deduped)
        print(f"\n[batch1] Done. {len(deduped)} unique matches written to {OUT_CSV}")
        try:
            await target.goto(original_url, wait_until="domcontentloaded", timeout=10000)
            print(f"[batch1] Tab restored to original URL.")
        except Exception as e:
            print(f"[batch1] Could not restore tab: {e}")
        await browser.close()


asyncio.run(run())
