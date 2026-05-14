"""
Connectors API — Quick-Connect integrations backed by ACI.dev.

Provides curated catalog + auth pipeline for popular services.
Uses the handler pattern from routes.py (BaseHTTPRequestHandler-style).
"""

import json
import logging
import os
import time

logger = logging.getLogger(__name__)

# ── Curated quick-connect catalog ──────────────────────────────────────────
CATALOG = [
    # Communication
    {"key": "SLACK",       "name": "Slack",         "category": "Communication",   "auth": "oauth2",  "desc": "Team messaging & collaboration",               "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/slack.svg"},
    {"key": "DISCORD",     "name": "Discord",       "category": "Communication",   "auth": "oauth2",  "desc": "Voice, video & text chat communities",           "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/discord.svg"},
    {"key": "GMAIL",       "name": "Gmail",         "category": "Communication",   "auth": "oauth2",  "desc": "Google email & inbox management",                 "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/gmail.svg"},
    {"key": "MICROSOFT_OUTLOOK", "name": "Outlook", "category": "Communication",   "auth": "oauth2",  "desc": "Microsoft email & calendar",                      "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/outlook.svg"},
    {"key": "REDDIT",      "name": "Reddit",        "category": "Communication",   "auth": "oauth2",  "desc": "Community discussions & content",                 "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/reddit.svg"},
    {"key": "X",           "name": "X (Twitter)",   "category": "Communication",   "auth": "oauth2",  "desc": "Social media & microblogging",                     "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/x.svg"},
    {"key": "SENDGRID",    "name": "SendGrid",      "category": "Communication",   "auth": "api_key", "desc": "Email delivery & transactional email",            "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/sendgrid.svg"},

    # Dev Tools
    {"key": "GITHUB",      "name": "GitHub",        "category": "Dev Tools",       "auth": "oauth2",  "desc": "Source code hosting & collaboration",             "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/github.svg"},
    {"key": "GITLAB",      "name": "GitLab",        "category": "Dev Tools",       "auth": "oauth2",  "desc": "DevOps platform & CI/CD",                         "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/gitlab.svg"},
    {"key": "JIRA",        "name": "Jira",          "category": "Dev Tools",       "auth": "oauth2",  "desc": "Issue tracking & agile project management",       "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/jira.svg"},
    {"key": "FIGMA",       "name": "Figma",         "category": "Dev Tools",       "auth": "oauth2",  "desc": "Collaborative interface design",                  "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/figma.svg"},
    {"key": "VERCEL",      "name": "Vercel",        "category": "Dev Tools",       "auth": "api_key", "desc": "Frontend deployment & serverless functions",      "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/vercel.png"},
    {"key": "NETLIFY",     "name": "Netlify",       "category": "Dev Tools",       "auth": "api_key", "desc": "Web hosting & serverless backend",                "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/netlify.svg"},
    {"key": "SENTRY",      "name": "Sentry",        "category": "Dev Tools",       "auth": "api_key", "desc": "Application performance monitoring & errors",      "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/sentry.svg"},

    # Productivity
    {"key": "NOTION",      "name": "Notion",        "category": "Productivity",    "auth": "oauth2",  "desc": "Docs, wikis & project management",                "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/notion.svg"},
    {"key": "ASANA",       "name": "Asana",         "category": "Productivity",    "auth": "api_key", "desc": "Team task & project tracking",                    "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/asana.png"},
    {"key": "GOOGLE_CALENDAR", "name": "Google Calendar", "category": "Productivity", "auth": "oauth2", "desc": "Scheduling & calendar management",              "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/google_calendar.svg"},
    {"key": "CALENDLY",    "name": "Calendly",      "category": "Productivity",    "auth": "oauth2",  "desc": "Automated meeting scheduling",                    "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/calendly.svg"},
    {"key": "GOOGLE_TASKS", "name": "Google Tasks", "category": "Productivity",    "auth": "oauth2",  "desc": "Personal to-do list management",                 "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/google_tasks.svg"},

    # Documents & Storage
    {"key": "GOOGLE_DOCS", "name": "Google Docs",   "category": "Documents",       "auth": "oauth2",  "desc": "Collaborative document editing",                  "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/google_docs.svg"},
    {"key": "GOOGLE_SHEETS", "name": "Google Sheets","category": "Documents",      "auth": "oauth2",  "desc": "Collaborative spreadsheets",                      "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/google_sheets.svg"},
    {"key": "MICROSOFT_ONEDRIVE", "name": "OneDrive","category": "Documents",      "auth": "oauth2",  "desc": "Microsoft cloud file storage",                    "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/onedrive.svg"},

    # AI & Media
    {"key": "ELEVEN_LABS", "name": "Eleven Labs",   "category": "AI & Media",     "auth": "api_key", "desc": "AI voice synthesis & text-to-speech",              "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/eleven_labs.svg"},
    {"key": "REPLICATE",   "name": "Replicate",     "category": "AI & Media",     "auth": "api_key", "desc": "Cloud ML model hosting & inference",               "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/replicate.svg"},
    {"key": "YOUTUBE",     "name": "YouTube",       "category": "AI & Media",     "auth": "oauth2",  "desc": "Video streaming & content platform",               "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/youtube.svg"},

    # Payments
    {"key": "STRIPE",      "name": "Stripe",        "category": "Payments",        "auth": "api_key", "desc": "Payment processing & billing platform",            "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/stripe.svg"},

    # Search & Scraping
    {"key": "BRAVE_SEARCH","name": "Brave Search",  "category": "Search",          "auth": "api_key", "desc": "Privacy-first web search API",                    "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/brave_search.svg"},
    {"key": "FIRECRAWL",   "name": "Firecrawl",     "category": "Search",          "auth": "api_key", "desc": "Web scraping & AI-ready content extraction",       "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/firecrawl.svg"},
    {"key": "SERPAPI",     "name": "SerpApi",       "category": "Search",          "auth": "api_key", "desc": "Search engine results API (Google, Bing, etc.)",   "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/serpapi.svg"},

    # Research
    {"key": "ARXIV",       "name": "arXiv",         "category": "Research",        "auth": "no_auth", "desc": "Open-access scientific paper repository",         "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/arxiv.svg"},
    {"key": "HACKERNEWS",  "name": "Hacker News",   "category": "Research",        "auth": "no_auth", "desc": "Tech news & community discussion",                 "logo": "https://raw.githubusercontent.com/aipotheosis-labs/aipolabs-icons/refs/heads/main/apps/hackernews.png"},
]

CATEGORIES = sorted(set(item["category"] for item in CATALOG))

# Stats for "X connected out of Y"
_QUICK_COUNTS = {
    cat: sum(1 for s in CATALOG if s["category"] == cat)
    for cat in CATEGORIES
}


# ── ACI helpers ──────────────────────────────────────────────────────────────

def _aci_available():
    return bool(os.environ.get("ACI_API_KEY"))


def _get_aci():
    if not _aci_available():
        return None
    try:
        from aci import ACI
        return ACI()
    except Exception as e:
        logger.warning("ACI SDK init failed: %s", e)
        return None


def _send_json(handler, data, status=200):
    """Send a JSON response using handler.send_response pattern."""
    body = json.dumps(data).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    handler.wfile.write(body)
    return True


def _read_body(handler):
    """Read POST body from handler."""
    length = int(handler.headers.get("Content-Length", 0))
    return handler.rfile.read(length) if length else b"{}"


# ── Route handlers ───────────────────────────────────────────────────────────

def handle_get_catalog(handler):
    """GET /api/connectors/catalog"""
    aci = _get_aci()
    linked = set()
    if aci:
        try:
            accounts = aci.linked_accounts.list()
            linked = {a.app_name for a in accounts if a.status == "active"}
        except Exception as e:
            logger.warning("Failed to fetch linked accounts: %s", e)

    enriched = []
    for svc in CATALOG:
        s = dict(svc)
        s["connected"] = s["key"] in linked
        s["aci_configured"] = _aci_available()
        enriched.append(s)

    # Build per-category connected counts
    cat_counts = {}
    for s in enriched:
        c = s["category"]
        if c not in cat_counts:
            cat_counts[c] = {"total": 0, "connected": 0}
        cat_counts[c]["total"] += 1
        if s["connected"]:
            cat_counts[c]["connected"] += 1

    return _send_json(handler, {
        "categories": list(cat_counts.keys()),
        "category_counts": cat_counts,
        "services": enriched,
        "aci_configured": _aci_available(),
        "catalog_version": 1,
    })


def handle_post_connect(handler):
    """POST /api/connectors/connect"""
    try:
        req = json.loads(_read_body(handler))
    except Exception:
        return _send_json(handler, {"error": "Invalid JSON body"}, 400)

    app_key = (req.get("key") or "").upper()
    auth_type = req.get("auth", "api_key")
    api_key_value = req.get("api_key", "")
    owner_id = req.get("owner_id", "default")

    svc = next((s for s in CATALOG if s["key"] == app_key), None)
    if not svc:
        return _send_json(handler, {"error": f"Unknown connector: {app_key}"}, 404)

    aci = _get_aci()
    if not aci:
        return _send_json(handler, {
            "error": "ACI not configured",
            "message": "Set the ACI_API_KEY environment variable and restart.",
        }, 501)

    try:
        from aci.types.enums import SecurityScheme
        scheme_map = {
            "oauth2": SecurityScheme.OAUTH2,
            "api_key": SecurityScheme.API_KEY,
            "no_auth": SecurityScheme.NO_AUTH,
        }
        scheme = scheme_map.get(auth_type, SecurityScheme.API_KEY)

        result = aci.linked_accounts.link(
            app_name=app_key,
            security_scheme=scheme,
            linked_account_owner_id=owner_id,
            api_key=api_key_value if auth_type == "api_key" else None,
        )

        if isinstance(result, str) and result.startswith("http"):
            return _send_json(handler, {"status": "oauth_redirect", "url": result})
        else:
            account_id = str(result.id) if hasattr(result, 'id') else "ok"
            return _send_json(handler, {"status": "connected", "account_id": account_id})

    except Exception as e:
        logger.error("Connect failed for %s: %s", app_key, e)
        return _send_json(handler, {"error": str(e)}, 500)


def handle_post_disconnect(handler):
    """POST /api/connectors/disconnect"""
    try:
        req = json.loads(_read_body(handler))
    except Exception:
        return _send_json(handler, {"error": "Invalid JSON body"}, 400)

    app_key = (req.get("key") or "").upper()
    owner_id = req.get("owner_id", "default")

    aci = _get_aci()
    if not aci:
        return _send_json(handler, {"error": "ACI not configured"}, 501)

    try:
        accounts = aci.linked_accounts.list(app_name=app_key, linked_account_owner_id=owner_id)
        for acct in accounts:
            aci.linked_accounts.delete(acct.id)
        return _send_json(handler, {"status": "disconnected"})
    except Exception as e:
        logger.error("Disconnect failed for %s: %s", app_key, e)
        return _send_json(handler, {"error": str(e)}, 500)
