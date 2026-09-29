#!/usr/bin/env python3
"""Skill Management Module

This module provides functions for managing skills in the Hermes agent.
Skills are created, edited, patched, and deleted using skill_manage() from
the Hermes agent's tooling.

Functions:
    - skill_manage(action, name, file_path): Manually manage a skill
    - create_skill(skill_name, skill_content): Create a skill from JSON string
    - delete_skill(skill_name): Delete a skill by name
    - search_skill(skill_name): Search for a skill
    - list_skills(): List all skills in the skills directory
    - get_skill_content(skill_name): Get skill content
    - patch_skill(skill_name, old_string, new_string): Patch an existing skill
    - edit_skill(skill_name, old_string, new_string): Edit an existing skill
    - validate_skill(skill_name): Validate a skill exists
"""

from typing import Any, Dict, List, Optional
from pathlib import Path
from tools.skill_manager_tool import (
    _find_skill,
    _validate_frontmatter,
    _create_skill,
    _edit_skill,
    _patch_skill,
    _delete_skill,
)

def skill_manage(action: str, name: str, file_path: str = None) -> dict[str, Any]:
    """Manually manage a skill (for testing or when automatic crystallization fails).

    Args:
        action: One of 'create', 'edit', 'patch', 'write_file', 'delete'
        name: Name of the skill
        file_path: Path to the skills directory (optional, defaults to ~/.hermes/skills)

    Returns:
        Dict with action result
    """
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)

    skill = _find_skill(name)

    if action == 'create':
        if skill:
            return {'action': 'create', 'skill': skill}
        return {'action': 'create', 'skill': None}

    elif action == 'edit':
        if skill:
            return {'action': 'edit', 'skill': _edit_skill(skill, name)}
        return {'action': 'edit', 'skill': None}

    elif action == 'patch':
        if skill:
            return {'action': 'patch', 'skill': _patch_skill(skill, name)}
        return {'action': 'patch', 'skill': None}

    elif action == 'write_file':
        if skill:
            return {'action': 'write_file', 'skill': skill}
        return {'action': 'write_file', 'skill': None}

    elif action == 'delete':
        if skill:
            return {'action': 'delete', 'skill': skill}
        return {'action': 'delete', 'skill': None}

    return {'action': 'create', 'skill': None}

def create_skill(skill_name: str, skill_content: str = None) -> str | None:
    """Create a new skill from a JSON string."""
    Path("skills", skill_name).mkdir(parents=True, exist_ok=True)
    Path(f"skills/{skill_name}/SKILL.md").write_text(skill_content)
    return str(Path("skills", skill_name, "SKILL.md"))

def delete_skill(skill_name: str) -> bool:
    """Delete a skill by name."""
    return _delete_skill(skill_name)

def search_skill(skill_name: str) -> bool:
    """Search for a skill by name."""
    return _find_skill(skill_name)

def list_skills() -> list[str]:
    """List all skills in the skills directory."""
    return _list_skills()

def get_skill_content(skill_name: str) -> str:
    """Get the content of a skill by name."""
    return _find_skill(skill_name)

def patch_skill(skill_name: str, old_string: str, new_string: str) -> bool:
    """Patch an existing skill."""
    return _patch_skill(skill_name, old_string, new_string)

def edit_skill(skill_name: str, old_string: str, new_string: str) -> bool:
    """Edit an existing skill."""
    return _edit_skill(skill_name, old_string, new_string)

def validate_skill(skill_name: str) -> bool:
    """Validate a skill exists and is properly formatted."""
    return _validate_frontmatter(skill_name)

def _list_skills() -> list[str]:
    """List all skills in the skills directory."""
    skills_dir = Path.home() / ".hermes" / "skills"
    return sorted([f.name for f in skills_dir.iterdir() if f.is_file()])
