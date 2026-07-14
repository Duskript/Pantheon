#!/usr/bin/env python3
"""
Reorganize Codex-Claude conversations into day subdirectories and
generate a topic-tagged master INDEX.md for searchability.

Usage:
    python3 reorg-claude-codex.py          # execute
    python3 reorg-claude-codex.py --dry-run  # preview only
"""

import os
import re
import sys
import shutil
from datetime import datetime
from collections import defaultdict

CODE_DIR = os.path.expanduser("~/athenaeum/Codex-Claude/conversations")
ARCHIVE_DIR = os.path.expanduser("~/athenaeum/Codex-Claude/archive")

# ── Topic rules: (keyword patterns, tag) ────────────────────────────
TOPIC_RULES = [
    (['3d', 'print', 'slicer', 'anycubic', 'printer', 'probook'], '3D Printing & Hardware'),
    (['linux', 'ubuntu', 'hyprland', 'kde', 'plasma', 'distrobox', 'bash', 'terminal',
      'package.*install', 'npm', 'bauh', 'etcher', 'uget', 'permission'], 'Software Setup & Linux'),
    (['logo', 'design', 'tattoo', 'red string', 'artistic', 'qr code', 'finder',
      'band member', 'combining.*photo', 'combining.*character', 'image'], 'Design & Art'),
    (['error', 'bug', 'fix', 'debug', 'validation', 'code review', 'blocked',
      'fixing error'], 'Debugging'),
    (['boot', 'drive.*identif', 'disk', 'partition', 'cockpit.*version',
      'converting.*probook'], 'System Admin'),
    (['android', 'app.*button'], 'Android'),
    (['cash', 'eos', 'backup', 'flashing', 'ios.*flash', 'cashyos'], 'Crypto & Finance'),
    (['microsoft', 'm365', 'email.*group', 'group.*user', 'copying.*email'], 'Microsoft 365'),
    (['agent', 'claude.*app', 'openclaude', 'synthetic', 'ai agent',
      'managing.*claude', 'usage limit'], 'AI & Agents'),
    (['cad', 'touch screen', 'android.*design'], 'CAD & Mobile Design'),
    (['dog', 'pup', 'raya', 'pet'], 'Pets'),
    (['function', 'class', 'method', 'variable', 'code.*review', 'bug.*validation',
      'custom.*feature.*overview'], 'Programming'),
    (['document', 'collaborative', 'organizing.*download', 'download.*folder',
      'matching.*data', 'asset.*report'], 'Data & Documents'),
    (['screwdriver', 'handoff'], 'Misc / Humor'),
]


def slugify(text):
    """Slugify a string for filenames."""
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text.strip('-')


def parse_metadata(filepath):
    """
    Parse metadata from a Claude export markdown file.
    Returns dict with title, uuid, created, updated, messages, summary.
    """
    meta = {
        'title': '',
        'uuid': '',
        'created': '',
        'updated': '',
        'messages': 0,
        'summary': '',
        'first_user_msg': '',
        'filename': os.path.basename(filepath),
        'filepath': filepath,
    }

    with open(filepath, 'r', errors='replace') as f:
        content = f.read()

    lines = content.split('\n')

    # Title is first line starting with #
    for line in lines[:5]:
        m = re.match(r'^#\s+(.+)$', line)
        if m:
            meta['title'] = m.group(1).strip()
            break

    # Extract metadata fields
    for line in lines[:20]:
        if '**UUID:**' in line:
            meta['uuid'] = line.split('**UUID:**', 1)[1].strip()
        elif '**Created:**' in line:
            meta['created'] = line.split('**Created:**', 1)[1].strip()
        elif '**Updated:**' in line:
            meta['updated'] = line.split('**Updated:**', 1)[1].strip()
        elif '**Messages:**' in line:
            try:
                meta['messages'] = int(line.split('**Messages:**', 1)[1].strip())
            except:
                pass
        elif '**Summary:**' in line:
            summary = line.split('**Summary:**', 1)[1].strip()
            if summary and summary != '**Conversation Overview**':
                meta['summary'] = summary

    # Extract first user message for context (skip metadata section)
    # Find the first ## User section
    in_user = False
    first_user_lines = []
    for line in lines:
        if line.strip().startswith('## User'):
            in_user = True
            continue
        if in_user:
            if line.strip().startswith('##') and not line.strip().startswith('## User'):
                break
            if line.strip() == '---':
                continue
            if line.strip() and not line.strip().startswith('*20'):
                first_user_lines.append(line.strip())

    meta['first_user_msg'] = ' '.join(first_user_lines)[:200] if first_user_lines else ''

    return meta


def generate_tags(title, first_msg, summary, raw_name):
    """Generate topic tags from title, first message, and summary."""
    # Build search text
    search_text = f"{raw_name} {title} {summary} {first_msg}".lower()

    tags = []
    for keywords, tag in TOPIC_RULES:
        for kw in keywords:
            if kw in search_text:
                tags.append(tag)
                break

    # Fallback for untagged
    if not tags:
        tags.append('General')

    # Deduplicate while preserving order
    seen = set()
    unique_tags = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            unique_tags.append(t)

    return unique_tags


def extract_date(created_str):
    """Parse the Created date string and return a date object."""
    # Format: "2026-03-06 23:55 UTC"
    try:
        return datetime.strptime(created_str.split(' UTC')[0], '%Y-%m-%d %H:%M')
    except:
        pass
    try:
        return datetime.strptime(created_str.split(' UTC')[0], '%Y-%m-%d')
    except:
        return None


def main():
    dry_run = '--dry-run' in sys.argv

    if not os.path.isdir(CODE_DIR):
        print(f"❌ Conversations directory not found: {CODE_DIR}")
        return

    print(f"{'🔍 DRY-RUN' if dry_run else '🔧 Reorganizing'} Codex-Claude conversations")
    print(f"   Source: {CODE_DIR}")
    print("=" * 60)

    # Collect all conversation files
    monthly_dirs = sorted([d for d in os.listdir(CODE_DIR)
                           if os.path.isdir(os.path.join(CODE_DIR, d))
                           and re.match(r'^\d{4}-\d{2}$', d)])

    all_conversations = []

    for month_dir in monthly_dirs:
        month_path = os.path.join(CODE_DIR, month_dir)
        # Walk recursively into day subdirectories (YYYY-MM/YYYY-MM-DD/)
        for root, dirs, files in os.walk(month_path):
            for fname in sorted(files):
                if not fname.endswith('.md') or fname == 'INDEX.md':
                    continue
                filepath = os.path.join(root, fname)

                meta = parse_metadata(filepath)
                date_obj = extract_date(meta['created'])

                if not date_obj:
                    print(f"  ⚠️  Could not parse date from {fname}, skipping")
                    continue

                # For untitled conversations, use the first user message as title
                raw_name = os.path.splitext(fname)[0]
                if not meta['title'] or meta['title'] == '':
                    # Extract topic from the UUID slug
                    title_match = re.match(r'^(.+?)--[a-f0-9]+$', raw_name)
                    if title_match:
                        meta['title'] = title_match.group(1).replace('-', ' ').title()
                    else:
                        meta['title'] = '(untitled)'

                tags = generate_tags(meta['title'], meta['first_user_msg'],
                                     meta['summary'], raw_name)

                all_conversations.append({
                    **meta,
                    'date_obj': date_obj,
                    'date_str': date_obj.strftime('%Y-%m-%d'),
                    'day_dir': date_obj.strftime('%Y-%m-%d'),
                    'month_dir': date_obj.strftime('%Y-%m'),
                    'tags': tags,
                })

    # Group by month
    by_month = defaultdict(list)
    for conv in all_conversations:
        by_month[conv['month_dir']].append(conv)

    print(f"\n📊 Found {len(all_conversations)} conversations across {len(by_month)} months\n")

    # Create day subdirectories and move files
    dry_run_log = []
    moves = []
    for conv in all_conversations:
        src = conv['filepath']
        target_month = os.path.join(CODE_DIR, conv['month_dir'])
        target_day = os.path.join(target_month, conv['day_dir'])
        target_path = os.path.join(target_day, conv['filename'])

        if src != target_path:
            moves.append((src, target_path, conv))

    if not moves:
        print("✅ All files are already in the correct day directories.")
        print("   Skipping to INDEX.md generation...\n")
    else:
        print(f"📁 {len(moves)} files to reorganize into day subdirectories:\n")
        for src, dst, conv in moves[:10]:
            print(f"   {conv['date_str']}  {conv['filename'][:55]}")
        if len(moves) > 10:
            print(f"   ... and {len(moves) - 10} more")

        if not dry_run:
            for src, dst, conv in moves:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
                # Remove source month dir if empty now
                src_month = os.path.dirname(src)
                try:
                    os.rmdir(src_month)
                except OSError:
                    pass  # not empty, fine
            # Recreate month dirs if needed
            for conv in all_conversations:
                os.makedirs(os.path.join(CODE_DIR, conv['month_dir']), exist_ok=True)
            print(f"\n✅ Moved {len(moves)} files into day directories")
        else:
            print(f"\n[DRY-RUN] Would move {len(moves)} files (see above)")

    # ── Write master INDEX.md ──
    all_sorted = sorted(all_conversations, key=lambda c: c['date_obj'], reverse=True)

    index_lines = [
        "# Codex-Claude — Master Index",
        "",
        f"Auto-generated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}",
        f"Total conversations: {len(all_sorted)}",
        f"Date range: {all_sorted[-1]['date_str']} → {all_sorted[0]['date_str']}" if all_sorted else "",
        "",
        "## Conversations by Topic",
        "",
    ]

    # Build topic index
    topic_groups = defaultdict(list)
    for conv in all_sorted:
        for tag in conv['tags']:
            topic_groups[tag].append(conv)

    index_lines.append("| Topic | Count |")
    index_lines.append("|-------|-------|")
    for tag in sorted(topic_groups.keys()):
        count = len(topic_groups[tag])
        index_lines.append(f"| **{tag}** | {count} |")
    index_lines.append("")

    # Full table
    index_lines.extend([
        "",
        "## All Conversations",
        "",
        "| Date | Title | Topic | Msgs | Path |",
        "|------|-------|-------|------|------|",
    ])

    for conv in all_sorted:
        date = conv['date_str']
        title = conv['title'][:55].replace('|', '/')
        tags = ', '.join(conv['tags'][:2])
        msgs = conv['messages']
        filename = conv['filename']
        filepath = f"{conv['month_dir']}/{conv['day_dir']}/{filename}"

        index_lines.append(f"| {date} | {title} | {tags} | {msgs} | [{filename}]({filepath}) |")

    index_lines.extend([
        "",
        "---",
        "",
        "## Month Archives",
        "",
    ])

    # Per-month sections
    for month in sorted(by_month.keys(), reverse=True):
        month_convs = sorted(by_month[month], key=lambda c: c['date_obj'])
        index_lines.append(f"### {month}")
        index_lines.append("")
        index_lines.append("| Day | Title | Topic | Msgs | Link |")
        index_lines.append("|-----|-------|-------|------|------|")
        for conv in month_convs:
            day = conv['day_dir']
            title = conv['title'][:50].replace('|', '/')
            tags = ', '.join(conv['tags'][:2])
            msgs = conv['messages']
            filename = conv['filename']
            filepath = f"{day}/{filename}"
            index_lines.append(f"| {day} | {title} | {tags} | {msgs} | [{filename}]({filepath}) |")
        index_lines.append("")

    if not dry_run:
        index_path = os.path.join(CODE_DIR, "INDEX.md")
        with open(index_path, 'w') as f:
            f.write('\n'.join(index_lines) + '\n')
        print(f"\n📄 Written master INDEX.md ({len(all_sorted)} conversations, {len(topic_groups)} topics)")
    else:
        index_path_display = os.path.join(CODE_DIR, "INDEX.md")
        print(f"\n📄 Would write INDEX.md ({len(all_sorted)} conversations, {len(topic_groups)} topics)")

    # Per-month INDEX.md files
    if not dry_run:
        for month in sorted(by_month.keys(), reverse=True):
            month_convs = sorted(by_month[month], key=lambda c: c['date_obj'])
            month_lines = [
                f"# {month} — Conversations",
                "",
                f"Parent: [INDEX.md](../INDEX.md)",
                f"Conversations in this month: {len(month_convs)}",
                "",
                "| Date | Title | Topic | Msgs | Link |",
                "|------|-------|-------|------|------|",
            ]
            for conv in month_convs:
                day = conv['day_dir']
                title = conv['title'][:50].replace('|', '/')
                tags = ', '.join(conv['tags'][:2])
                msgs = conv['messages']
                filename = conv['filename']
                filepath = f"{day}/{filename}"
                month_lines.append(f"| {conv['date_str']} | {title} | {tags} | {msgs} | [{filename}]({filepath}) |")

            month_index_path = os.path.join(CODE_DIR, month, "INDEX.md")
            with open(month_index_path, 'w') as f:
                f.write('\n'.join(month_lines) + '\n')

    print(f"\n✅ Done.")


if __name__ == '__main__':
    main()
