#!/usr/bin/env python3
"""
Dawn Patrol — Nightly intelligence scan for the Pantheon ecosystem.

Collects new projects, papers, models, MCP servers, and tools relevant to
the Pantheon system. Outputs raw findings that the Hermes cron agent
synthesizes into a structured intelligence briefing.

Runs nightly via Hermes cron. The raw output is fed to an LLM prompt
(Thoth profile) that produces ~/athenaeum/reports/dawn-patrol/YYYY-MM-DD.md.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
import urllib.parse
import urllib.error
from datetime import date, datetime, timezone
from pathlib import Path

# ── Paths ───────────────────────────────────────────────────────────
ATHENAEUM_DIR = Path(os.environ.get("ATHENAEUM_DIR", Path.home() / "athenaeum"))
REPORT_DIR = ATHENAEUM_DIR / "reports" / "dawn-patrol"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
TODAY = date.today().isoformat()
RAW_FILE = REPORT_DIR / f"{TODAY}--raw.md"


# ── Helpers ─────────────────────────────────────────────────────────

def _fetch(url: str, timeout: int = 30) -> str | None:
    """Fetch a URL and return text content, or None on failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Pantheon-Dawn-Patrol/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"[HTTP error: {e}]"


def _sh(cmd: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() or (f"[exit {r.returncode}]" if r.returncode else "")
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return f"[{e.__class__.__name__}]"


# ── Collectors ──────────────────────────────────────────────────────

def collect_arxiv_papers() -> str:
    """Fetch recent papers from cs.AI, cs.CL, cs.IR, cs.MA."""
    categories = ["cs.AI", "cs.CL", "cs.MA", "cs.IR", "cs.SE"]
    results = []
    for cat in categories:
        url = (
            f"http://export.arxiv.org/api/query?"
            f"search_query=cat:{cat}+AND+%28abs:agent+OR+abs:memory+OR+abs:knowledge+OR+abs:RAG%29&"
            f"sortBy=submittedDate&sortOrder=descending&max_results=5"
        )
        data = _fetch(url)
        if data and not data.startswith("[HTTP error"):
            # Extract titles and summaries (crude XML parse — enough for a report)
            entries = data.split("<entry>")[1:] if "<entry>" in data else []
            for entry in entries:
                title = entry.split("<title>")[1].split("</title>")[0].strip() if "<title>" in entry else "?"
                summary = entry.split("<summary>")[1].split("</summary>")[0].strip()[:200] if "<summary>" in entry else ""
                link = entry.split("<id>")[1].split("</id>")[0].strip() if "<id>" in entry else ""
                authors = entry.count("<author>")
                results.append(f"- **[{cat}]** {title} ({authors} authors)\n  {summary}...\n  {link}")
        else:
            results.append(f"[{cat}: {data}]")
    return "\n".join(results) if results else "[No arxiv results]"


def collect_github_trending() -> str:
    """Fetch trending repos for relevant topics."""
    queries = [
        "topic:ai-agents sort:stars",
        "topic:mcp-server sort:stars",
        "topic:llm-memory sort:stars",
        "topic:knowledge-graph sort:stars",
        "pantheon+hermes+agent created:>2026-05-01",
        "topic:rag created:>2026-05-01 sort:stars",
    ]
    results = []
    for q in queries:
        encoded = urllib.parse.quote(q)
        url = f"https://api.github.com/search/repositories?q={encoded}&per_page=3&sort=updated"
        data = _fetch(url)
        if data and not data.startswith("[HTTP error"):
            try:
                body = json.loads(data)
                repos = body.get("items", [])
                if repos:
                    results.append(f"\n### Query: {q}")
                    for r in repos[:3]:
                        name = r.get("full_name", "?")
                        desc = (r.get("description") or "no description")[:120]
                        stars = r.get("stargazers_count", 0)
                        lang = r.get("language") or "?"
                        url_r = r.get("html_url", "?")
                        results.append(f"- **{name}** ({lang}, ★{stars})\n  {desc}\n  {url_r}")
                else:
                    results.append(f"\n### Query: {q}\n  [No results]")
            except json.JSONDecodeError:
                results.append(f"\n### Query: {q}\n  [JSON parse error]")
        else:
            results.append(f"\n### Query: {q}\n  [API error: {data}]")
    return "\n".join(results)


def collect_mcp_servers() -> str:
    """Check for new MCP servers from the official registry and community."""
    sources = [
        ("Official MCP Server Registry", 
         "https://raw.githubusercontent.com/modelcontextprotocol/servers/main/README.md"),
        ("Awesome MCP Servers", 
         "https://raw.githubusercontent.com/punkpeye/awesome-mcp-servers/main/README.md"),
    ]
    results = []
    for name, url in sources:
        data = _fetch(url, timeout=15)
        if data and not data.startswith("[HTTP error"):
            lines = data.splitlines()
            # Just grab headings and list items as a summary
            relevant = [l.strip() for l in lines if l.strip().startswith("- [") or l.strip().startswith("##")]
            snippet = "\n".join(relevant[:30])
            results.append(f"\n### {name}\n{snippet[:2000]}")
        else:
            results.append(f"\n### {name}\n  [Could not fetch]")
    
    # Also search via web for recent MCP announcements
    web_results = _sh("""
        curl -s "https://html.duckduckgo.com/html/?q=new+MCP+server+released+2026" |
        grep -oP 'href=\"[^\"]+\"[^>]*>([^<]+)</a>' | head -10 2>/dev/null || echo "[ddg failed]"
    """)
    if web_results and web_results != "[ddg failed]":
        results.append(f"\n### Web Search: New MCP servers\n{web_results[:1500]}")
    
    return "\n".join(results)


def collect_model_news() -> str:
    """Search for recent LLM model releases and benchmark news."""
    queries = [
        "new+LLM+model+released+2026",
        "AI+agent+framework+launch+2026",
    ]
    results = []
    for q in queries:
        data = _sh(f"""
            curl -s "https://html.duckduckgo.com/html/?q={q}" |
            grep -oP 'href=\"[^\"]+\"[^>]*>([^<]+)</a>' | head -8 2>/dev/null || echo "[failed]"
        """)
        if data and data != "[failed]":
            results.append(f"\n### Search: {q}\n{data[:1500]}")
    return "\n".join(results)


def collect_reddit() -> str:
    """Search Reddit for relevant discussions and new projects."""
    subreddits = [
        "artificial", "ArtificialIntelligence", "LocalLLaMA", 
        "MachineLearning", "AIagents", "RAG", "MCP",
        "claudeai", "OpenAI", "selfhosted",
    ]
    queries = [
        "new agent framework",
        "MCP server",
        "memory system",
        "knowledge graph",
        "best LLM",
        "Hermes agent",
    ]
    results = []
    
    for sub in subreddits:
        for q in queries:
            encoded = urllib.parse.quote(q)
            url = f"https://www.reddit.com/r/{sub}/search.json?q={encoded}&restrict_sr=1&sort=new&t=week&limit=2"
            data = _fetch(url, timeout=15)
            if data and not data.startswith("[HTTP error"):
                try:
                    body = json.loads(data)
                    posts = body.get("data", {}).get("children", [])
                    for post in posts[:2]:
                        p = post.get("data", {})
                        title = p.get("title", "?")
                        score = p.get("score", 0)
                        comments = p.get("num_comments", 0)
                        permalink = p.get("permalink", "")
                        url_r = f"https://reddit.com{permalink}"
                        results.append(f"- **r/{sub}** [{score}▲ {comments}💬] {title}\n  {url_r}")
                except (json.JSONDecodeError, KeyError):
                    pass
    
    # Also search broader Reddit for new releases
    broad_queries = [
        "new+LLM+release+2026",
        "just+released+AI+agent",
        "open+source+MCP",
    ]
    for q in broad_queries:
        url = f"https://www.reddit.com/search.json?q={q}&sort=new&t=week&limit=5"
        data = _fetch(url, timeout=15)
        if data and not data.startswith("[HTTP error"):
            try:
                body = json.loads(data)
                posts = body.get("data", {}).get("children", [])
                for post in posts[:5]:
                    p = post.get("data", {})
                    title = p.get("title", "?")
                    sub = p.get("subreddit", "?")
                    score = p.get("score", 0)
                    permalink = p.get("permalink", "")
                    url_r = f"https://reddit.com{permalink}"
                    results.append(f"- **r/{sub}** [{score}▲] {title}\n  {url_r}")
            except (json.JSONDecodeError, KeyError):
                pass
    
    return "\n".join(results) if results else "[No Reddit results]"


def collect_recent_blog_posts() -> str:
    """Fetch recent posts from AI/ML blogs."""
    blogs = [
        ("Nous Research Blog", "https://nousresearch.com/blog/"),
        ("Hermes Agent Docs", "https://hermes-agent.nousresearch.com/docs/changelog"),
        ("Anthropic", "https://www.anthropic.com/feed.xml"),
    ]
    results = []
    for name, url in blogs:
        data = _fetch(url, timeout=15)
        if data and not data.startswith("[HTTP error"):
            # Grab the first 30 lines for a preview
            lines = data.splitlines()
            snippet = "\n".join(l for l in lines[:40] if l.strip())[:1500]
            results.append(f"\n### {name}\n{snippet}")
        else:
            results.append(f"\n### {name}\n  [Could not fetch]")
    return "\n".join(results)


# ── Main ────────────────────────────────────────────────────────────

def main() -> None:
    collectors = [
        ("📄 ARXIV PAPERS", collect_arxiv_papers),
        ("🐙 GITHUB TRENDING", collect_github_trending),
        ("🔌 MCP SERVERS", collect_mcp_servers),
        ("🤖 MODEL NEWS", collect_model_news),
        ("🔴 REDDIT", collect_reddit),
        ("📰 BLOG POSTS", collect_recent_blog_posts),
    ]

    lines = [
        f"# Dawn Patrol — {TODAY}",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "Raw intelligence collected from across the ecosystem. "
        "LLM synthesis will follow to produce the briefing.",
        "",
    ]

    for header, fn in collectors:
        lines.append(f"## {header}")
        try:
            result = fn()
            lines.append(result if result else "[No data collected]")
        except Exception as e:
            lines.append(f"[Collector error: {e}]")
        lines.append("")

    raw = "\n".join(lines)
    RAW_FILE.write_text(raw)
    print(raw)


if __name__ == "__main__":
    main()
