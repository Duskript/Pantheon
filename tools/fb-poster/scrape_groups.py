"""Scrape 17 SE Idaho business groups via Vivaldi CDP for posts matching target phrases.

Uses the user's logged-in Vivaldi session (residential IP, real cookies) so Facebook
sees this as normal user activity.

Phrases: "looking for", "recommend", "need someone", "website", "spreadsheet",
"canva", "facebook", "ai", "crm", "google forms"

For each group, opens Facebook's group-scoped search with each phrase, scrapes
top results from the last 30 days, captures: post_url, group, poster, post_text,
date, matched_phrase.

Cadence: 3 batches, ~6 groups per batch, 8 min between batches. 200ms per scroll
tick, 1-3s random pauses between actions. Auto-pause on real captcha/verify wall.

Output: ~/pantheon/scratch/fb_matches_<timestamp>.csv
"""
import asyncio
import csv
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path

from playwright.async_api import Page

GROUPS = [
    # Pocatello
    "Pocatello Business: Support Local/Stay Local!",
    "any business or service pocatello,blackfoot,pocy,AF,Aberdeen",
    "Business Women of Pocatello Club Members",
    "Pocatello & Idaho Falls Business",
    # Idaho Falls
    "Idaho Falls Business Networking",
    "Idaho Falls Small Business",
    "Idaho Falls Small Businesses",
    "Idaho Falls: Promote and Support Local Business",
    "East Idaho Small Business",
    "East Idaho Small Business, Advertise, Sale Items, Job Opportunities",
    "Idaho Business Networking",
    "Idaho Business Referral And Networking Group",
    # Rexburg
    "Rexburg Business Networking",
    "Rexburg Area Business Owners",
    "Rexburg Business Networkers - Members",
    "Rexburg Area Vendors and Small Businesses",
    "Businesses of Rexburg",
]

PHRASES = [
    "looking for",
    "recommend",
    "need someone",
    "website",
    "spreadsheet",
    "canva",
    "facebook",
    "ai",
    "crm",
    "google forms",
]

DAYS_BACK = 30
CUTOFF = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)

OUT_DIR = Path("/home/konan/pantheon/scratch")
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_CSV = OUT_DIR / f"fb_matches_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

# Cadence controls
SCROLL_PAUSE_MIN = 1.0
SCROLL_PAUSE_MAX = 3.0
BETWEEN_PHRASES_PAUSE = (4, 9)
BETWEEN_GROUPS_PAUSE = (8, 18)
BETWEEN_BATCHES_PAUSE = 480  # 8 minutes


def chunk(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


async def human_pause(lo, hi):
    await asyncio.sleep(random.uniform(lo, hi))


EXTRACT_POSTS_JS = r"""
() => {
    const items = [];
    const seen = new Set();
    const allLinks = document.querySelectorAll('a[href]');
    const realPostRegex = /^https?:\/\/(www\.)?facebook\.com\/[A-Za-z0-9._-]+\/posts\/(pfbid|[A-Za-z0-9_-]{8,})/;
    const groupPostRegex = /^https?:\/\/(www\.)?facebook\.com\/groups\/[0-9]+\/posts\//;
    allLinks.forEach(a => {
        const href = a.getAttribute('href') || '';
        if (!href || seen.has(href)) return;
        if (href.includes('/search/')) return;
        if (href.includes('__cft__')) return;
        if (href.includes('__tn__')) return;
        const isReal = realPostRegex.test(href);
        const isGroupPost = groupPostRegex.test(href);
        if (!isReal && !isGroupPost) return;
        seen.add(href);
        let container = a.closest('[role="article"]');
        if (!container) {
            let p = a.parentElement;
            for (let i = 0; i < 5 && p; i++) {
                if (p.innerText && p.innerText.length > 80) { container = p; break; }
                p = p.parentElement;
            }
        }
        let text = container ? (container.innerText || '').substring(0, 800) : '';
        text = text.replace(/\s+/g, ' ').trim();
        items.push({ href, text });
    });
    return items;
}
"""


async def is_real_wall(page: Page) -> bool:
    """Check for actual captcha/verify wall. Stops false-positive on normal pages."""
    url = page.url.lower()
    wall_url_signals = [
        "checkpoint" in url,
        "captcha" in url,
        ("/login/" in url and "search" not in url),
    ]
    if any(wall_url_signals):
        return True
    wall_ui_signals = await page.evaluate("""
        () => {
            const lower = (document.body.innerText || '').toLowerCase();
            return [
                lower.includes('enter the characters you see below'),
                lower.includes('please complete the security check'),
                lower.includes('your account has been locked'),
                lower.includes('we noticed unusual activity on your account'),
                lower.includes('confirm your identity to continue'),
                lower.includes('please solve this captcha'),
            ].some(Boolean);
        }
    """)
    return bool(wall_ui_signals)


async def search_group_for_phrase(page: Page, group_name: str, phrase: str, results: list):
    query = f"{phrase} {group_name}"
    search_url = f"https://www.facebook.com/search/posts/?q={query}"
    try:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
    except Exception as e:
        print(f"    [goto fail] {search_url}: {e}")
        return
    await human_pause(1.5, 3.0)
    if await is_real_wall(page):
        print(f"  ! REAL WALL DETECTED: {page.url}")
        print(f"    PAUSING — complete the challenge in Vivaldi, then press Enter.")
        input()
        return
    # Scroll a few times
    for _ in range(4):
        await page.evaluate("() => window.scrollBy(0, window.innerHeight * 0.8)")
        await human_pause(SCROLL_PAUSE_MIN, SCROLL_PAUSE_MAX)
    if await is_real_wall(page):
        return
    posts = await page.evaluate(EXTRACT_POSTS_JS)
    print(f"    [{phrase!r}] extracted {len(posts)} real posts")
    for p in posts[:8]:
        results.append({
            "group": group_name,
            "phrase": phrase,
            "post_url": p["href"],
            "post_text": p["text"][:600],
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        })


async def run_batch(browser, batch: list, batch_idx: int, total_batches: int) -> list:
    ctx = browser.contexts[0]
    # Hijack a safe tab
    target = None
    for page in ctx.pages:
        if "chrome-extension" not in page.url and "facebook.com" not in page.url:
            target = page
            break
    if target is None:
        print(f"[batch {batch_idx + 1}] No safe tab to hijack.")
        return []
    original_url = target.url
    print(f"\n[batch {batch_idx + 1}/{total_batches}] Hijacked: {original_url[:80]}")
    print(f"[batch {batch_idx + 1}/{total_batches}] Starting at {datetime.now().isoformat()}")
    results = []
    for group in batch:
        print(f"\n[batch {batch_idx + 1}] Group: {group}")
        for phrase in PHRASES:
            print(f"  phrase: {phrase!r}")
            try:
                await search_group_for_phrase(target, group, phrase, results)
            except Exception as e:
                print(f"  ERR: {e}")
            await human_pause(*BETWEEN_PHRASES_PAUSE)
        await human_pause(*BETWEEN_GROUPS_PAUSE)
    # Restore tab
    try:
        await target.goto(original_url, wait_until="domcontentloaded", timeout=10000)
    except Exception:
        pass
    return results


def main():
    import sys
    async def amain():
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://localhost:9222")
            # If specific batch given via argv, run only that one
            if len(sys.argv) > 1 and sys.argv[1] == "batch1":
                batches = list(chunk(GROUPS, 6))
                results = await run_batch(browser, batches[0], 0, len(batches))
            else:
                results = []
                batches = list(chunk(GROUPS, 6))
                for idx, batch in enumerate(batches):
                    batch_results = await run_batch(browser, batch, idx, len(batches))
                    results.extend(batch_results)
                    if idx < len(batches) - 1:
                        print(f"\n  Sleeping {BETWEEN_BATCHES_PAUSE // 60} min between batches...")
                        await asyncio.sleep(BETWEEN_BATCHES_PAUSE)
            # Dedup
            seen = set()
            deduped = []
            for r in results:
                if r["post_url"] not in seen:
                    seen.add(r["post_url"])
                    deduped.append(r)
            with open(OUT_CSV, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["group", "phrase", "post_url", "post_text", "scraped_at"])
                writer.writeheader()
                writer.writerows(deduped)
            print(f"\nDone. {len(deduped)} unique matches → {OUT_CSV}")
            await browser.close()
    asyncio.run(amain())


if __name__ == "__main__":
    main()
