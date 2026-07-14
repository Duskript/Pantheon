"""Command-line interface for Taxa.

Direct CLI queries against the local Codex-Tax-US corpus. No MCP required.

Usage:
    taxa research "QBI deduction phaseout for 2026"
    taxa cite §199A
    taxa cite 1.162-1
    taxa --limit 5 research "home office deduction"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Re-use the server's read_section and keyword_search
from .server import read_section, keyword_search, CODEX_ROOT


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="taxa",
        description="Taxa — citation-grade US tax research from the command line",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_research = sub.add_parser("research", help="Natural language tax research")
    p_research.add_argument("query", help="The tax question to research")
    p_research.add_argument("--limit", "-n", type=int, default=10)

    p_cite = sub.add_parser("cite", help="Look up a specific section")
    p_cite.add_argument("code", help="Section number, e.g. '199A' or '1.162-1'")

    p_status = sub.add_parser("status", help="Show corpus statistics")

    args = parser.parse_args()

    if args.cmd == "status":
        if not CODEX_ROOT.exists():
            print(f"Codex not found: {CODEX_ROOT}")
            sys.exit(1)
        irc_count = len(list((CODEX_ROOT / "irc").glob("§*.md")))
        cfr_count = len(list((CODEX_ROOT / "cfr").glob("§*.md")))
        print(f"Codex: {CODEX_ROOT}")
        print(f"  IRC sections: {irc_count}")
        print(f"  CFR sections: {cfr_count}")
        print(f"  Total:        {irc_count + cfr_count}")
        return

    if args.cmd == "research":
        matches = keyword_search(args.query, max_results=args.limit)
        if not matches:
            print(f"No matches for: {args.query}")
            return
        print(f"Top {len(matches)} matches for: {args.query}\n")
        for i, m in enumerate(matches, 1):
            print(f"--- [{i}] {m['citation']} ---")
            print(f"  Score: {m['score']} matching terms")
            print(f"  File:  {m['file']}")
            print(f"  Excerpt: {m['snippet'][:200].strip()}")
            print()
        return

    if args.cmd == "cite":
        section = read_section(args.code)
        if section is None:
            print(f"Section not found: {args.code}")
            print("Try: §199A (IRC) or 1.162-1 (CFR)")
            sys.exit(1)
        print(f"=== {section['citation']} ===")
        if section["heading"]:
            print(f"Heading: {section['heading']}")
        print(f"Source:  {section['source_url']}")
        print()
        print(section["body"])
        return


if __name__ == "__main__":
    main()
