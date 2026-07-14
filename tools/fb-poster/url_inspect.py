"""Inspect actual post URL structure on a real Facebook search results page."""
import asyncio


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
        test_url = "https://www.facebook.com/search/posts/?q=looking%20for%20Pocatello%20Business%3A%20Support%20Local%2FStay%20Local!"
        await target.goto(test_url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(3)
        urls = await target.evaluate(r"""
            () => {
                const out = {};
                const all = document.querySelectorAll('a[href]');
                const sample = [];
                const postLike = [];
                const searchLike = [];
                for (const a of all) {
                    const href = a.getAttribute('href') || '';
                    if (!href) continue;
                    if (href.includes('/posts/')) {
                        if (postLike.length < 10) postLike.push(href);
                    } else if (href.includes('/search/')) {
                        if (searchLike.length < 5) searchLike.push(href);
                    } else if (href.length < 200 && href.length > 5) {
                        if (sample.length < 30) sample.push(href);
                    }
                }
                out.postLike = postLike;
                out.searchLike = searchLike;
                out.otherSample = sample;
                return out;
            }
        """)
        print("=== URLs with /posts/ ===")
        for u in urls.get("postLike", []):
            print(f"  {u[:150]}")
        print("\n=== URLs with /search/ ===")
        for u in urls.get("searchLike", []):
            print(f"  {u[:150]}")
        print("\n=== Other sampled URLs ===")
        for u in urls.get("otherSample", []):
            print(f"  {u[:150]}")
        await target.goto(original_url, wait_until="domcontentloaded", timeout=10000)
        await browser.close()


asyncio.run(main())
