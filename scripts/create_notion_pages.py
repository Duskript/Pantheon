#!/usr/bin/env python3
"""Create Notion pages from Pantheon briefing data."""

from hermes_tools import Composio

# Configuration
NOTION_ID = "38aff934-3bb9-81c1-b7dc-cc8b4b52512b"
COMPOSIO_TOKEN = "your-notion-token"  # Replace with actual token
COMPOSIO_NOTION_ID = "notion_latite-dags"
NOTION_PAGE_URL = "https://www.notion.so"

# Briefing data from JSON script output
briefings = [
    {
        "label": "Dawn Patrol",
        "url": "https://github.com/byte5ai/omadia",
        "icon": "🌅",
        "body": "- **byte5ai/omadia** (TypeScript, ★28)\n  Self-hostable agentic OS. Build, run & audit multi-agent AI teams from signed plugins. Bring your own LLM key, own all y"
    },
    {
        "label": "Morning Briefing",
        "url": "https://github.com/w2ur/midas-core",
        "icon": "☀️",
        "body": "- **w2ur/midas-core** (Python, ★0)\n  Multi-agent paper-trading framework: LLM agents propose trades, a separate broker validates and executes them. pip insta"
    },
    {
        "label": "Morning Briefing",
        "url": "https://github.com/XFuel-Lab/xfuel-protocol",
        "icon": "🌅",
        "body": "- **XFuel-Lab/xfuel-protocol** (JavaScript, ★1)\n  Verifiable settlement + payments for AI compute - route any model, pay per task (USDC/x402), and get a public proof rece"
    }
]

# Create Notion pages (skip duplicates by title + date)
created_pages = []
for briefing in briefings:
    title = f"{briefing['label']} - {briefing['url'].split('/')[-1]}"  # Use URL as date
    is_duplicate = any(
        not created_pages and 
        created_pages[0]["title"] == title 
        for created_pages in created_pages
    )
    
    if not is_duplicate:
        import os
        os.makedirs('/home/konan/.hermes/cache/composio', exist_ok=True)
        
        # Create page
        page = {
            "title": title,
            "url": briefing['url'],
            "icon": briefing['icon'],
            "body": briefing['body']
        }
        
        result = Composio.create_page(
            parent={"id": NOTION_ID},
            title=title,
            body=page["body"],
            icon=page["icon"]
        )
        
        created_pages.append(result)
        print(f"Created: {result.link}")
    else:
        print(f"Skipping (duplicate): {title}")

print(f"\nTotal pages created: {len(created_pages)}")
