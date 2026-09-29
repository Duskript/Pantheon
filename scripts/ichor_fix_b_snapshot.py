#!/usr/bin/env python3
"""Surgical snapshot of the tables Fix B mutates (relationships.weight)."""
import os
import sqlite3
import time

OUT = f"/home/konan/backups/ichor-fixB-surgical-{time.strftime('%Y%m%d-%H%M%S')}.db"
src = sqlite3.connect("/home/konan/.hermes/ichor.db")
dst = sqlite3.connect(OUT)

for table in ("relationships", "entities"):
    schema = src.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not schema:
        print("no schema for", table)
        continue
    cols = [r[1] for r in src.execute(f"PRAGMA table_info({table})")]
    dst.execute(schema[0])
    rows = src.execute(f"SELECT * FROM {table}").fetchall()
    dst.executemany(
        f"INSERT INTO {table} VALUES ({','.join('?' * len(cols))})", rows
    )
    print("copied", table, len(rows))

dst.commit()
dst.close()
src.close()
print("SNAPSHOT:", OUT, os.path.getsize(OUT), "bytes")

# baseline for the Fix B acceptance: count of edges at exactly 0.0
src = sqlite3.connect("file:/home/konan/.hermes/ichor.db?mode=ro", uri=True)
zeroed = src.execute("SELECT COUNT(*) FROM relationships WHERE weight = 0.0").fetchone()[0]
total = src.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
print(f"BASELINE zeroed={zeroed} total={total}")
src.close()
