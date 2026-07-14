#!/usr/bin/env python3
"""
Craigslist East Idaho Gig Monitor v3
Scrapes gig listings, filters by service keywords, outputs actionable leads.
For listings where full URLs aren't available from JS-rendered search results,
provides Craigslist search links to find them.
"""

import re
import html
import json
import subprocess
import sys
from datetime import datetime
from urllib.parse import quote

REGION = "eastidaho"
REGION_NAME = "East Idaho"

CATEGORIES = {
    "ggg": "All Gigs",
    "cpg": "Computer Gigs",
    "cwg": "Creative Gigs",
    "cba": "General Labor",
}

SERVICE_KEYWORDS = [
    "website", "web design", "landing page", "wordpress", "wix", "shopify",
    "spreadsheet", "excel", "google sheets", "data entry", "google forms",
    "canva", "logo", "graphic design", "flyer", "banner",
    "write", "writer", "article", "content", "blog", "copy", "proofread", "edit",
    "facebook", "social media", "crm",
    "ai", "automation", "chatbot",
    "tech support", "computer help", "it help",
    "virtual assistant", "remote admin",
    "photo", "photograph", "video edit",
]

QUICK_PAY_KEYWORDS = [
    "remote", "work from home", "work from phone",
    "photo", "voice", "talk",
    "focus group", "research study", "survey",
    "writer", "article",
]

def fetch_page(url):
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "15", "-L",
             "-A", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
             url],
            capture_output=True, text=True, timeout=20
        )
        return result.stdout
    except:
        return ""

def extract_listings(html_content):
    """Extract listings from Craigslist search results page."""
    listings = []
    pattern = r'href="(https://[^"]*/d/[^"]+)"[^>]*>[\s]*(.*?)</a>'
    for m in re.finditer(pattern, html_content, re.DOTALL):
        url = m.group(1).strip()
        text = re.sub(r'<[^>]+>', '', m.group(2))
        text = html.unescape(text).strip()
        text = ' '.join(text.split())
        if text and len(text) > 5:
            listings.append({"title": text, "url": url})
    return listings

def is_valid_url(url):
    """Check if URL is real (not truncated with ellipsis)."""
    return "…" not in url and url.endswith(('/d/' + url.split('/d/')[-1] if '/d/' in url else url))

def get_search_link(title, category):
    """Generate a Craigslist search URL for a listing title."""
    query = quote(title[:60])
    return f"https://{REGION}.craigslist.org/search/{'ggg' if category == 'All Gigs' else category.lower()[:3]}?query={query}"

def get_listing_detail(url):
    """Get full detail from a listing page."""
    html_content = fetch_page(url)
    title_m = re.search(r'<title>(.*?)</title>', html_content)
    title = html.unescape(title_m.group(1)).replace(' - craigslist', '').strip() if title_m else ""
    body_m = re.search(r'id="postingbody">(.*?)</section>', html_content, re.DOTALL)
    body = ""
    if body_m:
        body = re.sub(r'<[^>]+>', '', body_m.group(1))
        body = html.unescape(body).strip()
        body = re.sub(r'\s+', ' ', body)
    return title, body

def check_keywords(text, keyword_list):
    text_lower = text.lower()
    return [kw for kw in keyword_list if kw.lower() in text_lower]

def generate_pitch(title):
    t = title.lower()
    if any(w in t for w in ["write", "writer", "article", "content", "blog"]):
        return "Professional writer with 15+ years experience. Can deliver quality articles fast. What's your topic and deadline?"
    elif any(w in t for w in ["photo", "photograph", "card", "ticket"]):
        return "Can do this today. Have equipment ready. How do I apply/sign up?"
    elif any(w in t for w in ["voice", "talk", "phone"]):
        return "Available now. Clear speaking voice, quiet home environment. Send details."
    elif any(w in t for w in ["focus group", "research", "survey"]):
        return "Interested. Available for online participation. Please send qualification link."
    elif any(w in t for w in ["website", "web", "wordpress", "wix", "landing"]):
        return "I build websites — landing pages to full sites. Can have a draft in 24hrs. What's your budget and needs?"
    elif any(w in t for w in ["excel", "spreadsheet", "data entry", "google sheet"]):
        return "Expert with Excel/Google Sheets. Can build automations or handle data entry remotely."
    elif any(w in t for w in ["social media", "facebook", "instagram"]):
        return "I handle social media management and content. Can set up or take over your pages."
    elif any(w in t for w in ["canva", "logo", "graphic", "flyer", "banner"]):
        return "I create professional designs — logos, flyers, social media graphics. Quick turnaround."
    elif any(w in t for w in ["ai", "automation", "chatbot"]):
        return "I build AI automation systems. Can streamline your workflow. Let me know what you need automated."
    elif any(w in t for w in ["photo", "videograph"]):
        return "Available for this project. Have equipment. Can you share more details?"
    else:
        return "I can help with this. Send me the details and I'll let you know my availability."

def main():
    print("=" * 60)
    print(f"CRAIGSLIST {REGION_NAME.upper()} — GIG MONITOR v3")
    print(f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    
    all_leads = []
    quick_pay_leads = []
    
    for cat_id, cat_name in CATEGORIES.items():
        url = f"https://{REGION}.craigslist.org/search/{cat_id}?sort=date"
        print(f"\n📂 {cat_name}...", end=" ", flush=True)
        
        html_content = fetch_page(url)
        if not html_content:
            print("❌ Failed")
            continue
        
        listings = extract_listings(html_content)
        print(f"{len(listings)}")
        
        for listing in listings:
            title = listing["title"]
            # Check title for keywords
            svc_matches = check_keywords(title, SERVICE_KEYWORDS)
            is_quick = any(kw in title.lower() for kw in QUICK_PAY_KEYWORDS)
            
            if not svc_matches and not is_quick:
                continue
            
            # Try to get detail
            url = listing["url"]
            detail_title, body = "", ""
            if is_valid_url(url):
                detail_title, body = get_listing_detail(url)
            
            full_text = f"{detail_title or title} {body}"
            svc_matches = check_keywords(full_text, SERVICE_KEYWORDS)
            
            if not svc_matches and not is_quick:
                continue
            
            search_link = get_search_link(title, cat_name)
            
            lead = {
                "title": detail_title or title,
                "url": url if is_valid_url(url) else search_link,
                "url_type": "direct" if is_valid_url(url) else "search link",
                "category": cat_name,
                "keywords": svc_matches,
                "preview": body[:200] if body else "",
                "pitch": generate_pitch(detail_title or title),
                "is_remote": "remote" in full_text.lower() or "work from home" in full_text.lower(),
                "is_quick_pay": is_quick,
            }
            all_leads.append(lead)
            if is_quick or "remote" in full_text.lower():
                quick_pay_leads.append(lead)
    
    # ── Output ───────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("ACTIONABLE LEADS")
    print("=" * 60)
    
    if not all_leads:
        print("\n❌ No matching service gigs found this scan.")
        print("   Check back later or expand your keywords.")
    
    if quick_pay_leads:
        print(f"\n🔴💰 QUICK-PAY / REMOTE LEADS ({len(quick_pay_leads)})")
        print("-" * 60)
        for i, lead in enumerate(quick_pay_leads, 1):
            print(f"\n  [{i}] {lead['title'][:80]}")
            if lead['url_type'] == 'direct':
                print(f"      🔗 {lead['url']}")
            else:
                print(f"      🔍 Search: {lead['url']}")
            if lead['keywords']:
                print(f"      Keywords: {', '.join(lead['keywords'][:5])}")
            if lead['preview']:
                print(f"      {lead['preview'][:150]}...")
            print(f"      💬 {lead['pitch']}")
    
    if all_leads:
        print(f"\n📋 ALL MATCHES ({len(all_leads)})")
        print("-" * 60)
        for lead in all_leads:
            if lead['url_type'] == 'direct':
                print(f"  • {lead['title'][:60]} → {lead['url']}")
            else:
                print(f"  • {lead['title'][:60]} → [Search] {lead['url']}")
    
    # Save
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    path = f"/home/konan/pantheon/craigslist_leads.json"
    with open(path, "w") as f:
        json.dump({"timestamp": ts, "quick_pay": quick_pay_leads, "all": all_leads}, f, indent=2)
    
    # Also write a simple HTML report for easy viewing
    html_path = f"/home/konan/pantheon/craigslist_leads.html"
    with open(html_path, "w") as f:
        f.write(f"<html><head><title>CL Leads {ts}</title>")
        f.write("<style>body{font-family:sans-serif;max-width:800px;margin:20px auto;padding:0 20px}")
        f.write(".lead{border:1px solid #ddd;padding:15px;margin:10px 0;border-radius:8px}")
        f.write(".remote{background:#fff3cd}.pitch{color:#555;font-style:italic}")
        f.write("a{color:#1a73e8}h2{color:#d93025}</style></head><body>")
        f.write(f"<h1>Craigslist Leads — {ts}</h1>")
        f.write(f"<p>{len(quick_pay_leads)} quick-pay | {len(all_leads)} total</p>")
        for lead in quick_pay_leads:
            cls = "lead remote" if lead.get('is_remote') else "lead"
            f.write(f'<div class="{cls}">')
            f.write(f"<h3>{lead['title']}</h3>")
            if lead['url_type'] == 'direct':
                f.write(f'<p><a href="{lead["url"]}">🔗 View Listing</a></p>')
            else:
                f.write(f'<p><a href="{lead["url"]}">🔍 Search on Craigslist</a></p>')
            if lead['keywords']:
                f.write(f"<p>Keywords: {', '.join(lead['keywords'][:5])}</p>")
            f.write(f'<p class="pitch">{lead["pitch"]}</p>')
            f.write("</div>")
        f.write("</body></html>")
    
    print(f"\n💾 JSON: {path}")
    print(f"💾 HTML: {html_path}")
    print(f"\n{'='*60}")
    print(f"QUICK-PAY: {len(quick_pay_leads)} | TOTAL: {len(all_leads)}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
