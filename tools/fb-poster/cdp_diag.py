"""Quick diagnostic: can we connect to Vivaldi CDP and reuse an existing page?"""
import asyncio
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        print(f"Connected. Contexts: {len(browser.contexts)}")
        ctx = browser.contexts[0]
        pages = ctx.pages
        print(f"Existing pages: {len(pages)}")
        # Find a non-extension, non-Facebook page to hijack
        target = None
        for i, page in enumerate(pages):
            url = page.url
            if "chrome-extension" not in url and "facebook.com" not in url:
                title = await page.title()
                print(f"  Candidate: page {i} - {title[:50]} | {url[:80]}")
                if target is None:
                    target = page
        if target is None:
            print("No non-extension, non-Facebook pages to hijack.")
            await browser.close()
            return
        title_before = await target.title()
        print(f"\nHijacking: {title_before}")
        try:
            await target.goto("https://www.example.com", wait_until="domcontentloaded", timeout=10000)
            new_title = await target.title()
            print(f"Success! Page is now: {new_title}")
        except Exception as e:
            print(f"goto failed: {e}")
        await browser.close()


asyncio.run(main())
