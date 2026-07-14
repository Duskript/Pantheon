"""B1 backfill v2 — id-range based pagination to avoid the offset-skip bug.

The v1 used `WHERE brief='' ORDER BY id LIMIT 500 OFFSET N`. As updates
filled in briefs, the WHERE filter shrank, so OFFSET N (relative to the
shrinking set) started skipping ids.

v2 walks id ranges explicitly: get min_id and max_id, process in chunks
of 500 ids, no offset, no filter race.
"""
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, "/home/konan/pantheon")
from lib.ichor_db import auto_generate_tiers

DB = Path.home() / ".hermes" / "ichor.db"
CHUNK = 500


def backfill_table(conn, table: str, text_col: str) -> int:
    """Populate brief + outline for rows where brief is empty, by id range."""
    row = conn.execute(
        f"SELECT MIN(id) AS lo, MAX(id) AS hi, "
        f"COUNT(*) AS total, "
        f"SUM(CASE WHEN brief IS NULL OR brief = '' THEN 1 ELSE 0 END) AS need "
        f"FROM {table}"
    ).fetchone()
    lo, hi, total, need = row["lo"], row["hi"], row["total"], row["need"]
    if need == 0 or lo is None:
        print(f"  {table}: nothing to do (total={total}, need={need})")
        return 0
    print(f"  {table}: {need} of {total} need backfill (id range {lo}..{hi})")

    updated = 0
    next_id = lo
    while next_id <= hi:
        # Pull a chunk by id range; select all rows in the window, not just
        # the empty ones (we want to walk every id in the window).
        rows = conn.execute(
            f"SELECT id, {text_col}, brief FROM {table} "
            f"WHERE id >= ? AND id < ? "
            f"ORDER BY id",
            (next_id, next_id + CHUNK),
        ).fetchall()
        for r in rows:
            if r["brief"]:
                continue  # already populated
            text = r[text_col] or ""
            brief, outline = auto_generate_tiers(text)
            conn.execute(
                f"UPDATE {table} SET brief = ?, outline = ? WHERE id = ?",
                (brief, outline, r["id"]),
            )
            updated += 1
        conn.commit()
        next_id += CHUNK
        pct = min(100, int(updated * 100 / need)) if need else 100
        print(f"    {updated}/{need} ({pct}%)", end="\r", flush=True)
    print(f"    {updated}/{need} (100%) — done")
    return updated


def main() -> int:
    print(f"=== B1 backfill v2 starting on {DB} ===")
    start = time.time()
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    n_cold = backfill_table(conn, "cold_events", "raw_text")
    n_warm = backfill_table(conn, "warm_entities", "value")
    n_ref = backfill_table(conn, "reference_knowledge", "body")

    conn.close()
    elapsed = time.time() - start
    total = n_cold + n_warm + n_ref
    print(f"=== B1 backfill v2 done: {total} rows in {elapsed:.1f}s ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
