#!/usr/bin/env python3
"""
Create Notion pages from the Dawn Patrol briefing data.
This script creates pages in the Notion workspace with:
- Parent ID: 38aff934-3bb9-81c1-b7dc-cc8b4b52512b
- Titles: "Dawn Patrol - YYYY-MM-DD"
- Icons: 🌅 for Dawn Patrol, ☀️ for Morning Briefing
- Body: The briefing's markdown content
- Deduplication by date only
"""

import os
import sys
import requests
from pathlib import Path


# Notion API credentials (from previous script)
NOTION_API_KEY = os.getenv('NOTION_API_KEY', 'YOUR_API_KEY_HERE')
WSPROF_ID = '38aff934-3bb9-81c1-b7dc-cc8b4b52512b'
COMPOSIO_MULTI_EXECUTE_TOOL = 'composio.multi.execute'
NOTION_CREATE_NOTION_PAGE = 'composio.create.notion.page'


def get_dawn_patrol_briefing():
    """
    Get the latest Dawn Patrol briefing from the script output.
    Returns the briefing as a dictionary.
    """
    briefing_data = os.environ.get('DAWN_PATROL_BRIEFING', '')
    if not briefing_data:
        return None
    
    # Parse the briefing data
    briefing = {
        'title': 'Cron Job: Dawn Patrol Raw Collection',
        'body': briefing_data,
        'date': None
    }
    
    # Try to parse the date from the briefing
    for line in briefing_data.split('\n'):
        line = line.strip()
        if line.startswith('-'):
            continue
        if 'date' in line.lower():
            date_part = line.split(':')[1].strip().strip('`').strip('"')
            briefing['date'] = date_part
            break
    
    return briefing


def create_notion_page(briefing, icon):
    """
    Create a Notion page using the Notion API.
    Args:
        briefing: The briefing dictionary
        icon: The icon to use (🌅 or ☀️)
    Returns:
        True if successful, False otherwise
    """
    try:
        # Build the Notion page object
        page_data = {
            'title': [{'text': {'content': briefing['title']}}],
            'properties': {
                'icon.name': {'rich_text': [{'text': {'content': icon}}]},
                'label.date': {'date': {'start': briefing['date']}}
            }
        }
        
        # Use the Notion API to create the page
        url = f'https://api.notion.com/v1/pages'
        headers = {
            'Authorization': f'Bearer {NOTION_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'parent': {
                'type': 'workspace',
                'id': WSPROF_ID
            },
            'properties': page_data
        }
        
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 201:
            print(f"✓ Created Notion page: {briefing['title']}")
            return True
        elif response.status_code == 400:
            print(f"✗ API error: {response.text}")
            return False
        else:
            print(f"✗ API error: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"✗ Error creating page: {e}")
        return False


def main():
    """
    Main function to create Notion pages from the briefing data.
    """
    # Get the briefing data
    briefing = get_dawn_patrol_briefing()
    
    if briefing is None:
        print("✗ No briefing data found")
        return
    
    # Get unique dates
    dates = set()
    for line in briefing.split('\n'):
        if line.startswith('-'):
            continue
        if 'date' in line.lower():
            date_part = line.split(':')[1].strip().strip('`').strip('"')
            dates.add(date_part)
    
    # Get unique titles
    titles = set()
    for line in briefing.split('\n'):
        if line.startswith('-'):
            continue
        if 'title' in line.lower():
            title_part = line.split(':')[1].strip().strip('`').strip('"')
            titles.add(title_part)
    
    print(f"Found {len(dates)} unique dates: {sorted(dates)}")
    print(f"Found {len(titles)} unique titles: {sorted(titles)}")
    
    # Create pages for each unique date
    for date in sorted(dates):
        print(f"\nCreating page for date: {date}")
        
        # Get the briefing for this date
        date_briefing = {
            'title': titles.pop(),
            'body': briefing,
            'date': date
        }
        
        if create_notion_page(date_briefing, '🌅'):
            print(f"✓ Created page successfully")
        else:
            print(f"✗ Failed to create page")
    
    print("\n✓ All pages created successfully!")
    return 0


if __name__ == '__main__':
    sys.exit(main())
