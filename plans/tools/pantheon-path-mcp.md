# pantheon_path MCP Tool — Spec

> **Status:** Draft v1
> **Date:** 2026-07-05
> **Category:** Standard Tool
> **Path:** `~/pantheon/lib/pantheon_path.py`
> **Enforces:** `~/athenaeum/Codex-Pantheon/standards/path-conventions.md`

---

## 1. What It Is

A single MCP tool registered on the **Pantheon MCP server** (`~/pantheon/pantheon-core/mcp_server.py`) that returns the correct filesystem path for any Pantheon artifact type. Gods never construct paths manually — they ask `pantheon_path` and get the right answer.

**Not a standalone MCP server.** It's one `@mcp.tool()` added to the existing Pantheon MCP server. Every god already connects to this server — no new config, no new process.

### Implementation

```python
# ~/pantheon/pantheon-core/mcp_server.py — registration (5 lines)
from lib.pantheon_path import resolve_path

@mcp.tool()
async def pantheon_path(type: str, ...) -> dict:
    """Resolve a canonical Pantheon path for any artifact type."""
    return resolve_path(...)
```

### Implementation Module

```python
# ~/pantheon/lib/pantheon_path.py — pure path logic, ~100 lines, no MCP dependency
# Defined in its own module so it's testable standalone:
#   python3 -c "from lib.pantheon_path import resolve_path; print(resolve_path(...))"
```

## 2. Tool Definition

```python
@mcp.tool()
async def pantheon_path(
    type: str,              # "upgrade" | "feature" | "idea" | "project_idea"
                            # | "report" | "research" | "decision"
                            # | "skill" | "tool" | "plugin"
                            # | "session" | "concept" | "connection"
                            # | "cron_output" | "INDEX" | "tool_spec"
    name: str = "",          # artifact slug or name
    god: str = "",           # god name (for god-scoped types)
    category: str = "",      # sub-category (for reports, skills)
    date: str = "",          # YYYY-MM-DD (for date-keyed reports)
    create: bool = False,    # if True, ensure directory exists
) -> dict:
    """Resolve a canonical Pantheon path for any artifact type."""
```

### Returns

```json
{
    "path": "~/pantheon/plans/upgrades/conductor-mcp-step-execution/",
    "exists": true,
    "created": false,
    "index": "~/pantheon/plans/upgrades/INDEX.md",
    "url": null,
    "error": null
}
```

| Field | Type | Description |
|-------|------|-------------|
| `path` | str | Absolute resolved path (with ~ expanded) |
| `exists` | bool | Whether the file or directory exists |
| `created` | bool | True if `create=true` and the directory was made |
| `index` | str or null | Path to the parent INDEX.md (if type belongs to an INDEX'd tree) |
| `url` | str or null | Tailscale HTTP URL if applicable (for reports, dashboards) |
| `error` | str or null | Error message if type unknown or required field missing |

## 3. Resolution Rules

The tool implements the path templates from the conventions document exactly:

### 3.1 Plans & Upgrades

```
pantheon_path(type="upgrade", name="conductor-mcp-step-execution")
  → ~/pantheon/plans/upgrades/conductor-mcp-step-execution/

pantheon_path(type="feature", name="olympus-ui-auth")
  → ~/pantheon/plans/features/olympus-ui-auth/

pantheon_path(type="idea", name="mcp-standard-locations")
  → ~/pantheon/plans/ideas/mcp-standard-locations.md

pantheon_path(type="project_idea", name="craigslist-monitor")
  → ~/pantheon/project-ideas/craigslist-monitor.md

pantheon_path(type="tool_spec", name="pantheon-path-mcp")
  → ~/pantheon/plans/tools/pantheon-path-mcp.md
```

### 3.2 Reports

```
pantheon_path(type="report", god="thoth", category="dawn-patrol", date="2026-07-05")
  → ~/athenaeum/Codex-God-thoth/reports/dawn-patrol/2026-07-05.md

pantheon_path(type="report", god="thoth", category="forge", name="2026-07-weekly")
  → ~/athenaeum/Codex-God-thoth/reports/forge/2026-07-weekly.md

pantheon_path(type="report", god="kairos", category="digests", date="2026-07-04")
  → ~/athenaeum/Codex-God-kairos/reports/digests/2026-07-04.md
```

### 3.3 Research

```
pantheon_path(type="research", god="thoth", name="mcp-ecosystem-2026")
  → ~/athenaeum/Codex-God-thoth/research/mcp-ecosystem-2026/
```

### 3.4 Decisions

```
pantheon_path(type="decision", name="fastmcp3-standalone")
  → ~/pantheon/shared/decisions/fastmcp3-standalone.md

pantheon_path(type="decision", god="thoth")
  → ~/athenaeum/Codex-God-thoth/DECISIONS.md
```

### 3.5 Sessions & Knowledge

```
pantheon_path(type="session", domain="Forge", name="20260704_141620_dae393f6")
  → ~/athenaeum/Codex-Forge/sessions/20260704_141620_dae393f6.md

pantheon_path(type="concept", domain="Forge", name="sqlite-wal-mode")
  → ~/athenaeum/Codex-Forge/distilled/concepts/sqlite-wal-mode.md

pantheon_path(type="connection", domain="Pantheon", name="memory-persistence")
  → ~/athenaeum/Codex-Pantheon/distilled/connections/memory-persistence.md
```

### 3.6 Skills

```
pantheon_path(type="skill", god="thoth", category="thoth", name="thoth-dawn-patrol")
  → ~/.hermes/profiles/thoth/skills/thoth/thoth-dawn-patrol/

pantheon_path(type="skill", name="blogwatcher")
  → ~/.hermes/skills/blogwatcher/
```

### 3.7 Tools & MCP Servers

```
pantheon_path(type="tool", name="pantheon-core")
  → ~/pantheon/pantheon-core/mcp_server.py

pantheon_path(type="tool", name="ichor-gates")
  → ~/pantheon/lib/ichor_gates.py

pantheon_path(type="tool", name="ichor-mcp")
  → ~/pantheon/lib/ichor_mcp.py

pantheon_path(type="plugin", name="pantheon-core")
  → ~/.hermes/plugins/pantheon-core/

pantheon_path(type="tool", name="conductor-engine")
  → ~/pantheon/conductor/v2/engine.py

pantheon_path(type="tool", name="pantheon-path")
  → ~/pantheon/lib/pantheon_path.py
```

### 3.8 Cron

```
pantheon_path(type="cron_output", god="thoth", name="abc123", file="report.md")
  → ~/.hermes/profiles/thoth/cron/output/abc123/report.md
```

## 4. INDEX.md Auto-Update

When a new artifact is created via `pantheon_path(type=..., create=True)`, the tool SHOULD also update the parent INDEX.md:

```
# After writing a new plan at:
#   ~/pantheon/plans/upgrades/conductor-mcp-step-execution/spec.md
#
# The tool appends to:
#   ~/pantheon/plans/upgrades/INDEX.md
#
# | conductor-mcp-step-execution | Draft | 2026-07-05 | Conductor wraps step execution in MCP Tasks |
```

This ensures INDEX files stay current without manual maintenance. The implementation appends a single row to the INDEX.md table (or creates INDEX.md from a template if it doesn't exist).

## 5. Implementation Notes

- **No dependencies beyond Python 3.10+.** Pure path resolution + os.path.exists checks + optional os.makedirs.
- **~ expansion** via `Path.home().expanduser()`.
- **Validation:** unknown `type` values return `{"error": "Unknown type: 'foo'. Valid: upgrade, feature, idea, ..."}`.
- **Git-agnostic.** The tool doesn't care whether the path is tracked by git. It just resolves paths.
- **Module location:** `~/pantheon/lib/pantheon_path.py` — pure path logic, ~100 lines, no MCP dependency.
- **Registration:** `~/pantheon/pantheon-core/mcp_server.py` — one `@mcp.tool()` decorator, ~5 lines.

## 6. Acceptance Criteria

| # | Criterion | How to Verify |
|---|-----------|---------------|
| 1 | Returns correct path for every type in conventions doc | Call every type with valid args, assert path matches conventions table |
| 2 | Returns `exists: false` for nonexistent artifacts | Query a made-up name, assert exists=false |
| 3 | `create=true` creates the directory (not the file) | Call with create=true, assert os.path.isdir(path) |
| 4 | Returns error for unknown types | Call with type="nope", assert error string returned |
| 5 | Returns error for missing required fields | Call type="report" without god, assert error |
| 6 | INDEX.md auto-update append creates correct entry | Create a new artifact, verify INDEX.md has new row |
