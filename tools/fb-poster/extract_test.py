"""Refined extractor: only real /<user>/posts/ or /groups/<id>/posts/ URLs."""
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
        original_url = target.url
        test_url = "https://www.facebook.com/search/posts/?q=looking%20for%20Pocatello%20Business%3A%20Support%20Local%2FStay%20Local!"
        await target.goto(test_url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(3)
        for tick in range(3):
            await target.evaluate("() => window.scrollBy(0, window.innerHeight * 0.8)")
            await asyncio.sleep(2)
        posts = await target.evaluate(r"""
            () => {
                const items = [];
                const seen = new Set();
                const allLinks = document.querySelectorAll('a[href]');
                // Real post patterns:
                //   /<user-slug>/posts/<post-id>
                //   /groups/<group-id>/posts/<post-id>
                // Junk to exclude:
                //   /search/posts/...
                //   Anything with __cft__ (internal tracking)
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
                            if (p.innerText && p.innerText.length > 80) {
                                container = p;
                                break;
                            }
                            p = p.parentElement;
                        }
                    }
                    let text = container ? (container.innerText || '').substring(0, 800) : '';
                    text = text.replace(/\s+/g, ' ').trim();
                    items.push({ href, text });
                });
                return items;
            }
        """)
        print(f"Extracted {len(posts)} REAL posts:")
        for i, post in enumerate(posts[:8]):
            print(f"  [{i}] {post['href'][:120]}")
            print(f"      Text: {post['text'][:250]}")
            print()
        await target.goto(original_url, wait_until="domcontentloaded", timeout=10000)
        await browser.close()


asyncio.run(main())
