# 2026-08-01 — pantheon-mcp.service restarted to load index-tools fix

**Decision:** Restarted `pantheon-mcp.service` (user systemd) at 08:18 MDT to pick up the uncommitted 82-line fix in `~/pantheon/pantheon-core/mcp_server.py`.

**Rationale:** `pantheon_index_status` MCP tool failed with `not enough values to unpack (expected 6, got 5)`. Root cause: service process started 2026-07-25 18:19 MDT ran a pre-fix `_pindex_import()` (5-tuple return) while `pantheon_index_status` unpacked 6 — the running process predated the fix written 2026-07-31 12:08 (uncommitted working-tree change vs commit 145c90e). Local module imports were clean; only the stale process was affected.

**Verification:** Post-restart `pantheon_index_status` returns healthy — db 8.67MB, 15,413 entries, last_indexed 2026-08-01T14:10Z (matches this cron's refresh). All 11 categories present.

**Follow-up for Hermes:** The 82-line fix (Pantheon System Index MCP tools, 6-element `_pindex_import` shape) is UNCOMMITTED in `pantheon-core/mcp_server.py`. Needs a commit (commit 145c90e "local snapshot before audit" lacks the section entirely).

**Reversibility:** Restart is non-destructive; service is Type=simple with Restart=on-failure. Old process was 7 days stale.
