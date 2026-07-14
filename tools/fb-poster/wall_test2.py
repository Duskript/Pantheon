"""Tighter post extraction: only real permalink URLs."""
import asyncio
import re
import sys
sys.path.insert(0, "/home/konan/pantheon/tools/fb-poster")


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
        test_url = "https://www.facebook.com/search/posts/?q=recommend%20Idaho%20Falls%20Business%20Networking"
        print(f"Test URL: {test_url}")
        await target.goto(test_url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(3)
        for tick in range(3):
            await target.evaluate("() => window.scrollBy(0, window.innerHeight * 0.8)")
            await asyncio.sleep(2)
        posts = await target.evaluate(r"""
            () => {
                const items = [];
                // Real post permalinks look like:
                //   /<user-slug>/posts/pfbid...   (profile post)
                //   /groups/<group-id>/posts/<post-id>   (group post)
                // Search results page itself uses /search/posts/ which we exclude.
                const allLinks = document.querySelectorAll('a[href]');
                const seen = new Set();
                // Regex: must contain /posts/ and NOT be a /search/ link
                const postRegex = /\/posts\/(pfbid|\d+|[A-Za-z0-9_-]{8,})/;
                const profilePostRegex = /^\/[A-Za-z0-9._-]+\/posts\//;
                const groupPostRegex = /^\/groups\/[0-9]+\/posts\//;
                allLinks.forEach(a => {
                    const href = a.getAttribute('href');
                    if (!href) return;
                    if (href.includes('/search/')) return;
                    if (href.includes('/login')) return;
                    if (href.includes('/friends')) return;
                    if (href.includes('/messages')) return;
                    if (seen.has(href)) return;
                    const isProfilePost = profilePostRegex.test(href);
                    const isGroupPost = groupPostRegex.test(href);
                    if (!isProfilePost && !isGroupPost) return;
                    seen.add(href);
                    // Walk up to find the article container
                    let container = a.closest('[role="article"]');
                    if (!container) {
                        // Fallback: walk up 3 levels
                        let p = a.parentElement;
                        for (let i = 0; i < 4 && p; i++) {
                            if (p.innerText && p.innerText.length > 100) {
                                container = p;
                                break;
                            }
                            p = p.parentElement;
                        }
                    }
                    let text = container ? (container.innerText || '').substring(0, 800) : '';
                    text = text.replace(/\s+/g, ' ').trim();
                    // Get the displayed poster name (often the first line of text)
                    let poster = '';
                    if (text) {
                        const firstLine = text.split(/\s{2,}|\n/)[0] || '';
                        poster = firstLine.substring(0, 100);
                    }
                    items.push({ href, poster, text });
                });
                return items;
            }
        """)
        print(f"\nExtracted {len(posts)} REAL posts:")
        for i, post in enumerate(posts[:10]):
            print(f"  [{i}] {post['href'][:90]}")
            print(f"      Poster: {post['poster'][:60]}")
            print(f"      Text:   {post['text'][:200]}")
            print()
        await target.goto(original_url, wait_until="domcontentloaded", timeout=10000)
        print("Tab restored.")
        await browser.close()


asyncio.run(main())
