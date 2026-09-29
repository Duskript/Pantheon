#!/usr/bin/env python3
"""Recon for the ichor relational-recall fix thread: what's live, what's stale."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

DBS = ["/home/konan/.hermes/ichor.db", "/home/konan/athenaeum/ichor.db"]


def ro(db):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def rows(c, sql, args=()):
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    except Exception as e:  # noqa: BLE001
        return [{"error": f"{type(e).__name__}: {e}"}]


for db in DBS:
    p = Path(db)
    if p.exists():
        print(f"DB {db}  size={p.stat().st_size/1e6:.1f}MB  mtime={time.ctime(p.stat().st_mtime)}")
    else:
        print(f"DB {db}  MISSING")

DB = "/home/konan/.hermes/ichor.db"
c = ro(DB)

print("\n== tables ==")
tabs = [r["name"] for r in rows(c, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print(" ", ", ".join(tabs))

for t in ("l2_scenarios", "relationships", "entities", "extraction_log", "observations", "cold_events"):
    if t not in tabs:
        print(f"\n!! {t} absent")
        continue
    cols = [r["name"] for r in rows(c, f"PRAGMA table_info({t})")]
    print(f"\n== {t} cols ==\n  {cols}")
    print(f"  count = {rows(c, f'SELECT COUNT(*) c FROM {t}')[0]}")

print("\n== l2_scenarios state ==")
for r in rows(c, "SELECT COUNT(*) n, MAX(last_seen) mx, MIN(last_seen) mn FROM l2_scenarios"):
    print(" ", r)
for r in rows(c, "SELECT * FROM l2_scenarios ORDER BY last_seen DESC LIMIT 2"):
    print("  newest:", {k: str(v)[:100] for k, v in r.items()})

print("\n== empty active summaries ==")
print(" ", rows(c, "SELECT COUNT(*) c FROM entities WHERE status='active' AND (summary IS NULL OR TRIM(summary)='')"))
print(" == zero-weight edges ==")
print(" ", rows(c, "SELECT COUNT(*) c FROM relationships WHERE weight = 0.0"))
print(" == provenance histogram ==")
for r in rows(c, "SELECT provenance, COUNT(*) c FROM relationships GROUP BY provenance ORDER BY c DESC LIMIT 10"):
    print("  ", r)

print("\n== recent extraction_log ==")
for r in rows(c, "SELECT * FROM extraction_log ORDER BY rowid DESC LIMIT 3"):
    print("  ", {k: str(v)[:90] for k, v in r.items()})
c.close()
