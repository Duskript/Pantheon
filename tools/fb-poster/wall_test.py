"""Test the wall detection on a real Facebook search page.

We hijack a tab, navigate to a real Facebook search URL, and check whether
the wall detector (a) correctly returns False for normal search results,
(b) extracts post URLs successfully.
"""
import asyncio
import sys
sys.path.insert(0, "/home/konan/pantheon/tools/fb-poster")
from scrape_groups import dismiss_human_wall


async def main():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        ctx = browser.contexts[0]
        target = None
        for page in ctx.pages:
            if "chrome-extension" not in page.url and "facebook.com" not in page.url:
                target = page
                break
        if not target:
            print("No tab to hijack")
            await browser.close()
            return
        original_url = target.url
        # Navigate to a real Facebook group search
        test_url = "https://www.facebook.com/search/posts/?q=looking%20for%20Pocatello%20Business%3A%20Support%20Local%2FStay%20Local!"
        print(f"Test URL: {test_url}")
        await target.goto(test_url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(3)
        # Check wall
        is_wall = await dismiss_human_wall(target)
        print(f"Wall detection result: {is_wall} (should be False for normal search)")
        # Now try the extraction
        posts = await target.evaluate("""
            () => {
                const items = [];
                const links = document.querySelectorAll('a[href*="/posts/"], a[href*="/permalink/"]');
                const seen = new Set();
                links.forEach(a => {
                    const href = a.getAttribute('href');
                    if (!href || seen.has(href)) return;
                    seen.add(href);
                    let container = a.closest('[role="article"]') || a.closest('div');
                    let text = container ? (container.innerText || '').substring(0, 400) : '';
                    items.push({ href, text: text.replace(/\\n+/g, ' ').trim() });
                });
                return items;
            }
        """)
        print(f"\nExtracted {len(posts)} posts:")
        for i, post in enumerate(posts[:5]):
            print(f"  [{i}] {post['href'][:80]}")
            print(f"      Text: {post['text'][:200]}")
        # Restore
        await target.goto(original_url, wait_until="domcontentloaded", timeout=10000)
        print("\nTab restored.")
        await browser.close()


asyncio.run(main())
