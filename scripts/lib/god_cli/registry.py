"""
registry.py — gods.yaml read/write operations.

Responsibilities:
- Read/write ~/pantheon/gods/gods.yaml
- gods_yaml_find(name) -> dict or None
- gods_yaml_add(manifest) -> None
- gods_yaml_remove(name) -> bool
- gods_yaml_update(name, fields) -> bool

Schema: {gods: {god_id: {display_name, role, description, capabilities, status}}}
"""

import os
import sys
from pathlib import Path

import yaml

from .defaults import GODS_YAML_PATH


def _read_gods_yaml() -> dict:
    """Read the gods.yaml file and return the parsed dict.

    Returns {gods: {}} if file doesn't exist or is empty.
    """
    if not os.path.isfile(GODS_YAML_PATH):
        # Ensure parent directory exists
        parent = os.path.dirname(GODS_YAML_PATH)
        if not os.path.isdir(parent):
            print(
                f"  Warning: Directory {parent} does not exist. Creating it.",
                file=sys.stderr,
            )
            os.makedirs(parent, exist_ok=True)
        return {"gods": {}}

    try:
        with open(GODS_YAML_PATH, "r") as f:
            data = yaml.safe_load(f) or {}
        if "gods" not in data:
            data["gods"] = {}
        return data
    except yaml.YAMLError as e:
        print(f"  Warning: Failed to parse {GODS_YAML_PATH}: {e}", file=sys.stderr)
        return {"gods": {}}


def _write_gods_yaml(data: dict) -> None:
    """Write the full gods.yaml file."""
    parent = os.path.dirname(GODS_YAML_PATH)
    os.makedirs(parent, exist_ok=True)
    with open(GODS_YAML_PATH, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    print(f"  Gods registry updated: {GODS_YAML_PATH}")


def gods_yaml_find(name: str) -> dict | None:
    """Find a god entry in gods.yaml by name (lowercase key).

    Returns the entry dict or None if not found.
    """
    data = _read_gods_yaml()
    gods = data.get("gods", {})
    key = name.lower()
    return gods.get(key)


def gods_yaml_add(manifest: dict) -> None:
    """Add a god entry to gods.yaml.

    manifest should have keys: id, name, description, type, version
    """
    data = _read_gods_yaml()
    gods = data.setdefault("gods", {})

    god_id = manifest["id"]
    name = manifest["name"]
    description = manifest.get("description", "")
    god_type = manifest.get("type", "conversational")

    entry = {
        "display_name": name,
        "role": f"{god_type.capitalize()} God of {description}",
        "description": description,
        "capabilities": [f"{god_type}_tasks"],
        "status": "active",
    }

    key = god_id.lower()
    if key in gods:
        print(f"  Updating existing gods.yaml entry for '{name}'")
        # Merge — preserve existing fields, update with new
        existing = gods[key]
        existing.update(entry)
    else:
        gods[key] = entry
        print(f"  Added '{name}' to gods.yaml")

    _write_gods_yaml(data)


def gods_yaml_remove(name: str) -> bool:
    """Remove a god from gods.yaml by name (lowercase key).

    Returns True if found and removed, False otherwise.
    """
    data = _read_gods_yaml()
    gods = data.get("gods", {})
    key = name.lower()

    if key not in gods:
        print(f"  '{name}' not found in gods.yaml")
        return False

    removed = gods.pop(key)
    _write_gods_yaml(data)
    print(f"  Removed '{removed.get('display_name', key)}' from gods.yaml")
    return True


def gods_yaml_update(name: str, fields: dict) -> bool:
    """Update specific fields in a god's gods.yaml entry.

    Returns True if found and updated, False otherwise.
    """
    data = _read_gods_yaml()
    gods = data.get("gods", {})
    key = name.lower()

    if key not in gods:
        return False

    gods[key].update(fields)
    _write_gods_yaml(data)
    return True
