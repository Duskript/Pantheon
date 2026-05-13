"""
main.py — CLI argument parsing and dispatch for `pantheon god` commands.

Entry point for the `pantheon` script. Parses sys.argv and dispatches to
init() or validate() with structured error handling and exit codes.
"""

import argparse
import sys
import traceback


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="pantheon",
        description="Pantheon God SDK — manage Pantheon gods",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Show detailed error information",
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Available commands")

    # ── god init ──────────────────────────────────────────────────────
    init_parser = subparsers.add_parser(
        "init", help="Scaffold a new god profile"
    )
    init_parser.add_argument("name", help="God identifier (lowercase-hyphens)")
    init_parser.add_argument("--domain", help="God's domain/purpose")
    init_parser.add_argument("--title", help="God's display title")
    init_parser.add_argument(
        "--type", default="conversational",
        choices=["conversational", "service", "subsystem"],
        help="God type (default: conversational)",
    )
    init_parser.add_argument("--model", help="LLM model (default: from ~/.hermes/config.yaml)")
    init_parser.add_argument("--provider", help="LLM provider (default: auto-detected from model)")
    init_parser.add_argument("--author", help="Author name (default: from git config)")
    init_parser.add_argument(
        "--codexes",
        help="Comma-separated list of bundled Codexes (overrides domain suggestions)",
    )
    init_parser.add_argument(
        "--no-suggest-codexes", action="store_true",
        help="Skip interactive Codex suggestion prompt",
    )
    init_parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing profiles without asking",
    )
    init_parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be created, make no changes",
    )
    init_parser.add_argument(
        "--json", action="store_true",
        help="Output structured JSON",
    )
    init_parser.add_argument(
        "--builder", action="store_true",
        help="Mark this god as a builder (gets Git Discipline section in SOUL.md)",
    )
    init_parser.add_argument(
        "--no-builder", action="store_true",
        help="Mark this god as a non-builder (gets code-routing note in SOUL.md instead of Git section)",
    )

    # ── god validate ──────────────────────────────────────────────────
    val_parser = subparsers.add_parser(
        "validate", help="Validate an existing god profile"
    )
    val_parser.add_argument(
        "name", nargs="?",
        help="God ID to validate (if omitted, validates ALL gods)",
    )
    val_parser.add_argument(
        "--json", action="store_true",
        help="Output structured JSON",
    )
    val_parser.add_argument(
        "--verbose", action="store_true",
        help="Show detailed check information",
    )

    parsed = parser.parse_args(argv)

    if parsed.subcommand is None:
        parser.print_help()
        sys.exit(0)

    # Normalize codexes argument
    if hasattr(parsed, 'codexes') and parsed.codexes:
        parsed.codexes = [c.strip() for c in parsed.codexes.split(",") if c.strip()]
    else:
        parsed.codexes = None

    return parsed


def cli(argv: list[str] | None = None) -> None:
    """Main CLI entry point."""
    try:
        args = parse_args(argv)

        if args.subcommand == "init":
            from .init import run_init
            run_init(args)
        elif args.subcommand == "validate":
            from .validate import run_validate
            run_validate(args)
        else:
            print(f"Unknown subcommand: {args.subcommand}")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    except ValueError as e:
        # User-facing validation errors (bad input, missing files)
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except PermissionError as e:
        print(f"Error: Permission denied — {e}", file=sys.stderr)
        print("Hint: Check directory ownership and write permissions.", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        # Unexpected errors
        print(f"Unexpected error: {e}", file=sys.stderr)
        verbose = getattr(args, 'verbose', False) if 'args' in dir() else False
        if verbose:
            traceback.print_exc()
        sys.exit(2)


if __name__ == "__main__":
    cli()
