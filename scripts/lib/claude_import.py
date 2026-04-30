"""
Claude Import — shared helpers for the pantheon-import-claude tool.
"""
import json
import os
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

# ── Paths (same pattern as pantheon_sdk.py) ──────────────────────────

HOME = os.path.expanduser("~")
if ".hermes/profiles" in HOME:
    parts = HOME.split("/.hermes/profiles/")
    HOME = parts[0]

PANTHEON_DIR = os.path.join(HOME, "pantheon")
ATHENAEUM_DIR = os.path.join(HOME, "athenaeum")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(SCRIPT_DIR, "lib")
sys.path.insert(0, LIB_DIR)

# ── Routing Rules ────────────────────────────────────────────────────

# Keywords that route a conversation to a specific Codex
ROUTE_RULES = [
    # Apollo — Lyric Smith core knowledge
    ("apollo", ["lyric smith", "lyricist", "lyric-writing", "lyric craft",
                 "apollo god", "god of music"]),
    # SKC — music, lyrics, styles, Suno
    ("skc", ["lyric", "song", "style prompt", "suno", "verse", "chorus",
             "bridge", "hook", "genre", "kips", "vocal", "melody",
             "rhyme scheme", "power prompt", "section"]),
    # Work — Jira, IT, helpdesk
    ("work", ["jira", "helpdesk", "help desk", "ticket", "inventory",
              "it support", "onboarding", "offboarding", "mdm",
              "vcenter", "provision"]),
    # Infrastructure — tech, homelab, networking
    ("infrastructure", ["homelab", "proxmox", "networking", "port forward",
                        "vlan", "docker", "kubernetes", "ollama",
                        "server", "raspberry pi", "nginx"]),
]

# Project routing — certain projects belong to specific Codices
PROJECT_ROUTES = {
    "lyric smith": "apollo",
    "stylish style maker": "apollo",
    "suno formatter": "apollo",
    "album art": "skc",
    "jira": "work",
    "agent zero": "infrastructure",
    "synthetic.new": "infrastructure",
}


def classify_conversation(name: str, summary: str, messages_text: str) -> str:
    """Route a conversation to the best Codex based on keywords."""
    text = f"{name} {summary} {messages_text}".lower()

    for codex, keywords in ROUTE_RULES:
        for kw in keywords:
            if kw.lower() in text:
                return codex

    return "claude"  # default fallback


def classify_project(name: str) -> str:
    """Route a project to its best Codex."""
    name_lower = name.lower()
    for pattern, codex in PROJECT_ROUTES.items():
        if pattern in name_lower:
            return codex
    return "claude"


def sanitize_filename(name: str) -> str:
    """Turn a conversation name into a safe filename."""
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'[-\s]+', '-', name).strip('-')
    return name[:80]


def format_timestamp(ts: str) -> str:
    """Parse ISO timestamp to readable format."""
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d %H:%M UTC')
    except Exception:
        return ts


def conversation_to_markdown(conv: dict) -> str:
    """Convert a Claude conversation dict to a markdown document."""
    name = conv.get("name", "Untitled")
    uuid = conv.get("uuid", "unknown")
    summary = conv.get("summary", "")
    created = format_timestamp(conv.get("created_at", ""))
    updated = format_timestamp(conv.get("updated_at", ""))
    messages = conv.get("chat_messages", [])

    lines = [
        f"# {name}",
        f"",
        f"**Source:** claude.ai export",
        f"**UUID:** {uuid}",
        f"**Created:** {created}",
        f"**Updated:** {updated}",
        f"**Messages:** {len(messages)}",
    ]

    if summary:
        lines.append(f"**Summary:** {summary}")

    lines.extend(["", "---", ""])

    for i, msg in enumerate(messages):
        sender = msg.get("sender", "unknown")
        text = msg.get("text", "")
        created = format_timestamp(msg.get("created_at", ""))

        # Skip empty messages
        if not text.strip():
            continue

        # Format attachments
        attachments = msg.get("attachments", []) or []
        files = msg.get("files", []) or []

        label = "User" if sender == "human" else "Assistant"

        lines.append(f"## {label}")
        if created:
            lines.append(f"*{created}*")
        lines.append("")

        # Check for code blocks or other content structure
        for block in msg.get("content", []):
            block_type = block.get("type", "text")
            if block_type == "text":
                block_text = block.get("text", "")
                if block_text:
                    lines.append(block_text)

        # Add attachments info
        for att in attachments:
            att_type = att.get("type", "unknown")
            att_name = att.get("name", "")
            if att_name:
                lines.append(f"\n*[Attached: {att_name} ({att_type})]*\n")

        for f in files:
            f_name = f.get("name", "unknown")
            f_type = f.get("type", "")
            if f_name:
                lines.append(f"\n*[File: {f_name} ({f_type})]*\n")

        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def safe_write(path: str, content: str) -> None:
    """Write content, creating directories as needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def get_existing_uuids(codex_dir: str) -> set:
    """Scan existing Claude imports and return set of UUIDs already imported."""
    uuids = set()
    if not os.path.isdir(codex_dir):
        return uuids
    for root, _, files in os.walk(codex_dir):
        for f in files:
            if f.endswith(".md"):
                path = os.path.join(root, f)
                try:
                    with open(path) as fh:
                        for line in fh:
                            if line.startswith("**UUID:**"):
                                uuid = line.replace("**UUID:**", "").strip()
                                if uuid:
                                    uuids.add(uuid)
                                break
                except Exception:
                    continue
    return uuids
