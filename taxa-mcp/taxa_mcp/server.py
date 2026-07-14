"""Taxa MCP server entry point.

This is the stdio MCP server that any AI agent (Hermes, Claude Code,
Cursor, Copilot, etc.) can connect to for citation-grade US tax research.

Tools exposed:
    - taxa_research(query: str) -> TaxResearchResult
        Natural language tax question. Returns verdict + rule + application
        + citations, all grounded in the Codex-Tax-US corpus.

    - taxa_cite(code: str) -> TaxCitationResult
        Exact lookup of an IRC section (e.g. "199A") or CFR section
        (e.g. "1.162-1"). Returns the full text with metadata.

    - taxa_history(citation: str) -> TaxHistoryResult  (Phase 2)
        Citator: what cites what, what overrules what. Powered by Ichor's
        entity graph.

Resource URIs:
    - taxa://irc/<num>       — e.g. taxa://irc/199A
    - taxa://cfr/<num>       — e.g. taxa://cfr/1.162-1

Usage from an MCP client:
    Add to your MCP config:
        {
            "mcpServers": {
                "taxa": {
                    "command": "taxa-mcp",
                    "args": []
                }
            }
        }

For now (Phase 1 prototype), this server uses local Athenaeum
filesystem lookups + LLM synthesis. Phase 2 will add CourtListener
integration for Tax Court opinions.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# MCP SDK imports
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent, Resource, Prompt
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False


# Default Athenaeum location
ATHENAEUM_ROOT = Path(os.environ.get("ATHENAEUM_ROOT", Path.home() / "athenaeum"))
CODEX_ROOT = ATHENAEUM_ROOT / "Codex-Tax-US"
IRC_DIR = CODEX_ROOT / "irc"
CFR_DIR = CODEX_ROOT / "cfr"


def make_irc_filename(section_num: str) -> str:
    """'199A' -> 'irc/§199A.md'"""
    safe = re.sub(r"[^A-Za-z0-9.\-]", "_", section_num)
    safe = re.sub(r"_+", "_", safe).strip("_")
    return f"irc/§{safe}.md"


def make_cfr_filename(section_num: str) -> str:
    """'1.162-1' -> 'cfr/§1.162-1.md'"""
    safe = re.sub(r"[^A-Za-z0-9.\-]", "_", section_num)
    safe = re.sub(r"_+", "_", safe).strip("_")
    return f"cfr/§{safe}.md"


def parse_citation(code: str) -> tuple[str, str]:
    """Parse a citation like '§199A' or '1.162-1' into (kind, section_num).

    Heuristics:
        - If it contains a dot, it's a CFR section (e.g. "1.162-1")
        - If it's a plain number, it's an IRC section
        - If it has a "§" prefix, strip it
    """
    code = code.strip()
    if code.startswith("§"):
        code = code[1:]
    if code.startswith("26 USC ") or code.startswith("26 U.S.C. "):
        code = code.split("§", 1)[-1].strip()
    if code.startswith("26 CFR ") or code.startswith("26 C.F.R. "):
        code = code.split("§", 1)[-1].strip()
    if "." in code:
        return ("cfr", code)
    return ("irc", code)


def read_section(code: str) -> dict | None:
    """Read a tax section from the codex. Returns None if not found."""
    kind, section_num = parse_citation(code)
    if kind == "irc":
        path = CODEX_ROOT / make_irc_filename(section_num)
    else:
        path = CODEX_ROOT / make_cfr_filename(section_num)

    if not path.exists():
        return None

    text = path.read_text()
    # Parse YAML frontmatter
    frontmatter: dict[str, str] = {}
    body = text
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end > 0:
            fm_text = text[4:end]
            body = text[end + 5:]
            for line in fm_text.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    frontmatter[k.strip()] = v.strip().strip('"')

    return {
        "kind": kind,
        "section_num": section_num,
        "citation": frontmatter.get("citation", f"{'26 U.S.C.' if kind == 'irc' else '26 CFR'} § {section_num}"),
        "heading": frontmatter.get("heading", ""),
        "source_url": frontmatter.get("source", ""),
        "frontmatter": frontmatter,
        "body": body.strip(),
    }


def keyword_search(query: str, max_results: int = 10) -> list[dict]:
    """Simple keyword search across the codex.

    This is the Phase 0 baseline. Phase 0.6 will wire this through
    Ichor's FTS5 backend for proper ranking + citation boosting.

    For now, we do substring matching on each section's body.
    """
    # Normalize query terms
    terms = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 2]
    if not terms:
        return []

    results: list[tuple[float, dict]] = []
    # Score: sum of term frequencies (TF), with a small bonus for term
    # coverage (number of distinct terms that appear at least once).
    for md_file in list(IRC_DIR.glob("§*.md")) + list(CFR_DIR.glob("§*.md")):
        try:
            text = md_file.read_text().lower()
        except Exception:
            continue
        # Skip frontmatter for body search
        body_lower = text
        if text.startswith("---\n"):
            end = text.find("\n---\n", 4)
            if end > 0:
                body_lower = text[end + 5:]
        # Length-normalized scoring: log(1 + TF) divided by log(1 + length/1000)
        # This is a poor-man's BM25: rewards term density, not raw counts.
        # A 5,000-char section that mentions "deduction" 50 times beats a
        # 50,000-char section that mentions it 200 times.
        import math
        body_len = max(len(body_lower), 1)
        tf_total = 0.0
        terms_matched = 0
        for t in terms:
            count = body_lower.count(t)
            if count > 0:
                tf_total += math.log1p(count)
                terms_matched += 1
        if tf_total == 0:
            continue
        # Length penalty: shorter sections get a multiplier boost
        length_factor = 1.0 / math.log1p(body_len / 1000.0)
        # Coverage bonus: more distinct terms matched = higher rank
        coverage = terms_matched / len(terms) if terms else 0
        score = tf_total * length_factor * (1.0 + coverage)
        # Pull the citation from the frontmatter
        try:
            raw = md_file.read_text()
            if raw.startswith("---\n"):
                end = raw.find("\n---\n", 4)
                fm = raw[4:end]
                citation = ""
                for line in fm.splitlines():
                    if line.startswith("citation:"):
                        citation = line.split(":", 1)[1].strip().strip('"')
                        break
            else:
                citation = md_file.stem
        except Exception:
            citation = md_file.stem
        # Get first 500 chars of body as snippet
        snippet_end = min(500, len(body_lower))
        results.append((score, {
            "citation": citation,
            "file": str(md_file.relative_to(CODEX_ROOT)),
            "score": score,
            "snippet": body_lower[:snippet_end],
        }))

    results.sort(key=lambda x: -x[0])
    return [r[1] for r in results[:max_results]]


# ----- MCP Tool Handlers -----

async def tool_research(query: str) -> list[dict[str, Any]]:
    """Handle the taxa_research MCP tool.

    1. Run keyword search across the codex
    2. Return the top results with citations and snippets
    3. (Phase 1.1) Pass to LLM for synthesis: verdict + rule + application
    """
    matches = keyword_search(query, max_results=10)
    result = {
        "query": query,
        "result_count": len(matches),
        "matches": matches,
        "note": "Phase 1 prototype: keyword search only. Phase 1.1 will add LLM synthesis layer.",
    }
    return [{"type": "text", "text": json.dumps(result, indent=2)}]


async def tool_cite(code: str) -> list[dict[str, Any]]:
    """Handle the taxa_cite MCP tool.

    Returns the full text of a specific IRC or CFR section.
    """
    section = read_section(code)
    if section is None:
        return [{"type": "text", "text": json.dumps({
            "error": f"Section not found: {code}",
            "hint": "Try §<num> for IRC, or 1.<sub>-<sub> for CFR. E.g. '199A' or '1.162-1'.",
        }, indent=2)}]

    return [{"type": "text", "text": json.dumps(section, indent=2)}]


# ----- MCP Server Setup -----

def build_server() -> "Server":
    """Build and return the configured MCP server instance."""
    if not MCP_AVAILABLE:
        raise RuntimeError(
            "mcp package not installed. Run: pip install mcp"
        )

    server = Server("taxa-mcp")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="taxa_research",
                description=(
                    "Research a US tax question. Returns matching IRC sections "
                    "and Treasury Regulations with citations and snippets. "
                    "Use for natural language tax queries like 'QBI deduction "
                    "phaseout for 2026' or 'what deductions are available for "
                    "heavy equipment'."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural language tax research question",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="taxa_cite",
                description=(
                    "Look up a specific IRC or CFR section by number. "
                    "Returns the full text with citation metadata. "
                    "Examples: '199A', '§162', '1.162-1', '26 CFR 1.162-1'."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "Section number, optionally prefixed with § or '26 CFR'/'26 USC'",
                        },
                    },
                    "required": ["code"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[dict[str, Any]]:
        if name == "taxa_research":
            return await tool_research(arguments["query"])
        elif name == "taxa_cite":
            return await tool_cite(arguments["code"])
        else:
            return [{"type": "text", "text": f"Unknown tool: {name}"}]

    @server.list_resources()
    async def list_resources() -> list[Resource]:
        # Phase 1 prototype: don't enumerate all 8,360 resources.
        # Real implementation: return top-level codex markers.
        return [
            Resource(
                uri="taxa://irc/§199A",
                name="IRC §199A — Qualified business income deduction",
                mimeType="text/markdown",
                description="Example: open the §199A page directly",
            ),
            Resource(
                uri="taxa://cfr/§1.162-1",
                name="26 CFR §1.162-1 — Business expenses",
                mimeType="text/markdown",
                description="Example: open the §1.162-1 page directly",
            ),
        ]

    @server.read_resource()
    async def read_resource(uri: str) -> str:
        # taxa://irc/<num> or taxa://cfr/<num>
        if uri.startswith("taxa://irc/"):
            code = uri[len("taxa://irc/"):]
        elif uri.startswith("taxa://cfr/"):
            code = uri[len("taxa://cfr/"):]
        else:
            return f"Unknown URI scheme: {uri}"

        section = read_section(code)
        if section is None:
            return f"Section not found: {code}"
        return section["body"]

    return server


async def main() -> None:
    """Run the MCP server on stdio."""
    if not MCP_AVAILABLE:
        sys.stderr.write(
            "ERROR: mcp package not installed. Run: pip install mcp\n"
        )
        sys.exit(1)

    if not CODEX_ROOT.exists():
        sys.stderr.write(
            f"WARNING: Codex-Tax-US not found at {CODEX_ROOT}\n"
            f"Set ATHENAEUM_ROOT env var or run: python -m taxa_mcp.ingest.codex\n"
        )

    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main_sync() -> None:
    """Sync entry point for setuptools script wrapper."""
    import asyncio
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()