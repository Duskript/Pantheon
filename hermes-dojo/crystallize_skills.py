#!/usr/bin/env python3
"""
Hermes Dojo Skill Crystallization Engine
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
DOJO_DIR = Path.home() / "pantheon" / "hermes-dojo"

def main():
    candidates = find_candidates()
    
    for candidate in candidates:
        if create_skill(candidate):
            print(f"✓ {candidate['subject']}")

def find_candidates() -> list:
    path = Path(HERMES_HOME) / "ichor.db"
    if not path.exists():
        return []
    conn = sqlite3.connect(str(path))
    try:
        cursor = conn.execute("SELECT id, subject, raw_text, god_name, event_type, importance FROM ichor_events")
        rows = cursor.fetchall()
    finally:
        conn.close()
    return rows

def create_skill(candidate: tuple) -> bool:
    skill_name = candidate[2].replace("_", "-").title()
    skill_path = DOJO_DIR / "skills" / skill_name / f"{skill_name}.md"
    
    if not skill_path.exists():
        print(f"Creating: {skill_name}")
        with open(skill_path, "w") as f:
            f.write(f"# {skill_name}\n")
            f.write(f"God: Hermes\n")
            f.write(f"Importance: High\n")
            f.write(f"Pattern: {candidate[3][:150]}\n")
        return True
    return False

if __name__ == "__main__":
    main()
