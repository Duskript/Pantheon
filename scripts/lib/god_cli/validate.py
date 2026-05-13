"""
validate.py — `god validate` implementation.

Responsibilities:
- Discover profile directory from god name
- Run each check and collect results
- Each check returns a CheckResult namedtuple
- Compute overall status
- Print formatted report or emit JSON
- 7 checks: SOUL, Persona, Config, Codex (T2), Bundled (T1),
  Registry, Gods.yaml, Manifest Codex
"""

import json
import os
import sys
from collections import namedtuple
from pathlib import Path

import yaml

from . import defaults
from . import registry as reg_mod

# Import pantheon_sdk functions
sys.path.insert(0, os.path.join(defaults.PANTHEON_DIR, "scripts", "lib"))
from pantheon_sdk import get_registry, registry_find

# ── Data Structures ───────────────────────────────────────────────────

CheckResult = namedtuple("CheckResult", ["name", "status", "message", "hint"])

# status values: "PASS", "WARN", "FAIL"


def _print_report(
    god_name: str,
    results: list[CheckResult],
    json_output: bool = False,
) -> None:
    """Print a formatted validation report."""
    if json_output:
        report = {
            "god": god_name,
            "results": [
                {
                    "check": r.name,
                    "status": r.status,
                    "message": r.message,
                    "hint": r.hint,
                }
                for r in results
            ],
            "summary": {
                "total": len(results),
                "pass": sum(1 for r in results if r.status == "PASS"),
                "warn": sum(1 for r in results if r.status == "WARN"),
                "fail": sum(1 for r in results if r.status == "FAIL"),
            },
        }
        print(json.dumps(report, indent=2))
        return

    pass_count = sum(1 for r in results if r.status == "PASS")
    warn_count = sum(1 for r in results if r.status == "WARN")
    fail_count = sum(1 for r in results if r.status == "FAIL")

    overall = "✅ PASS"
    if fail_count > 0:
        overall = "❌ FAIL"
    elif warn_count > 0:
        overall = "⚠️  WARN"

    box_width = 66
    print()
    print(f"  ╭─ Validation Report: {god_name} ─{''.join(['─' for _ in range(max(0, box_width - 24 - len(god_name)))])}╮")
    print(f"  │{' ' * (box_width)}│")
    print(f"  │  Overall: {overall}  ({pass_count} PASS, {warn_count} WARN, {fail_count} FAIL){' ' * (box_width - 12 - len(overall) - len(f'{pass_count} PASS, {warn_count} WARN, {fail_count} FAIL') - 5)}│")
    print(f"  │{' ' * (box_width)}│")

    for r in results:
        icon = "✅" if r.status == "PASS" else ("⚠️ " if r.status == "WARN" else "❌")
        msg = r.message
        if len(msg) > box_width - 6:
            msg = msg[: box_width - 9] + "..."
        print(f"  │  {icon} {r.name:<14} — {msg:<{box_width - 22}}│")
        if r.hint:
            hint_lines = []
            line = r.hint
            while len(line) > 0:
                hint_lines.append(line[:box_width - 8])
                line = line[box_width - 8:]
            for hl in hint_lines:
                print(f"  │    {' ' * 17}{hl:<{box_width - 22}}│")

    print(f"  │{' ' * (box_width)}│")
    print(f"  ╰{'─' * box_width}╯")
    print()


# ── Check Functions ───────────────────────────────────────────────────


def check_soul(profile_dir: Path) -> CheckResult:
    """Check 1: SOUL.md exists and has all required sections."""
    soul_path = profile_dir / "SOUL.md"
    if not soul_path.exists():
        return CheckResult(
            "SOUL.md", "FAIL",
            f"SOUL.md not found at {soul_path}",
            "Run 'pantheon god init <name> --force' to regenerate",
        )

    required_sections = [
        "## Identity",
        "## Domain",
        "## Persona",
        "## Filesystem Access",
        "## Shared Brain Protocol",
        "## Notifications",
    ]

    content = soul_path.read_text()
    missing = [s for s in required_sections if s not in content]

    if missing:
        return CheckResult(
            "SOUL.md", "FAIL",
            f"Missing required sections: {', '.join(missing)}",
            "Edit SOUL.md to add the missing sections",
        )

    return CheckResult("SOUL.md", "PASS", "All required sections present", "")


def check_persona(profile_dir: Path) -> CheckResult:
    """Check 2: persona.md exists (warn if not)."""
    persona_path = profile_dir / "persona.md"
    if not persona_path.exists():
        return CheckResult(
            "Persona", "WARN",
            f"persona.md not found at {persona_path}",
            "Create persona.md (see persona.md.example in god-template)",
        )

    content = persona_path.read_text()
    # Check for unfilled placeholders
    if "[Trait 1]" in content or "[Signature phrase]" in content:
        return CheckResult(
            "Persona", "WARN",
            "persona.md exists but has unfilled placeholders",
            "Fill in the [bracketed] sections with actual character content",
        )

    return CheckResult("Persona", "PASS", "persona.md present", "")


def check_config(profile_dir: Path) -> CheckResult:
    """Check 3: config.yaml exists + valid YAML + MCP server + toolsets."""
    config_path = profile_dir / "config.yaml"
    if not config_path.exists():
        return CheckResult(
            "Config", "FAIL",
            f"config.yaml not found at {config_path}",
            "Run 'pantheon god init <name> --force' to regenerate",
        )

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
        if not isinstance(config, dict):
            return CheckResult(
                "Config", "FAIL",
                "config.yaml is empty or malformed",
                "",
            )
    except yaml.YAMLError as e:
        return CheckResult(
            "Config", "FAIL",
            f"config.yaml YAML parse error: {e}",
            "",
        )

    issues = []
    mcps = config.get("mcp_servers", {})
    if "pantheon" not in mcps:
        issues.append("Missing mcp_servers.pantheon")
    elif not isinstance(mcps["pantheon"], dict):
        issues.append("mcp_servers.pantheon is not a dict")
    else:
        if "url" not in mcps["pantheon"]:
            issues.append("mcp_servers.pantheon missing 'url' field")

    toolsets = config.get("toolsets", [])
    if "hermes-cli" not in toolsets:
        issues.append("Missing toolsets: 'hermes-cli'")

    if issues:
        return CheckResult(
            "Config", "FAIL",
            "; ".join(issues),
            "Edit config.yaml to add the missing entries",
        )

    return CheckResult("Config", "PASS", "MCP server + toolsets OK", "")


def check_scaffolded_codex(god_name: str) -> CheckResult:
    """Check 4a: Tier 2 Codex (Codex-God-{Name}) structure."""
    name_title = god_name.replace("-", " ").title().replace(" ", "")
    if god_name.islower() and "-" not in god_name:
        name_title = god_name.capitalize()
    else:
        name_title = "".join(w.capitalize() for w in god_name.split("-"))

    codex_dir = defaults.get_codex_dir(name_title)

    if not codex_dir.exists():
        return CheckResult(
            "Codex (T2)", "FAIL",
            f"Scaffolded Codex not found at {codex_dir}",
            "Run 'pantheon god init <name> --force' to create it",
        )

    missing = []
    if not (codex_dir / "INDEX.md").exists():
        missing.append("INDEX.md")
    if not (codex_dir / "memory.md").exists():
        missing.append("memory.md")
    if not (codex_dir / "journal").exists():
        missing.append("journal/")

    if missing:
        return CheckResult(
            "Codex (T2)", "FAIL",
            f"Missing required files: {', '.join(missing)}",
            "Run 'pantheon god init <name> --force' to scaffold missing files",
        )

    return CheckResult(
        "Codex (T2)", "PASS",
        "INDEX.md + memory.md + journal/ present",
        "",
    )


def check_bundled_codexes(profile_dir: Path) -> CheckResult:
    """Check 4b: Tier 1 Bundled Codexes — verify all declared Codexes exist."""
    manifest_path = profile_dir / "god.yaml"
    if not manifest_path.exists():
        return CheckResult(
            "Bundled (T1)", "FAIL",
            "god.yaml not found — cannot check bundled Codexes",
            "",
        )

    try:
        with open(manifest_path) as f:
            manifest = yaml.safe_load(f)
    except Exception as e:
        return CheckResult(
            "Bundled (T1)", "FAIL",
            f"Cannot read god.yaml: {e}",
            "",
        )

    if not isinstance(manifest, dict):
        return CheckResult(
            "Bundled (T1)", "FAIL",
            "god.yaml is empty or malformed",
            "",
        )

    codexes = manifest.get("codexes", {})
    bundled = codexes.get("bundled", [])

    if not bundled:
        return CheckResult(
            "Bundled (T1)", "PASS",
            "No bundled Codexes declared",
            "",
        )

    missing = []
    for codex_name in bundled:
        codex_dir = defaults.get_bundled_codex_dir(codex_name)
        if not codex_dir.exists() or not (codex_dir / "INDEX.md").exists():
            missing.append(codex_name)

    if missing:
        hint = (
            "Missing bundled Codexes need to exist at ~/athenaeum/ for "
            "build/install to work. Either create them or update god.yaml."
        )
        return CheckResult(
            "Bundled (T1)", "WARN",
            f"Bundled Codexes not found: {', '.join(missing)}",
            hint,
        )

    return CheckResult(
        "Bundled (T1)", "PASS",
        f"All {len(bundled)} bundled Codexes present",
        "",
    )


def check_registry(god_name: str) -> CheckResult:
    """Check 5: Entry in pantheon-registry.yaml exists."""
    try:
        entries = get_registry()
    except Exception as e:
        return CheckResult(
            "Registry", "FAIL",
            f"Cannot read pantheon-registry.yaml: {e}",
            "",
        )

    if not entries:
        return CheckResult(
            "Registry", "FAIL",
            "No entries in pantheon-registry.yaml",
            "Run 'pantheon god init <name>' to register",
        )

    # Try matching by name
    idx, entry = registry_find(entries, god_name)
    if idx is None:
        # Also try exact name match
        for i, e in enumerate(entries):
            if e.get("name", "").lower() == god_name.lower():
                idx, entry = i, e
                break

    if idx is None:
        return CheckResult(
            "Registry", "FAIL",
            f"'{god_name}' not found in pantheon-registry.yaml",
            "Run 'pantheon god init <name>' to register",
        )

    version = entry.get("version", "?")
    return CheckResult(
        "Registry", "PASS",
        f"Found in registry (v{version})",
        "",
    )


def check_gods_yaml(god_name: str) -> CheckResult:
    """Check 6: Entry in gods.yaml exists with status."""
    try:
        entry = reg_mod.gods_yaml_find(god_name)
    except Exception as e:
        return CheckResult(
            "gods.yaml", "FAIL",
            f"Cannot check gods.yaml: {e}",
            "",
        )

    if entry is None:
        return CheckResult(
            "gods.yaml", "FAIL",
            f"'{god_name}' not found in gods.yaml",
            "Run 'pantheon god init <name>' to register in gods.yaml",
        )

    status = entry.get("status", "unknown")
    return CheckResult(
        "gods.yaml", "PASS",
        f"Found with status: {status}",
        "",
    )


def check_manifest_codexes(profile_dir: Path) -> CheckResult:
    """Check 7: Validate the codex declaration in god.yaml.

    - codexes.bundled exists
    - codexes.scaffolded exists
    - No Codex-God-* in bundled
    - All paths are valid
    """
    manifest_path = profile_dir / "god.yaml"
    if not manifest_path.exists():
        return CheckResult(
            "Manifest", "FAIL",
            "god.yaml not found",
            "",
        )

    try:
        with open(manifest_path) as f:
            manifest = yaml.safe_load(f)
    except Exception as e:
        return CheckResult(
            "Manifest", "FAIL",
            f"Cannot read god.yaml: {e}",
            "",
        )

    if not isinstance(manifest, dict):
        return CheckResult(
            "Manifest", "FAIL",
            "god.yaml is empty or malformed",
            "",
        )

    codexes = manifest.get("codexes", {})
    if not isinstance(codexes, dict):
        return CheckResult(
            "Manifest", "FAIL",
            "codexes section in god.yaml is not a dict",
            "",
        )

    issues = []

    # Must have both sections
    if "bundled" not in codexes:
        issues.append("Missing 'codexes.bundled' section")
    if "scaffolded" not in codexes:
        issues.append("Missing 'codexes.scaffolded' section")

    bund = codexes.get("bundled", [])
    if not isinstance(bund, list):
        issues.append("'codexes.bundled' is not a list")
    else:
        # Scaffolded must NOT include Codex-God-* in bundled
        for cx in bund:
            if isinstance(cx, str) and cx.startswith("Codex-God-"):
                issues.append(
                    f"'{cx}' is a scaffolded Codex but declared as bundled. "
                    f"Codex-God-* Codexes must be in codexes.scaffolded only."
                )

    scaff = codexes.get("scaffolded", [])
    if not isinstance(scaff, list):
        issues.append("'codexes.scaffolded' is not a list")

    if issues:
        return CheckResult(
            "Manifest", "FAIL",
            "; ".join(issues),
            "Edit the codexes section in god.yaml",
        )

    return CheckResult("Manifest", "PASS", "Codex declaration valid", "")


# ── Main Validate Logic ───────────────────────────────────────────────


def discover_gods() -> list[str]:
    """Discover all god names from ~/.hermes/profiles/."""
    profiles_dir = defaults.get_profiles_dir()
    if not profiles_dir.exists():
        return []
    return sorted([
        d.name for d in profiles_dir.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    ])


def run_validate(args) -> None:
    """Main entry point for `pantheon god validate [name]`."""
    god_name = getattr(args, 'name', None)
    json_output = getattr(args, 'json', False)

    if god_name:
        # Validate a single god
        names_to_check = [god_name]
    else:
        # Validate ALL gods
        names_to_check = discover_gods()
        if not names_to_check:
            print("No gods found in ~/.hermes/profiles/")
            return
        if not json_output:
            print(f"\n  Found {len(names_to_check)} god(s) to validate.\n")

    overall_fail = False

    for name in names_to_check:
        profile_dir = defaults.get_profile_dir(name)
        if not profile_dir.exists():
            if not json_output:
                result = CheckResult(
                    "Profile", "FAIL",
                    f"Profile directory not found: {profile_dir}",
                    "Use 'pantheon god init <name>' to create it",
                )
                _print_report(name, [result], json_output=False)
            else:
                report = {
                    "god": name,
                    "error": f"Profile directory not found: {profile_dir}",
                }
                print(json.dumps(report, indent=2))
            overall_fail = True
            continue

        # Run all checks

        # Check 1 & 2: SOUL.md, Persona
        r1 = check_soul(profile_dir)
        r2 = check_persona(profile_dir)

        # Check 3: Config
        r3 = check_config(profile_dir)

        # Check 4a: Scaffolded Codex (Tier 2)
        r4a = check_scaffolded_codex(name)

        # Check 4b: Bundled Codexes (Tier 1)
        r4b = check_bundled_codexes(profile_dir)

        # Check 5: Registry
        r5 = check_registry(name)

        # Check 6: gods.yaml
        r6 = check_gods_yaml(name)

        # Check 7: Manifest Codex
        r7 = check_manifest_codexes(profile_dir)

        results = [r1, r2, r3, r4a, r4b, r5, r6, r7]

        if not json_output:
            _print_report(name, results, json_output=False)
        else:
            _print_report(name, results, json_output=True)

        if any(r.status == "FAIL" for r in results):
            overall_fail = True

    if overall_fail:
        sys.exit(1)
