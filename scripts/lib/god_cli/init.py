"""
init.py — `god init` implementation.

Responsibilities:
- Prompt for domain/title if not provided (interactive mode)
- Validate god name format (lowercase-hyphens)
- Check for existing profile → prompt/--force handling
- Domain-to-Codex mapping lookup → suggest bundled Codexes
- Interactive Codex prompt (accept/edit/skip suggested bundled Codexes)
- Render all templates via template_engine.render()
- Dry-run mode (summary + exit)
- Create directory structure and write all files
- Create Tier 2 (scaffolded) Codex: memory.md + journal/ + INDEX.md
- Create Tier 1 (bundled) reference entries for each declared bundled Codex
- Update pantheon-registry.yaml (via pantheon_sdk.registry_add)
- Update gods.yaml (via registry.gods_yaml_add)
- Log to vault (via pantheon_sdk.log_vault_entry)
- Print formatted summary with next steps
"""

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import defaults
from . import template_engine
from . import registry

# Import pantheon_sdk (existing SDK)
sys.path.insert(0, os.path.join(defaults.PANTHEON_DIR, "scripts", "lib"))
from pantheon_sdk import (
    registry_add as sdk_registry_add,
    log_vault_entry,
    print_header,
)


RESERVED_NAMES = ["hermes", "hephaestus", "apollo", "template", "pantheon", "zeus", "athena"]


# ── Validation ────────────────────────────────────────────────────────


def validate_god_name(name: str) -> str:
    """Validate and normalize a god name.

    Must be lowercase alphanumeric with hyphens, starting with a letter.
    Returns the normalized name.
    Raises ValueError on invalid input.
    """
    name = name.strip().lower()

    if not name:
        raise ValueError("God name cannot be empty.")

    if not re.match(r'^[a-z][a-z0-9-]*$', name):
        raise ValueError(
            f"Invalid god name: '{name}'. "
            f"Use lowercase letters, numbers, and hyphens only. "
            f"Must start with a letter. Examples: asclepius, my-cool-god"
        )

    if name in RESERVED_NAMES:
        raise ValueError(f"'{name}' is a reserved god name. Choose another.")

    return name


def to_title_case(name: str) -> str:
    """Convert a lowercase-hyphen name to PascalCase.

    e.g. 'asclepius' -> 'Asclepius', 'my-cool-god' -> 'MyCoolGod'
    """
    return "".join(word.capitalize() for word in name.split("-"))


def derive_title(domain: str) -> str:
    """Derive a display title from the domain description."""
    domain = domain.strip().strip(".,!")
    words = domain.split()
    if len(words) <= 3:
        # "healing" -> "God of Healing"
        return f"God of {domain.title()}"
    else:
        # "healing and medicine" -> "God of Healing and Medicine"
        return f"God of {domain.title()}"


def derive_description(name_title: str, domain: str, god_type: str) -> str:
    """Derive a description string."""
    return f"A {god_type} god of {domain}"


# ── Existing Profile Check ────────────────────────────────────────────


def check_for_existing_profile(name: str, force: bool) -> str:
    """Check if profile exists. Returns 'fresh', 'overwrite', 'skip', or 'cancel'."""
    profile_dir = defaults.get_profile_dir(name)
    if not profile_dir.exists():
        return "fresh"

    if force:
        print(f"  ⚠️  Profile '{name}' already exists at {profile_dir}")
        print(f"     --force set: config files will be overwritten")
        print(f"     Codex data will be preserved (existing files not overwritten)")
        return "overwrite"

    print(f"  Profile '{name}' already exists at {profile_dir}")
    print(f"  Options: (o)verwrite configs, (s)kip, (c)ancel")
    try:
        choice = input("  > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "cancel"

    if choice in ('o', 'overwrite', ''):
        return "overwrite"
    elif choice in ('s', 'skip'):
        return "skip"
    else:
        return "cancel"


# ── Domain-to-Codex Interaction ───────────────────────────────────────


def resolve_bundled_codexes(
    domain: str,
    interactive: bool,
    no_suggest: bool = False,
    explicit: list[str] | None = None,
    name_title: str | None = None,
) -> list[str]:
    """Resolve the list of bundled Codexes.

    Priority:
    1. Explicit --codexes flag
    2. Domain mapping suggestions (if interactive and not --no-suggest-codexes)
    3. Empty list (no bundled Codexes)
    """
    if explicit is not None:
        return [c.strip() for c in explicit if c.strip()]

    suggested = [] if no_suggest else defaults.suggest_bundled_codexes(domain)

    if not interactive:
        return suggested

    if not suggested:
        print(f"\n  No bundled Codexes suggested for domain '{domain}'.")
        choice = input("  Would you like to add any? (y/N/edit): ").strip().lower()
        if choice in ('y', 'yes', ''):
            custom = input("  Enter Codexes (comma-separated): ").strip()
            return [c.strip() for c in custom.split(",") if c.strip()]
        elif choice == 'edit':
            custom = input("  Enter Codexes (comma-separated): ").strip()
            return [c.strip() for c in custom.split(",") if c.strip()]
        return []

    print(f"\n  Domain '{domain}' suggests the following reference Codexes:")
    for cx in suggested:
        print(f"    ✅ {cx}")
    print(f"  These contain reference knowledge that ships with your god.")

    try:
        choice = input("  Accept? (Y/n/edit): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return suggested

    if choice in ('y', 'yes', '', 'accept'):
        return suggested
    elif choice == 'edit':
        try:
            custom = input("  Enter Codexes (comma-separated): ").strip()
        except (EOFError, KeyboardInterrupt):
            return suggested
        return [c.strip() for c in custom.split(",") if c.strip()]
    else:
        return []


# ── Codex Variable Builder ────────────────────────────────────────────


def build_codex_variables(context: dict) -> dict:
    """Build template variables for codex sections in SOUL.md.

    Generates BUNDLED_CODEX_PATHS, SCAFFOLDED_CODEX_PATHS, HAS_BUNDLED_CODEXES.
    """
    bundled = context.get("bundled_codexes", [])
    scaffolded = context.get("scaffolded_codexes", ["Codex-God-" + context["NAME"]])

    # Build bundled paths section
    if bundled:
        bundled_paths = "\n".join(
            f"  - `~/athenaeum/{cx}/` — reference knowledge"
            for cx in bundled
        )
        has_bundled = "\n### Bundled Reference Codexes:"
    else:
        bundled_paths = "  (none declared)"
        has_bundled = ""

    # Build scaffolded paths
    scaffolded_paths = ", ".join(
        f"`~/athenaeum/{cx}/`" for cx in scaffolded
    )

    return {
        "BUNDLED_CODEX_PATHS": bundled_paths,
        "SCAFFOLDED_CODEX_PATHS": scaffolded_paths,
        "HAS_BUNDLED_CODEXES": has_bundled,
    }


# ── Interactive Prompting ─────────────────────────────────────────────


def prompt_for_domain() -> str:
    """Prompt the user for the god's domain/purpose. Returns the domain string."""
    print()
    try:
        domain = input("  Enter god domain/purpose (required): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n  Cancelled.")
        sys.exit(0)
    if not domain:
        print("  Domain is required.")
        return prompt_for_domain()
    return domain


def prompt_for_title(domain: str) -> str:
    """Prompt for god title, offering a default derived from domain."""
    default_title = derive_title(domain)
    print()
    try:
        title = input(f"  God title [{default_title}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n  Cancelled.")
        sys.exit(0)
    return title if title else default_title


# ── Context Building ──────────────────────────────────────────────────


def build_context(args) -> dict:
    """Build the full rendering context from args, defaults, and interactive prompts."""
    name = args.name
    domain = args.domain
    title = args.title
    interactive = not domain

    # Interactive: prompt for domain if not provided
    if not domain:
        domain = prompt_for_domain()
    if not title:
        title = derive_title(domain)

    name_title = to_title_case(name)
    description = derive_description(name_title, domain, args.type)

    # Gather defaults
    model = args.model or defaults.get_default_model()
    provider = args.provider or defaults.get_default_provider()
    author = args.author or defaults.get_author()
    user = defaults.get_user()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Build context dict
    context = {
        "name": name,
        "NAME": name_title,
        "TITLE": title,
        "DOMAIN": domain,
        "DESCRIPTION": description,
        "TYPE": args.type or "conversational",
        "MODEL": model,
        "PROVIDER": provider,
        "VERSION": "1.0.0",
        "AUTHOR": author,
        "SANCTUARY": "The Forge",
        "id": name,
        "USER": user,
        "DATE": today,
    }

    # Resolve bundled Codexes
    bundled_codexes = resolve_bundled_codexes(
        domain=domain,
        interactive=interactive,
        no_suggest=getattr(args, 'no_suggest_codexes', False),
        explicit=args.codexes,
        name_title=name_title,
    )
    scaffolded_codexes = [f"Codex-God-{name_title}"]

    context["bundled_codexes"] = bundled_codexes
    context["scaffolded_codexes"] = scaffolded_codexes

    # Build YAML-friendly lists for god.yaml
    if bundled_codexes:
        context["BUNDLED_CODEXES"] = "\n".join(
            f"    - {cx}" for cx in bundled_codexes
        )
    else:
        context["BUNDLED_CODEXES"] = "    []"

    context["SCAFFOLDED_CODEXES"] = "\n".join(
        f"    - {cx}" for cx in scaffolded_codexes
    )

    # Add dynamic codex variables for SOUL.md
    context.update(build_codex_variables(context))

    # Git Discipline — builder gods get the full section, non-builders get
    # a routing note, and unflagged gods get nothing (Soul Forge decides).
    if getattr(args, 'builder', False):
        context["GIT_DISCIPLINE"] = (
            "## Git Discipline\n"
            "As a builder god, every code change follows this workflow:\n"
            "\n"
            "**Repositories:**\n"
            "- `~/pantheon/` (origin: `Duskript/Pantheon`) — primary repo for "
            "Pantheon infrastructure, configs, SDK, and documentation\n"
            "- Upstream repos (Hermes Agent, Hermes WebUI, etc.) are only "
            "committed to when explicitly needed\n"
            "\n"
            "**Rules:**\n"
            "- **Feature branches always** — `feat/<name>` for new features, "
            "`fix/<name>` for bugs, `chore/<name>` for config/docs. "
            "Never commit to `main` directly.\n"
            "- **Commit after each logical unit** — not at end of session. "
            "Each commit message answers \"what changed and why\" in under 80 chars.\n"
            "- **No personal/private data in commits** — no user config paths, "
            "no token amounts, no private content.\n"
            "- **Ask for review before merging to `main`** — even for small "
            "fixes. Send a notification: \"This needs a look before I merge.\"\n"
            "- **Stale branches get cleaned** — after merge or abandonment, "
            "delete the branch.\n"
            "\n"
        )
    elif getattr(args, 'no_builder', False):
        context["GIT_DISCIPLINE"] = (
            "## Code Changes\n"
            "This god does not write code directly. If a task requires changes "
            "to Pantheon repositories (configs, SDK, WebUI, etc.), hand it off "
            "to Hermes with context about what needs to change and why. "
            "Hermes handles all repo operations.\n"
            "\n"
        )
    else:
        context["GIT_DISCIPLINE"] = ""

    return context


# ── Rendering ─────────────────────────────────────────────────────────


def render_all_templates(context: dict) -> dict[str, str]:
    """Render all 8 templates with the given context.

    Returns dict mapping filename -> rendered content.
    """
    templates = [
        "SOUL.md.j2",
        "persona.md.j2",
        "config.yaml.j2",
        "god.yaml.j2",
        "harness.yaml.j2",
        "INDEX.md.j2",
        "memory.md.j2",
        "journal.j2",
    ]

    rendered = {}
    for tpl in templates:
        rendered[tpl] = template_engine.render(tpl, context)

    return rendered


# ── Write Operations ──────────────────────────────────────────────────


def write_profile(name: str, rendered: dict[str, str], context: dict) -> None:
    """Write profile files to ~/.hermes/profiles/{name}/."""
    profile_dir = defaults.get_profile_dir(name)
    os.makedirs(profile_dir, exist_ok=True)

    # Map template names to output filenames
    name_title = context["NAME"]

    files = [
        ("SOUL.md.j2", "SOUL.md"),
        ("persona.md.j2", "persona.md"),
        ("config.yaml.j2", "config.yaml"),
        ("god.yaml.j2", "god.yaml"),
        ("harness.yaml.j2", "harness.yaml"),
    ]

    for tpl_key, out_name in files:
        if tpl_key in rendered:
            out_path = profile_dir / out_name
            out_path.write_text(rendered[tpl_key])
            print(f"  ✅ Created {out_path}")

    # Also write god.yaml and harness.yaml to the profile directory
    # The god.yaml is needed by pantheon-install and pantheon-build
    print(f"  Profile directory: {profile_dir}")


def write_scaffolded_codex(context: dict) -> None:
    """Create Tier 2 (scaffolded) Codex — shared brain, per-user state.

    Creates empty memory.md, journal/, and INDEX.md at
    ~/athenaeum/Codex-God-{Name}/.
    NEVER overwrites existing data.
    """
    name = context["NAME"]
    codex_dir = defaults.get_codex_dir(name)

    if codex_dir.exists():
        print(f"  ℹ️  Codex-God-{name} already exists at {codex_dir}")
        print(f"     → Creating only missing files (existing data preserved)")
    else:
        codex_dir.mkdir(parents=True, exist_ok=True)

    # Create INDEX.md
    index_path = codex_dir / "INDEX.md"
    if not index_path.exists():
        index_path.write_text(context.get("INDEX.md.j2", ""))
        print(f"  ✅ Created {index_path}")
    else:
        print(f"  ℹ️  Preserved existing {index_path}")

    # Create memory.md
    memory_path = codex_dir / "memory.md"
    if not memory_path.exists():
        memory_path.write_text(context.get("memory.md.j2", ""))
        print(f"  ✅ Created {memory_path}")
    else:
        print(f"  ℹ️  Preserved existing memory.md")

    # Create journal/ directory with TEMPLATE.md
    journal_dir = codex_dir / "journal"
    journal_dir.mkdir(exist_ok=True)
    journal_template = journal_dir / "TEMPLATE.md"
    if not journal_template.exists():
        journal_template.write_text(context.get("journal.j2", ""))
        print(f"  ✅ Created {journal_template}")

    # Create sessions, reference, archive subdirs
    for sub in ["sessions", "reference", "archive"]:
        subdir = codex_dir / sub
        subdir.mkdir(exist_ok=True)

    log_vault_entry(
        f"Codex-God-{name}",
        "created",
        f"Scaffolded Codex at {codex_dir}",
    )


def reference_bundled_codexes(context: dict) -> None:
    """Create Tier 1 (bundled) Codex reference entries.

    Bundled Codexes are read-only reference knowledge that ships with the god.
    In Phase 1, we verify they exist and create reference entries.
    """
    bundled = context.get("bundled_codexes", [])
    for codex_name in bundled:
        codex_dir = defaults.get_bundled_codex_dir(codex_name)

        if codex_dir.exists():
            print(f"  ✅ Bundled Codex {codex_name} found at {codex_dir}")
            ref_path = codex_dir / "INDEX.md"
            if ref_path.exists():
                print(f"     → INDEX.md present, Codex is valid")
        else:
            print(f"  ⚠️  Bundled Codex {codex_name} NOT found at {codex_dir}")
            print(f"     → Reference entry added to god.yaml but Codex must exist")
            print(f"     → for build/install (Phase 2) to succeed")


# ── Registry Updates ──────────────────────────────────────────────────


def update_registries(context: dict) -> None:
    """Update both pantheon-registry.yaml and gods.yaml."""
    name = context["name"]
    name_title = context["NAME"]
    version = context["VERSION"]
    god_type = context["TYPE"]
    description = context["DESCRIPTION"]
    model = context["MODEL"]
    author = context["AUTHOR"]

    # Create a manifest-like dict for registry operations
    manifest = {
        "id": name,
        "name": name_title,
        "version": version,
        "type": god_type,
        "description": description,
        "model": model,
        "author": author,
    }

    # Update pantheon-registry.yaml via SDK
    try:
        sdk_registry_add(manifest)
    except Exception as e:
        print(f"  ⚠️  Failed to update pantheon-registry.yaml: {e}")
        print(f"     Continuing with gods.yaml update...")

    # Update gods.yaml via our registry module
    try:
        registry.gods_yaml_add(manifest)
    except Exception as e:
        print(f"  ⚠️  Failed to update gods.yaml: {e}")


# ── Dry Run ────────────────────────────────────────────────────────────


def print_dry_run_summary(context: dict, rendered: dict[str, str]) -> None:
    """Print a summary of what would be created, without making changes."""
    name = context["name"]
    name_title = context["NAME"]
    domain = context["DOMAIN"]
    bundled = context.get("bundled_codexes", [])
    scaffolded = context.get("scaffolded_codexes", [])

    print()
    print(f"  ╭─ DRY RUN: {name_title} ──────────────────────────────────╮")
    print(f"  │                                                         │")
    print(f"  │  God ID:        {name:<35} │")
    print(f"  │  Display Name:  {name_title:<35} │")
    print(f"  │  Domain:        {domain:<35} │")
    print(f"  │  Type:          {context['TYPE']:<35} │")
    print(f"  │  Model:         {context['MODEL']:<35} │")
    print(f"  │  Provider:      {context['PROVIDER']:<35} │")
    print(f"  │  Author:        {context['AUTHOR']:<35} │")
    print(f"  │                                                         │")
    print(f"  │  Files to create:                                        │")
    profile_dir = defaults.get_profile_dir(name)
    print(f"  │    ~/.hermes/profiles/{name}/                  │")
    print(f"  │    ├── SOUL.md                                          │")
    print(f"  │    ├── persona.md                                       │")
    print(f"  │    ├── config.yaml                                      │")
    print(f"  │    ├── god.yaml                                         │")
    print(f"  │    └── harness.yaml                                     │")
    print(f"  │                                                         │")
    print(f"  │  Tier 2 — Scaffolded Codex:                             │")
    codex_dir = defaults.get_codex_dir(name_title)
    print(f"  │    {codex_dir}")
    print(f"  │    ├── INDEX.md                                         │")
    print(f"  │    ├── memory.md                                        │")
    print(f"  │    └── journal/TEMPLATE.md                              │")
    print(f"  │                                                         │")
    if bundled:
        print(f"  │  Tier 1 — Bundled Codexes ({len(bundled)}):                    │")
        for cx in bundled:
            cx_dir = defaults.get_bundled_codex_dir(cx)
            print(f"  │    - {cx_dir}")
    else:
        print(f"  │  Tier 1 — No bundled Codexes                          │")
    print(f"  │                                                         │")
    print(f"  │  Registries to update:                                  │")
    print(f"  │    - pantheon-registry.yaml                             │")
    print(f"  │    - gods.yaml                                          │")
    print(f"  │                                                         │")
    print(f"  ╰─────────────────────────────────────────────────────────╯")
    print()
    print(f"  Run without --dry-run to create the god profile.")
    print()


# ── Summary ────────────────────────────────────────────────────────────


def print_summary(context: dict) -> None:
    """Print a formatted summary after successful init."""
    name = context["name"]
    name_title = context["NAME"]
    domain = context["DOMAIN"]
    bundled = context.get("bundled_codexes", [])
    scaffolded = context.get("scaffolded_codexes", [])

    print()
    print(f"  ╭─ ✅ God Created: {name_title} ──────────────────────────────╮")
    print(f"  │                                                         │")
    print(f"  │  ID:          {name:<35} │")
    print(f"  │  Domain:      {domain:<35} │")
    print(f"  │  Type:        {context['TYPE']:<35} │")
    print(f"  │  Model:       {context['MODEL']:<35} │")
    print(f"  │  Sanctuary:   {context['SANCTUARY']:<35} │")
    print(f"  │                                                         │")
    print(f"  │  Profile:  ~/.hermes/profiles/{name}/")
    print(f"  │  Codex:    ~/athenaeum/Codex-God-{name_title}/")
    if bundled:
        print(f"  │  Bundled:  {', '.join(bundled):<35}")
    print(f"  │                                                         │")
    print(f"  ╰─────────────────────────────────────────────────────────╯")
    print()
    print(f"  📋 Next steps:")
    print(f"    1. Edit persona.md     → ~/.hermes/profiles/{name}/persona.md")
    print(f"       (Fill in traits, speech patterns, and character)")
    print(f"    2. Review SOUL.md      → ~/.hermes/profiles/{name}/SOUL.md")
    print(f"    3. Test with:          → hermes {name} <your-first-prompt>")
    if bundled:
        print(f"    4. Verify Codexes:     → pantheon god validate {name}")
    print()


# ── Main Init Logic ───────────────────────────────────────────────────


def run_init(args) -> None:
    """Main entry point for `pantheon god init <name>`."""
    # ── Step 1: Validate name ─────────────────────────────────────────
    name = validate_god_name(args.name)

    # ── Step 2: Build context ─────────────────────────────────────────
    context = build_context(args)

    # ── Step 3: Check for existing profile ────────────────────────────
    status = check_for_existing_profile(name, getattr(args, 'force', False))
    if status == "cancel":
        print("  Cancelled.")
        return
    if status == "skip":
        print(f"  Skipping {name} — use --force to overwrite.")
        return
    # If overwrite, set context flag
    context["_overwrite"] = (status == "overwrite")

    # ── Step 4: Render all templates (in memory) ──────────────────────
    rendered = render_all_templates(context)
    context["INDEX.md.j2"] = rendered.get("INDEX.md.j2", "")
    context["memory.md.j2"] = rendered.get("memory.md.j2", "")
    context["journal.j2"] = rendered.get("journal.j2", "")

    # ── Step 5: Dry-run mode ──────────────────────────────────────────
    if getattr(args, 'dry_run', False):
        print_dry_run_summary(context, rendered)
        return

    # ── Step 6: Write phase ───────────────────────────────────────────
    print(f"\n  🛠️  Creating god profile: {name}...")

    # Write profile files
    write_profile(name, rendered, context)

    # Write scaffolded Codex (Tier 2)
    write_scaffolded_codex(context)

    # Reference bundled Codexes (Tier 1)
    reference_bundled_codexes(context)

    # Update registries
    update_registries(context)

    # Log to vault
    log_vault_entry(
        "init",
        name,
        f"Created god profile: {context['NAME']} ({context['TYPE']}, {context['MODEL']})",
        version=context["VERSION"],
    )

    # ── Step 7: Summary ───────────────────────────────────────────────
    print_summary(context)
