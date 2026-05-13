"""
template_engine.py — Simple template rendering using string.Template.

Responsibilities:
- render(template_name, variables) -> str
- resolve_template_path(template_name) -> Path
- TEMPLATE_DIR points to god_cli/templates/
- Uses string.Template.safe_substitute()
- validate_no_unsubstituted_vars(rendered) — warns about $VAR left behind
"""

import os
import re
import sys
from pathlib import Path
from string import Template

TEMPLATE_DIR = Path(__file__).parent / "templates"


def resolve_template_path(template_name: str) -> Path:
    """Resolve a template name to an absolute path."""
    path = TEMPLATE_DIR / template_name
    if not path.exists():
        raise FileNotFoundError(
            f"Template '{template_name}' not found at {path}. "
            f"Reinstall the god CLI or check the templates/ directory."
        )
    return path


def find_unsubstituted_vars(text: str) -> list[str]:
    """Find any remaining $VAR patterns in rendered text.

    Looks for standalone $WORD patterns (uppercase letters, underscores, digits).
    Skips things like markdown, path references with $name, etc.
    """
    # Match $ followed by uppercase letters, underscores, and optionally digits
    # Exclude common false positives: $name (already substituted lowercase vars)
    matches = re.findall(r'\$[A-Z][A-Z_0-9]*', text)
    # Also find $word patterns that aren't common false positives
    matches.extend(re.findall(r'\$[A-Z][a-zA-Z_]*', text))
    # Deduplicate
    return sorted(set(matches))


def render(template_name: str, variables: dict) -> str:
    """Render a template file with the given variables.

    Uses string.Template.safe_substitute() so missing variables are left as-is.
    After rendering, scans for unreplaced variables and warns.
    """
    template_path = resolve_template_path(template_name)

    with open(template_path) as f:
        raw = f.read()

    result = Template(raw).safe_substitute(variables)

    # Warn about unreplaced variables (helps template authors catch typos)
    unreplaced = find_unsubstituted_vars(result)
    if unreplaced:
        print(
            f"  ⚠️  Warning: Unsubstituted variables in {template_name}: "
            f"{', '.join(unreplaced)}",
            file=sys.stderr,
        )

    return result
