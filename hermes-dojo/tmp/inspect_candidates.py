#!/usr/bin/env python3
import sqlite3, json, sys
conn = sqlite3.connect('/home/konan/.hermes/ichor.db')
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT * FROM ichor_events WHERE id IN (320898, 320899, 320900)").fetchall()
for row in rows:
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, str) and len(v) > 500:
            v = v[:500] + '...'
        print(f'{k}: {v}')
    print('---')
conn.close()
