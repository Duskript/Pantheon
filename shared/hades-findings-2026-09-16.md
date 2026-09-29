# Hades nightly findings — 2026-09-16

Source: nightly Hades consolidation run (Hephaestus cron, 07:00 MDT).
Report: `~/athenaeum/Codex-Pantheon/reports/hades-2026-09-16.md`
Environment: Pantheon `81ba106` on `ops/pantheon-top-moves-20260812` · Python 3.14.4 · Ubuntu 26.04 LTS

Hades itself: **clean run, 0 errors, 6/6 phases + heartbeat.** The two defects below
were found while *verifying* the pipeline's downstream assumptions, not by the pipeline —
Hades' health phase does not cover either.

---

## 1. `athenaeum_search` breaks on the boolean syntax it advertises — 🟡 medium

**Where:** `pantheon-core/mcp_server.py` → `athenaeum_search()` (query builder, ~line 336-346)

**What happened:** The tool docstring/tool-description advertises "FTS5 supports prefix
wildcards (e.g. `theo*`), boolean AND/OR, phrase quotes". The builder appends `*` to every
whitespace token and joins with ` AND `, with no operator filtering. A user query containing
`AND` therefore becomes:

```
"kanban AND board"  ->  kanban* AND AND* AND board*
```

**Reproduced** against the live index (`~/.hermes/ichor.db`, read-only):

```
fts query sent -> 'kanban* AND AND* AND board*'
  -> ERROR: fts5: syntax error near "AND"
```

**Expected:** returns results for kanban + board.
**Workaround:** `kanban board` (implicit AND) works; phrase-quoted terms work (verified: 561 hits).
**Note:** the failure surfaces as an unhandled `sqlite3.OperationalError` around the MATCH
call — the `try` block only wraps the `connect()`. Worth confirming the tool's returned
shape on this path (needs the live MCP call to confirm end-user-visible error).

**Likely fix:** filter FTS5 operators (`AND`, `OR`, `NOT`, `NEAR`) out of `safe_terms` and
pass them through as operators, or wrap each term as a quoted phrase (`"term"*`).

## 2. `graph_client` `nodes_fts` is structurally broken — 🟡 medium (self-healing fallback)

**Where:** `pantheon-core/gods/graph_client.py` — FTS5 DDL (~line 121) and `search_nodes()` MATCH query (~line 247)

**What happened:** `nodes_fts` is declared as an **external-content** table
(`content='nodes', content_rowid='rowid'`) with a first column named `node_id`:

```sql
CREATE VIRTUAL TABLE nodes_fts USING fts5(
    node_id UNINDEXED, label, metadata_text,
    content='nodes', content_rowid='rowid'
);
```

External-content FTS5 resolves columns **by name** against the content table. The backing
table `nodes` has an `id` column, not `node_id`. Every MATCH therefore fails:

```
nodes rows: 49336
  query 'hades'  -> ERR: no such column: T.node_id
  query 'kanban' -> ERR: no such column: T.node_id
```

The `JOIN nodes_fts fts ON n.id = fts.node_id` in `search_nodes()` can never succeed either.

**Blast radius:** contained — `search_nodes()` catches `OperationalError` and silently falls
back to `find_nodes(label_contains=query)` (a LIKE substring match). So graph search is
**degraded, not down**: no rank ordering, no metadata text matching. `_sync_fts()` also
`INSERT`s directly into a content-external FTS table, which is not how those tables are
maintained (they need triggers or a `'rebuild'`).

**Likely fix:** either declare `nodes_fts` without `content=` (standalone FTS, keep the
explicit inserts), or rename the column to `id` and add insert/update/delete triggers plus
a one-time `INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild')`.

---

## Not filed as issues

`github-bug-report` Phase 0 says do not file unilaterally — and `pantheon-core/mcp_server.py`
currently has **82 uncommitted added lines** in the local checkout, so someone is mid-work
on exactly one of these files. Awaiting operator direction on whether to file.

## 3. God notifications are DOWN (all gods) — 🔴 high, found in passing

Discovered while trying to push the notification for these findings.

**Cause A — the helper script is corrupted.** `~/.local/bin/god-notify` symlinks to
`~/.hermes/scripts/god-notify.sh`. That file's contents are **RSS feed names**, not shell:

```
Hacker News Front Page\nLilian Weng's Blog\narXiv cs.AI\...
```

mtime **2026-08-24 07:00**, 182 bytes, mode 755. Executing it yields
`line 1: Hacker: command not found` — so the shell error is *not* command-not-found, it is
corrupted content. This is the exact failure mode documented as a pitfall in the
`pantheon-god-notifications` skill ("If `god-notify` executes unexpected non-shell text
(for example, `Hacker News Front Page`)...").

**Cause B — the Pantheon WebUI daemon is stopped, and a stranger owns the port.**

```
webui/ctl.sh status  →  ● hermes-webui — stopped   (Bound: 127.0.0.1:8787, sessions: 0)
ss -ltnp             →  0.0.0.0:8787  python (pid 2818991)   ← squatting
                        127.0.0.1:8788  uvicorn (pid 34384)  ← the dev instance
curl /api/health     →  HTTP 401 {"error":"Authentication required"} (Server: HermesWebUI/81ba106-dirty)
~/.hermes/webui/.sessions.json → 0 sessions (no cookie can be minted)
```

Same shape as the 2026-08-04 incident recorded in that skill: a stray server occupies 8787
while the real WebUI daemon is stopped, so every `/api/notifications/god` POST 401s
unauthenticated (and would 404 with a valid cookie). Corroborating evidence: the WebUI
notification store `~/.hermes/notifications.json` (255 entries) has **no entry newer than
2026-09-11** — nothing has landed in ~5 days.

**Not attempted (deliberately):** did not restart the WebUI daemon, did not repair
`god-notify.sh`, did not hand-append to `notifications.json`. All three are outside this
session's filesystem scope and/or an infra decision that belongs to the operator. The
`notification-auth-boundary` skill's instruction for this case is: record that delivery was
blocked, do not retry the unauthenticated request, continue the job.

**Remediation (for Konan, ~2 commands):**
```bash
cp ~/.hermes/skills/pantheon/pantheon-god-notifications/scripts/god-notify.sh \
   ~/.hermes/scripts/god-notify.sh && bash -n ~/.hermes/scripts/god-notify.sh
# then identify what pid 2818991 is, stop it, and start the real daemon:
bash ~/pantheon/webui/ctl.sh start
```

## Adjacent observations (informational, not defects)

- **Hades report has 2 permanently-dead columns.** `Embedded: ?` and the "Embed backfill"
  section are legacy from pre-P4a: `gods/hades/embed.py` is now an explicit no-op shim
  ("Retrieval now uses FTS5"). Cosmetic, but the nightly report will show `?` forever.
- **Duplicate nightly run.** Crontab already owns Hades (`0 7 * * * scripts/hades --save ...`);
  this agent cron runs it again ~50s later. Result: two Hermes-mailbox messages per morning
  (also seen 2026-09-14 and 2026-09-15). One of the two schedulers is redundant.
- **Stale 0-byte DB.** `~/.hermes/pantheon/ichor.db` is 0 bytes (mtime 2026-07-11) — a
  leftover; the live index is `~/.hermes/ichor.db` (6.1 GB, 2,197,407 cold_events,
  2,185,998 `memory_fts` rows, latest event 2026-09-16 13:00:38 UTC). Confirmed **not** the
  file the tool reads.
- **Possible stale per-profile index.** `~/.hermes/profiles/thoth/home/.hermes/ichor.db` is
  48 MB with `memory_fts`, last modified **2026-07-30**. If thoth's MCP server resolves
  `Path.home()` to that profile-local path, thoth's `athenaeum_search` is querying a
  ~7-week-old index. Unconfirmed — needs a check of how the MCP process is launched.
- **Disk:** `~/.hermes/ichor.db` 6.1 GB + `.bak-hindsight` 1.2 GB + `.pre-phase0a` 884 MB
  + `-wal` 358 MB ≈ 8.5 GB. Filesystem at 24% (699 GB free) — no pressure, but the two
  `.bak` files are candidates for cleanup.
