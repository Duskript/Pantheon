"""Taxa MCP — citation-grade US tax research as a pluggable AI service.

Public API:
    - taxa_mcp.server: MCP server entry point (stdio transport)
    - taxa_mcp.cli: command-line interface for direct queries
    - taxa_mcp.research: taxa_research tool implementation
    - taxa_mcp.cite: taxa_cite tool implementation
    - taxa_mcp.history: taxa_history tool implementation (Phase 2)
    - taxa_mcp.ingest: Phase 0 — IRC, CFR, and codex loading
    - taxa_mcp.retrieval: Ichor/Athenaeum integration layer
"""

__version__ = "0.0.1"
__author__ = "Konan Rudolph"
__license__ = "AGPL-3.0"

# Tier limits
FREE_TIER_MONTHLY_QUERIES = 100
PRO_TIER_DESCRIPTION = "Bundled with Talli subscription ($600-1,750/mo)"
ENTERPRISE_TIER_DESCRIPTION = "$199/mo or $1,999/yr, all 50 state codes"

# Data sources
IRC_RELEASE_POINT = "119-100"  # Public Law 119-100, current as of 2026
CFR_LATEST_ISSUE = "2026-06-30"

# Athenaeum codex name for tax data
CODEX_TAX_US = "Codex-Tax-US"
