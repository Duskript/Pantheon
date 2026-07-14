#!/usr/bin/env python3
"""Build portable god bundles for sharing via Nextcloud."""

import json
import os
import shutil
import tarfile
import tempfile
from datetime import datetime

HOME = os.path.expanduser("~")
PROFILES_DIR = os.path.join(HOME, ".hermes", "profiles")
PANTHEON_DIR = os.path.join(HOME, "pantheon")
OUTPUT_DIR = os.path.join(PANTHEON_DIR, "god-exports")
NOW = datetime.now().strftime("%Y%m%d")

GODS = [
    {
        "id": "iris",
        "name": "Iris",
        "description": "God of UI/UX Design & Theoforge Web Fleet",
        "model": "MiniMax-M3",
        "tags": ["design", "ui", "ux", "accessibility", "web"],
        "color": "#8B5CF6",
    },
    {
        "id": "rheta",
        "name": "Rheta",
        "description": "God of Copywriting, Rhetoric, and Persuasion",
        "model": "deepseek-v4-flash",
        "tags": ["copywriting", "marketing", "persuasion", "compliance"],
        "color": "#EC4899",
    },
    {
        "id": "marvin",
        "name": "Marvin",
        "description": "Master Coder — engineering, architecture, code review",
        "model": "deepseek-v4-pro",
        "tags": ["coding", "engineering", "architecture", "code-review"],
        "color": "#60A5FA",
    },
    {
        "id": "apollo",
        "name": "Apollo",
        "description": "God of Creative Work — lyrics, poetry, songwriting, narrative",
        "model": "deepseek-v4-flash",
        "tags": ["creative", "lyrics", "poetry", "songwriting"],
        "color": "#F5C542",
    },
    {
        "id": "caduceus",
        "name": "Caduceus",
        "description": "Physician-God — medical research, scheduling, health guidance",
        "model": "deepseek-v4-flash",
        "tags": ["medical", "health", "research", "scheduling"],
        "color": "#34D399",
    },
]

EXCLUDED_SKILL_PREFIXES = ("apple", "inference-sh", "gifs", "gaming", "design",)
AUTO_EXCLUDED_FILES = {".env", "auth.json", "gateway_state.json", "gateway.lock",
                       "gateway.pid", "processes.json", "state.db", "state.db-shm",
                       "state.db-wal", "kanban.db", "response_store.db", "messaging.db",
                       "models_dev_cache.json", "ollama_cloud_models_cache.json",
                       "provider_models_cache.json", "context_length_cache.yaml",
                       ".restart_last_processed.json", ".skills_prompt_snapshot.json",
                       ".update_check", "channel_directory.json"}
AUTO_EXCLUDED_DIRS = {"__pycache__", ".git", "logs", "sessions", "cron", "platforms",
                      "webui_state", "workspace", "sandboxes", "skins", "cache",
                      "checkpoints", "audio_cache", "image_cache", "hooks", "pairing",
                      "lsp", "bin", "plugins", "state", "tmp", "home", "scripts",
                      "plans", "schedules", "sessions", "messages"}

def build_god_bundle(god):
    god_id = god["id"]
    profile_dir = os.path.join(PROFILES_DIR, god_id)
    export_name = f"god-{god_id}-v1.0.0"
    export_root = os.path.join(tempfile.mkdtemp(), export_name)

    print(f"\n{'='*60}")
    print(f"Building {god['name']} ({god_id})...")
    print(f"{'='*60}")

    # Create directory structure
    os.makedirs(export_root)

    # 1. god.yaml manifest
    god_yaml = {
        "schema_version": 1,
        "id": god_id,
        "name": god["name"],
        "version": "1.0.0",
        "type": "conversational",
        "author": "Pantheon Core",
        "private": False,
        "description": god["description"],
        "model": god["model"],
        "sanctuary": "The Forge",
        "studios": [],
        "athenaeum_codex": True,
        "dependencies": [],
        "codexes": {
            "bundled": [],
            "scaffolded": [f"Codex-God-{god['name']}"]
        },
        "tags": god["tags"],
    }
    with open(os.path.join(export_root, "god.yaml"), "w") as f:
        import yaml
        yaml.dump(god_yaml, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    print("  ✅ god.yaml")

    # 2. harness.yaml (if it exists in the profile)
    harness_src = os.path.join(profile_dir, "harness.yaml")
    if os.path.isfile(harness_src):
        shutil.copy2(harness_src, os.path.join(export_root, "harness.yaml"))
        print("  ✅ harness.yaml (from profile)")
    else:
        # Create a basic one
        harness = {
            "schema_version": 1,
            "name": god["name"],
            "type": "conversational",
            "driver": "llm",
            "model": god["model"],
            "sanctuary": "The Forge",
            "identity": f"You are {god['name']}, a Pantheon god. {god['description']}.",
            "output": {"format": "natural", "log_to_vault": True},
        }
        with open(os.path.join(export_root, "harness.yaml"), "w") as f:
            yaml.dump(harness, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        print("  ✅ harness.yaml (generated)")

    # 3. SOUL.md
    soul_path = os.path.join(profile_dir, "SOUL.md")
    if os.path.isfile(soul_path):
        shutil.copy2(soul_path, os.path.join(export_root, "SOUL.md"))
        print(f"  ✅ SOUL.md ({os.path.getsize(soul_path)} bytes)")
    else:
        print("  ⚠️  No SOUL.md found")

    # 4. persona.md
    persona_path = os.path.join(profile_dir, "persona.md")
    if os.path.isfile(persona_path):
        shutil.copy2(persona_path, os.path.join(export_root, "persona.md"))
        print(f"  ✅ persona.md ({os.path.getsize(persona_path)} bytes)")
    else:
        print("  ⚠️  No persona.md found")

    # 5. profile.yaml (Hermes metadata)
    profile_yaml_path = os.path.join(profile_dir, "profile.yaml")
    if os.path.isfile(profile_yaml_path):
        shutil.copy2(profile_yaml_path, os.path.join(export_root, "profile.yaml"))
        print("  ✅ profile.yaml")

    # 6. god.json (Pantheon registry metadata)
    god_json_path = os.path.join(profile_dir, "god.json")
    if os.path.isfile(god_json_path):
        shutil.copy2(god_json_path, os.path.join(export_root, "god.json"))
        print("  ✅ god.json")

    # 7. Memories (MEMORY.md + USER.md)
    memories_dir = os.path.join(profile_dir, "memories")
    if os.path.isdir(memories_dir):
        mem_export = os.path.join(export_root, "memories")
        os.makedirs(mem_export)
        for fname in os.listdir(memories_dir):
            if fname.endswith(".md") and not fname.endswith(".lock"):
                shutil.copy2(os.path.join(memories_dir, fname), os.path.join(mem_export, fname))
        print(f"  ✅ memories/ ({len(os.listdir(mem_export))} files)")

    # 8. Skills
    skills_dir = os.path.join(profile_dir, "skills")
    if os.path.isdir(skills_dir):
        skills_export = os.path.join(export_root, "skills")
        os.makedirs(skills_export)
        count = 0
        for skill in sorted(os.listdir(skills_dir)):
            skill_path = os.path.join(skills_dir, skill)
            if os.path.isdir(skill_path) and os.path.isfile(os.path.join(skill_path, "SKILL.md")):
                shutil.copytree(skill_path, os.path.join(skills_export, skill),
                                ignore=shutil.ignore_patterns("__pycache__"))
                count += 1
        print(f"  ✅ skills/ ({count} skills)")

    # 9. Configuration (sanitized config.yaml — strip secrets)
    config_path = os.path.join(profile_dir, "config.yaml")
    if os.path.isfile(config_path):
        with open(config_path) as f:
            config_content = f.read()
        # Strip sensitive sections
        sanitized = []
        skip_sections = {"providers:", "credential_pool_strategies:"}
        in_skip = False
        for line in config_content.split("\n"):
            stripped = line.strip()
            if any(stripped.startswith(s) for s in skip_sections):
                in_skip = True
                sanitized.append(f"# {stripped}  # REDACTED for export")
                continue
            if in_skip and stripped and not stripped.startswith("#") and not line[0].isspace():
                in_skip = False
            if not in_skip:
                sanitized.append(line)
        config_export = os.path.join(export_root, "config.yaml")
        with open(config_export, "w") as f:
            f.write("\n".join(sanitized))
        # Also remove any ${VAR} references that look like secrets
        import re
        with open(config_export) as f:
            content = f.read()
        content = re.sub(r'\$\{(?!HERMES_HOME|HOME)[^}]+\}', '${REDACTED}', content)
        with open(config_export, "w") as f:
            f.write(content)
        print("  ✅ config.yaml (sanitized)")

    # 10. README.md
    readme = f"""# {god['name']}

A Pantheon god — exported {NOW}.

**Version:** 1.0.0
**Author:** Pantheon Core
**Description:** {god['description']}
**Tags:** {', '.join(god['tags'])}

## Included in this package

- SOUL.md — The god's core identity and domain
- persona.md — Voice, speech patterns, and character definition
- god.yaml — Pantheon manifest
- harness.yaml — Runtime configuration
- skills/ — Custom Hermes agent skills
- memories/ — Persistent memory and user knowledge
- config.yaml — Sanitized profile configuration

## Install

```bash
# Extract the bundle
tar xzf god-{god_id}-v1.0.0.tar.gz

# Copy to Hermes profiles
cp -r god-{god_id} ~/.hermes/profiles/{god_id}/

# Or install via Pantheon (if registered):
# pantheon-install god-{god_id}/
```

## About

{god['description']}. Part of the Pantheon — https://github.com/Duskript/Pantheon
"""
    with open(os.path.join(export_root, "README.md"), "w") as f:
        f.write(readme)
    print("  ✅ README.md")

    # Create tarball
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    tarball_name = f"god-{god_id}-v1.0.0.tar.gz"
    tarball_path = os.path.join(OUTPUT_DIR, tarball_name)

    with tarfile.open(tarball_path, "w:gz") as tar:
        tar.add(export_root, arcname=f"god-{god_id}")

    size_kb = os.path.getsize(tarball_path) / 1024
    print(f"\n📦 Created: {tarball_name} ({size_kb:.1f} KB)")

    # Cleanup temp
    shutil.rmtree(os.path.dirname(export_root))

    return tarball_path


def main():
    print("Pantheon God Bundle Builder")
    print(f"Output: {OUTPUT_DIR}")
    print(f"Date: {NOW}")
    print()

    results = []
    for god in GODS:
        try:
            path = build_god_bundle(god)
            results.append((god["name"], path, os.path.getsize(path)))
        except Exception as e:
            print(f"\n  ❌ FAILED: {e}")
            results.append((god["name"], None, 0))

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for name, path, size in results:
        status = f"{size/1024:.1f} KB" if path else "FAILED"
        print(f"  {name:12s} → {status}")

    total = sum(r[2] for r in results if r[1])
    print(f"\n  Total: {total/1024:.1f} KB")
    print(f"\nBundles ready at: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
