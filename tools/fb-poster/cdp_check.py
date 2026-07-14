"""Attach to Vivaldi via CDP, find Facebook tab, check login state."""
import asyncio
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        print("Connected. Browser: chromium via CDP")
        print(f"Contexts: {len(browser.contexts)}")
        for i, ctx in enumerate(browser.contexts):
            print(f"  Context {i}: {len(ctx.pages)} pages")

        fb_page = None
        for ctx in browser.contexts:
            for page in ctx.pages:
                if "facebook.com" in page.url and "chrome-extension" not in page.url and "/search/" not in page.url:
                    fb_page = page
                    break
            if fb_page:
                break

        if not fb_page:
            print("No Facebook homepage tab found.")
            return

        await asyncio.sleep(1)
        html = await fb_page.content()
        with open("/home/konan/pantheon/logs/fb_home.html", "w") as f:
            f.write(html)
        login_markers = ["Log in", "Log In", "Sign Up", "Create Account", "Email or phone"]
        logged_in_markers = ["News Feed", "What's on your mind", "Home", "Your profile", "Notifications"]
        html_lower = html.lower()
        is_logged_out = any(m.lower() in html_lower for m in login_markers)
        is_logged_in = any(m.lower() in html_lower for m in logged_in_markers)
        print("\nLogin analysis:")
        print(f"  Logged-out markers present: {is_logged_out}")
        print(f"  Logged-in markers present: {is_logged_in}")
        print(f"  Current URL: {fb_page.url}")
        cookies = await fb_page.context.cookies()
        fb_cookies = [c for c in cookies if "facebook.com" in c.get("domain", "")]
        print(f"  Facebook cookies: {len(fb_cookies)}")
        for c in fb_cookies[:8]:
            print(f"    {c.get('name')}: expires={c.get('expires', '?')}")
        body_text = await fb_page.evaluate("() => document.body.innerText.substring(0, 1500)")
        print("\n--- Page text (first 1500 chars) ---")
        print(body_text)
        print("--- end ---")

        await browser.close()


asyncio.run(main())
