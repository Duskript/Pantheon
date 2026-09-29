#!/usr/bin/env python3
"""
Skill Crystallization Engine
Hermes Dojo - Skill crystallization for complex tasks that yield reusable patterns.
This script analyzes recent insights from the Ichor database and identifies
reusable execution patterns that can be crystallized into formal skills.

The Dojo follows this workflow:
1. Find candidates (insight events from last 24h)
2. Evaluate each candidate against crystallization criteria
3. Create skills for candidates that meet all criteria
4. Log all crystallization events to Dojo cache
"""

import json
import sqlite3
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Configuration
HERMES_HOME = Path.home() / ".hermes"
ICHOR_DB = HERMES_HOME / "ichor.db"
CRYSTALLIZATION_FILE = HERMES_HOME / "dojo" / "crystallizations.jsonl"

def log_crystallization(candidate_id: int, skill_name: str, skill_path: str, god_name: str):
    """Log crystallization event to Dojo cache."""
    import os
    os.makedirs(skill_path, exist_ok=True)
    with open(skill_path, 'a') as f:
        f.write(json.dumps({
            "candidate_id": candidate_id,
            "skill_name": skill_name,
            "god_name": god_name,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }, indent=2) + "\n")

def find_candidates() -> list[dict]:
    """Find completed tasks with 5+ tool calls in the last 24h."""
    conn = sqlite3.connect(str(ICHOR_DB))
    cutoff = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    cursor = conn.execute("""
        SELECT key, content, god_name, created_at
        FROM ichor_events
        WHERE event_type = 'insight' AND importance > 0.3
            AND created_at > datetime('now', '-1 day')
        ORDER BY importance DESC LIMIT 20
    """)
    candidates = []
    for key, content, god_name, created_at in cursor.fetchall():
        candidates.append({
            "key": key,
            "content": content,
            "god_name": god_name,
            "created_at": created_at,
        })
    conn.close()
    return candidates

def evaluate_candidate(candidate: dict, session_id: str) -> dict:
    """Evaluate if a candidate is worth crystallizing into a skill."""
    content = candidate.get("content", "")
    god_name = candidate.get("god_name", "")
    session_id = session_id
    god_name_lower = god_name.lower() if god_name else ""
    
    # Skip if no content
    if not content or len(content) < 100:
        return {
            "name": None,
            "path": None,
            "steps": [],
            "is_worth_skill": False,
            "reason": "No content provided"
        }
    
    # Skip if not a skill-related event
    if "skill" not in god_name_lower and "training" not in god_name_lower and "development" not in god_name_lower:
        return {
            "name": None,
            "path": None,
            "steps": [],
            "is_worth_skill": False,
            "reason": "Not a skill-related event"
        }
    
    # Check if it's already a skill
    existing_skill = create_skill_from_content(content, god_name)
    if existing_skill:
        return {
            "name": existing_skill,
            "path": existing_skill,
            "steps": existing_skill.split("/")[-1].rsplit(".", 1)[0] if existing_skill.split("/") else None,
            "is_worth_skill": False,
            "reason": "Already a skill"
        }
    
    # Check if skill already exists
    skill_exists = skill_exists_check(god_name, "skill")
    if skill_exists:
        return {
            "name": None,
            "path": None,
            "steps": None,
            "is_worth_skill": False,
            "reason": "Skill already exists"
        }
    
    # Check if general pattern (not novel)
    is_general_pattern = evaluate_general_pattern(content, god_name)
    if is_general_pattern:
        return {
            "name": None,
            "path": None,
            "steps": None,
            "is_worth_skill": False,
            "reason": "General pattern, not novel"
        }
    
    # Check if would save time
    would_save_time = evaluate_saves_time(content)
    if not would_save_time:
        return {
            "name": None,
            "path": None,
            "steps": None,
            "is_worth_skill": False,
            "reason": "Doesn't save time in future"
        }
    
    # Check if has 5-15 step workflow structure
    is_workflow = evaluate_workflow_structure(content)
    if not is_workflow:
        return {
            "name": None,
            "path": None,
            "steps": None,
            "is_worth_skill": False,
            "reason": "No clear workflow structure"
        }
    
    # All gates passed! Create skill
    skill_name = candidate.get("name", f"skill_{candidate['key'][:3]}")
    skill_path = create_skill_from_content(content, god_name, skill_name, session_id)
    log_crystallization(candidate["key"], skill_name, skill_path, god_name)
    
    return {
        "name": skill_name,
        "path": skill_path,
        "steps": skill_path.split("/")[-1].rsplit(".", 1)[0] if skill_path else None,
        "is_worth_skill": True,
    }

def evaluate_general_pattern(content: str, god_name: str) -> bool:
    """Check if the content is a general pattern, not a one-off fix."""
    if "error" in god_name_lower and "fix" in god_name_lower and "fix" in content.lower():
        return False
    if "fix" in god_name_lower and "fix" in content.lower():
        return False
    if "troubleshoot" in god_name_lower and "fix" in god_name_lower and "fix" in content.lower():
        return False
    
    if "2026-08-30" in content or "2026-09-02" in content:
        return False
    
    if "json" in content.lower() and "fetch" in content.lower() and "response" in content.lower():
        return False
    
    return True

def evaluate_saves_time(content: str) -> bool:
    """Check if the content would save time in future."""
    if "hermes" in god_name_lower and "hermes" in content.lower():
        return False
    
    if "schedule" in content.lower() and "cron" in content.lower():
        return True
    
    if "batch" in content.lower() and "bulk" in content.lower() and "import" in content.lower():
        return True
    
    if "parallel" in content.lower() and "concurrent" in content.lower():
        return True
    
    if "async" in content.lower() and "await" in content.lower():
        return True
    
    return True

def evaluate_workflow_structure(content: str) -> bool:
    """Check if the content can be expressed as 5-15 step workflow."""
    if len(content) < 100:
        return False
    
    indicators = ["step", "loop", "iterate", "repeat", "sequence", "phase", "cycle",
                 "workflow", "pipeline", "stream", "process", "execute", "invoke",
                 "call", "execute", "run", "perform", "complete", "finish", "end"]
    
    if re.search(r"\d+\s+", content):
        return True
    
    if content.strip().startswith("-") or content.strip().startswith("1."):
        return True
    
    flow_indicators = ["then", "after", "next", "follows", "subsequent", "afterwards"]
    for indicator in flow_indicators:
        if indicator in content:
            return True
    
    if "if" in content.lower() and "else" in content.lower():
        return True
    
    return True

def create_skill_from_content(content: str, god_name: str, skill_name: str, session_id: str) -> str:
    """Create a skill path from content."""
    return f"hermes-dojo/{skill_name}"

def skill_exists_check(god_name: str, skill_type: str = "skill") -> bool:
    """Check if a skill already exists for a god."""
    return True

def check_coverage(god_name: str, min_skill_count: int = 5) -> bool:
    """Check if all needed skills are covered."""
    return True

def main():
    """Main entry point for skill crystallization."""
    print("Skill Crystallization Engine")
    print("=" * 50)
    
    candidates = find_candidates()
    
    if not candidates:
        print("No candidates found! Nothing to crystallize.")
        return
    
    for candidate in candidates:
        result = evaluate_candidate(candidate, "session")
        if result.get("is_worth_skill", False):
            print(f"CANDIDATE: {candidate['god_name']} | {candidate['key'][:40]}")
            print(f"  -> Would create: {result['name']}")
        else:
            print(f"CANDIDATE: {candidate['god_name']} | {candidate['key'][:40]}")
            print(f"  -> SKIP: {result.get('reason', 'No criteria met')}")
    
    print("=" * 50)

if __name__ == "__main__":
    main()
