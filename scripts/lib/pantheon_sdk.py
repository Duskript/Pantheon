"""
Pantheon God SDK — shared library for god package management.

Used by: pantheon-install, pantheon-uninstall, pantheon-list-gods, pantheon-upgrade

Every operation logs to the vault and notifies Hermes so the system
remains self-aware.
"""

import json
import os
import shutil
import sys
import yaml
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────

HOME = os.path.expanduser("~")
# Use the real home directory, not Hermes' sandboxed home
_REAL_HOME = os.environ.get("HERMES_REAL_HOME", HOME)
if _REAL_HOME != HOME and _REAL_HOME != os.path.join(HOME, ".."):
    # We're in a sandbox — use the real home
    HOME = _REAL_HOME
# Fallback: check if HOME resolves to the user's Hermes profiles and fix it
if ".hermes/profiles" in HOME:
    # Walk up to find the actual home
    parts = HOME.split("/.hermes/profiles/")
    HOME = parts[0]
PANTHEON_DIR = os.path.join(HOME, "pantheon")
REGISTRY_PATH = os.path.join(PANTHEON_DIR, "pantheon-registry.yaml")
HARNESSES_DIR = os.path.join(PANTHEON_DIR, "harnesses")
MESSAGES_DIR = os.path.join(PANTHEON_DIR, "gods", "messages")
ATHENAEUM_DIR = os.path.join(HOME, "athenaeum")
INSTALLED_DIR = os.path.join(HOME, ".pantheon", "gods")

# ── Valid Node Types (from GraphClient) ──────────────────────────────

VALID_GOD_TYPES = ["conversational", "service", "subsystem"]

# ── Schema Validation ────────────────────────────────────────────────

REQUIRED_FIELDS = ["schema_version", "id", "name", "version", "type", "description"]


def validate_manifest(package_path: str) -> dict:
    """Read and validate a god.yaml manifest. Returns parsed dict or raises."""
    manifest_path = os.path.join(package_path, "god.yaml")
    if not os.path.isfile(manifest_path):
        raise ValueError(f"god.yaml not found in {package_path}")

    with open(manifest_path, "r") as f:
        manifest = yaml.safe_load(f)

    if not isinstance(manifest, dict):
        raise ValueError("god.yaml is empty or malformed")

    for field in REQUIRED_FIELDS:
        if field not in manifest or manifest[field] is None:
            raise ValueError(f"Missing required field: {field}")

    if manifest.get("schema_version") != 1:
        raise ValueError(f"Unsupported schema_version: {manifest.get('schema_version')}. Expected 1.")

    god_type = manifest.get("type")
    if god_type not in VALID_GOD_TYPES:
        raise ValueError(f"Invalid type: {god_type}. Must be one of: {', '.join(VALID_GOD_TYPES)}")

    god_id = manifest["id"]
    if not isinstance(god_id, str) or not god_id.replace("-", "").isalnum():
        raise ValueError(f"Invalid id: {god_id}. Use lowercase alphanumeric with hyphens.")

    # Validate semver
    version = manifest.get("version", "")
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f"Invalid version: {version}. Must be semver (X.Y.Z).")

    if god_type == "conversational" and "model" not in manifest:
        raise ValueError("Conversational gods require a 'model' field.")

    return manifest


# ── Registry Operations ──────────────────────────────────────────────


def get_registry() -> list:
    """Read the pantheon-registry.yaml and return the list of god entries."""
    if not os.path.isfile(REGISTRY_PATH):
        return []
    with open(REGISTRY_PATH, "r") as f:
        data = yaml.safe_load(f) or {}
    return data.get("gods", [])


def write_registry(entries: list) -> None:
    """Write the full registry back to pantheon-registry.yaml."""
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    with open(REGISTRY_PATH, "w") as f:
        yaml.dump({"gods": entries}, f, default_flow_style=False, sort_keys=False)
    print(f"  Registry updated: {REGISTRY_PATH}")


def registry_find(entries: list, god_id: str) -> tuple:
    """Find a god in the registry list. Returns (index, entry) or (None, None)."""
    for i, entry in enumerate(entries):
        if entry.get("name", "").lower() == god_id.replace("god-", "").lower():
            return i, entry
        if entry.get("id") == god_id:
            return i, entry
    return None, None


def registry_add(manifest: dict) -> None:
    """Add a god entry to the registry."""
    harness_name = f"{manifest['id']}-base.yaml"
    entry = {
        "name": manifest["name"],
        "id": manifest["id"],
        "harness": harness_name,
        "type": manifest["type"],
        "version": manifest["version"],
        "description": manifest["description"],
    }
    if manifest.get("studios"):
        entry["studios"] = manifest["studios"]
    if manifest.get("sanctuary"):
        entry["sanctuary"] = manifest["sanctuary"]
    if manifest.get("private"):
        entry["private"] = True
    if manifest.get("author"):
        entry["author"] = manifest["author"]

    entries = get_registry()
    entries.append(entry)
    write_registry(entries)


def registry_update(god_id: str, manifest: dict) -> bool:
    """Update a god's entry in the registry. Returns True if found."""
    entries = get_registry()
    idx, existing = registry_find(entries, god_id)
    if idx is None:
        return False

    entries[idx]["version"] = manifest["version"]
    entries[idx]["description"] = manifest["description"]
    if manifest.get("studios"):
        entries[idx]["studios"] = manifest["studios"]
    if manifest.get("sanctuary"):
        entries[idx]["sanctuary"] = manifest["sanctuary"]
    if manifest.get("private"):
        entries[idx]["private"] = manifest["private"]
    if manifest.get("author"):
        entries[idx]["author"] = manifest["author"]

    write_registry(entries)
    return True


def registry_remove(god_id: str) -> bool:
    """Remove a god from the registry. Returns True if found and removed."""
    entries = get_registry()
    idx, _ = registry_find(entries, god_id)
    if idx is None:
        return False
    removed = entries.pop(idx)
    write_registry(entries)
    print(f"  Removed from registry: {removed['name']}")
    return True


# ── Package Operations ───────────────────────────────────────────────


def get_installed_path(god_id: str) -> str:
    """Get the path where a god package is installed."""
    return os.path.join(INSTALLED_DIR, god_id)


def is_installed(god_id: str) -> bool:
    """Check if a god package is installed."""
    return os.path.isdir(get_installed_path(god_id))


def copy_package(src: str, dst: str) -> None:
    """Copy a god package directory to the installed location."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst, symlinks=True)
    print(f"  Package copied to: {dst}")


def remove_package(god_id: str) -> None:
    """Remove an installed god package."""
    path = get_installed_path(god_id)
    if os.path.isdir(path):
        shutil.rmtree(path)
        print(f"  Package removed: {path}")


# ── Harness Operations ───────────────────────────────────────────────


def install_harness(god_id: str, package_path: str) -> str:
    """Copy harness.yaml to the harnesses directory. Returns the destination path."""
    src = os.path.join(package_path, "harness.yaml")
    if not os.path.isfile(src):
        raise FileNotFoundError(f"harness.yaml not found in {package_path}")

    dst = os.path.join(HARNESSES_DIR, f"{god_id}-base.yaml")
    os.makedirs(HARNESSES_DIR, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"  Harness installed: {dst}")
    return dst


def remove_harness(god_id: str) -> None:
    """Remove a god's harness file."""
    path = os.path.join(HARNESSES_DIR, f"{god_id}-base.yaml")
    if os.path.isfile(path):
        os.remove(path)
        print(f"  Harness removed: {path}")


# ── Inbox Operations ─────────────────────────────────────────────────


def create_inbox(god_id: str) -> None:
    """Create a message inbox directory for the god."""
    inbox = os.path.join(MESSAGES_DIR, god_id)
    os.makedirs(inbox, exist_ok=True)
    # Create an inbox index file
    inbox_index = os.path.join(inbox, f"{god_id}-inbox.json")
    if not os.path.isfile(inbox_index):
        with open(inbox_index, "w") as f:
            json.dump({"god_id": god_id, "messages": []}, f, indent=2)
    print(f"  Inbox created: {inbox}")


def remove_inbox(god_id: str) -> None:
    """Remove a god's inbox directory."""
    inbox = os.path.join(MESSAGES_DIR, god_id)
    if os.path.isdir(inbox):
        shutil.rmtree(inbox)
        print(f"  Inbox removed: {inbox}")


# ── Codex Operations ─────────────────────────────────────────────────


def create_codex(god_id: str, name: str) -> None:
    """Create a Codex directory for the god in the Athenaeum."""
    codex_name = f"Codex-{name}"
    codex_dir = os.path.join(ATHENAEUM_DIR, codex_name)
    if os.path.isdir(codex_dir):
        print(f"  Codex already exists: {codex_dir}")
        return

    os.makedirs(codex_dir, exist_ok=True)
    # Create INDEX.md
    index_path = os.path.join(codex_dir, "INDEX.md")
    with open(index_path, "w") as f:
        f.write(f"# {codex_name} — Index\n")
        f.write(f"Parent: [Athenaeum](../INDEX.md)\n")
        f.write(f"Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n")
        f.write(f"Knowledge domain for {name}.\n\n")
        f.write("## Subfolders\n\n")
        f.write("| Folder | Description |\n")
        f.write("|--------|-------------|\n")
        f.write("| sessions | God session logs and vault output |\n")
        f.write("| reference | Reference documents |\n")
        f.write("| archive | Archived content |\n")
    # Create subdirectories
    for sub in ["sessions", "reference", "archive"]:
        os.makedirs(os.path.join(codex_dir, sub), exist_ok=True)

    print(f"  Codex created: {codex_dir}")


def remove_codex(god_id: str, name: str, force: bool = False) -> None:
    """Remove a god's Codex directory. Requires confirmation unless forced."""
    codex_name = f"Codex-{name}"
    codex_dir = os.path.join(ATHENAEUM_DIR, codex_name)
    if not os.path.isdir(codex_dir):
        print(f"  Codex not found: {codex_dir}")
        return

    if not force:
        print(f"  WARNING: Codex directory contains data: {codex_dir}")
        print(f"  To remove, use: pantheon-uninstall {god_id} --remove-codex")
        return

    shutil.rmtree(codex_dir)
    print(f"  Codex removed: {codex_dir}")


# ── Hermes Notification ──────────────────────────────────────────────


def notify_hermes(subject: str, body: str) -> None:
    """Write a notification message to Hermes' inbox."""
    hermes_inbox = os.path.join(MESSAGES_DIR, "hermes")
    os.makedirs(hermes_inbox, exist_ok=True)

    timestamp = datetime.now(timezone.utc)
    msg_id = f"msg_{timestamp.strftime('%Y%m%d_%H%M%S_%f')}"

    message = {
        "id": msg_id,
        "from": "hephaestus",
        "to": "hermes",
        "type": "notification",
        "subject": subject,
        "body": body,
        "priority": "normal",
        "timestamp": timestamp.isoformat(),
        "read": False,
        "payload": {},
        "thread_id": None,
    }

    msg_path = os.path.join(hermes_inbox, f"{msg_id}.json")
    with open(msg_path, "w") as f:
        json.dump(message, f, indent=2)
    print(f"  Hermes notified: {msg_path}")


# ── Vault Logging ────────────────────────────────────────────────────


def log_vault_entry(
    action: str,
    god_id: str,
    details: str,
    version: str = "",
    success: bool = True,
) -> None:
    """Log a god SDK action to the vault session log."""
    # Use Codex-Pantheon sessions directory for system logs
    log_dir = os.path.join(ATHENAEUM_DIR, "Codex-Pantheon", "sessions")
    os.makedirs(log_dir, exist_ok=True)

    timestamp = datetime.now(timezone.utc)
    log_entry = {
        "timestamp": timestamp.isoformat(),
        "action": action,
        "god_id": god_id,
        "version": version,
        "details": details,
        "success": success,
        "actor": "hephaestus",
    }

    log_file = os.path.join(log_dir, f"god-sdk-{timestamp.strftime('%Y-%m')}.jsonl")
    with open(log_file, "a") as f:
        f.write(json.dumps(log_entry) + "\n")


# ── Graph Operations ─────────────────────────────────────────────────


def _get_graph_client():
    """Try to import and connect GraphClient. Returns None if unavailable."""
    try:
        sys.path.insert(0, os.path.join(PANTHEON_DIR, "pantheon-core"))
        from gods.graph_client import GraphClient

        gc = GraphClient()
        gc.connect()
        return gc
    except Exception:
        return None


def register_in_graph(god_id: str, name: str, version: str, type_: str) -> None:
    """Create a node for the god in the entity graph."""
    gc = _get_graph_client()
    if gc is None:
        print("  (GraphClient unavailable — skipping graph registration)")
        return

    try:
        gc.upsert_node(
            node_id=god_id,
            type_="entity",
            label=name,
            codex=f"Codex-{name}" if name != "Template" else "",
            metadata={"version": version, "god_type": type_, "installed_at": datetime.now(timezone.utc).isoformat()},
        )
        print(f"  Registered in graph: {god_id}")
    except Exception as e:
        print(f"  (Graph registration failed: {e})")
    finally:
        try:
            gc.close()
        except Exception:
            pass


def remove_from_graph(god_id: str) -> None:
    """Remove a god's node from the entity graph."""
    gc = _get_graph_client()
    if gc is None:
        print("  (GraphClient unavailable — skipping graph removal)")
        return

    try:
        gc.delete_node(god_id)
        print(f"  Removed from graph: {god_id}")
    except Exception as e:
        print(f"  (Graph removal failed: {e})")
    finally:
        try:
            gc.close()
        except Exception:
            pass


# ── Terminal Display ─────────────────────────────────────────────────


def print_header(text: str) -> None:
    """Print a section header."""
    print(f"\n{'─' * 50}")
    print(f"  {text}")
    print(f"{'─' * 50}")


def print_summary(god_id: str, name: str, version: str, action: str) -> None:
    """Print a summary of what was done."""
    print(f"\n  ✅ {name} v{version} — {action}")
    print(f"     ID: {god_id}")
    print(f"     Location: {get_installed_path(god_id)}")
