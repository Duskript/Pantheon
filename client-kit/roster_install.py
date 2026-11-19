"""Pantheon Client Kit — roster installer (SPEC-CONTRACT Phase 2).

Installs the six shipped gods onto a client box, then removes every trace of the
operator's runtime from them. Three jobs, in this order:

1. **Render** the roster through the Phase-1 interview engine, so the client gets
   SOUL.md / persona.md / god.json / MEMORY.md / Codex index / .env / config.yaml
   built from the same spec the wizard asks questions from.
2. **Place** them at the layout the manifest declares, writing **nothing** outside
   the target root (every path is resolved and checked with ``relative_to``).
3. **Scrub** — blank MEMORY.md / USER.md and delete session, cron, ichor and
   state-database history. A client kit that ships the operator's memory is a
   data leak, not an onboarding.

Design rules it enforces as checks:

* No inline ``data:`` image anywhere in the pack, and no ``<...>`` placeholder
  passed off as an asset (``--check`` fails on both).
* Every ``routes_to`` destination must be a shipped god — a routing entry naming
  an uninstalled god is a dead handoff that only fails at runtime.
* Credentials are never templated in: ``model.default``/``model.provider`` ship as
  ``null`` and every secret-shaped value in a rendered ``.env`` is refused.
* Idempotent: an existing file is kept unless ``--force``. ``--dry-run`` writes
  nothing and reports exactly what it would do.

Usage
-----
    python3 roster_install.py --check
    python3 roster_install.py --root /home/client --dry-run
    python3 roster_install.py --root /home/client --answers answers.json
    python3 roster_install.py --sanitize /home/operator/.hermes/profiles   # fix live god.json defects
"""
from __future__ import annotations

import argparse
import base64
import json
import pathlib
import re
import shutil
import sys
from typing import Any

import yaml

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_MANIFEST = HERE / "manifest.yaml"
REPO_ROOT = HERE.parent
ENGINE_PATH = REPO_ROOT / "webui" / "api" / "interview_engine.py"

#: Runtime state that must never reach a client. Globs are matched inside each
#: profile directory; anything matching is deleted by the scrub.
SCRUB_GLOBS = [
    "state.db", "state.db-*", "state.db.*",
    "response_store.db", "response_store.db-*",
    "verification_evidence.db", "verification_evidence.db-*",
    "lcm.db", "lcm.db-*", "ichor.db", "ichor.db-*",
    "*.bak", "*.bak-*", "*.bak.*", ".backup.lock", "*.lock",
    "gateway_state.json", ".gateway_state_*.tmp", "processes.json",
    "session-rotations", ".session-rotations", "pending_messages",
    "discord_threads.json", ".restart_last_processed.json",
    ".skills_prompt_snapshot.json", ".codex_gpt55_autoraise_notice",
    ".clean_shutdown", "source-checks", "plugin-update-checks", "serve_restart_pending",
]
SCRUB_DIRS = [
    "sessions", "cron", "ichor", "memories", "webui_state", "state-snapshots",
    "runtime", "sandboxes", "backups", "audio_cache", "image_cache", "content",
    "pending_messages", ".curator_backups",
]

#: Values that must never appear in a rendered artifact.
SECRET_PREFIXES = ("sk-", "ghp_", "gho_", "ak_", "ck_", "eyJ", "data:", "xoxb-")
SECRET_RE = re.compile(r"^[A-Za-z0-9_\-]{32,}$")


class KitError(RuntimeError):
    """The pack, the manifest, or a rendered artifact is not shippable."""


# ── engine import (the pack reuses Phase 1, it does not fork it) ─────────────

def load_engine(engine_path: pathlib.Path | None = None):
    """Import the Phase-1 interview engine from the repo or a packaged copy."""
    path = pathlib.Path(engine_path) if engine_path else ENGINE_PATH
    if not path.exists():
        raise KitError(
            f"interview engine not found at {path}. Pass --engine-path, or package "
            f"interview_engine.py beside interview.yaml in the kit."
        )
    import importlib.util

    spec = importlib.util.spec_from_file_location("client_kit_interview_engine", path)
    if spec is None or spec.loader is None:
        raise KitError(f"could not load the interview engine from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["client_kit_interview_engine"] = module
    spec.loader.exec_module(module)
    return module


# ── manifest ───────────────────────────────────────────────────────────────

def load_manifest(path: pathlib.Path | None = None) -> dict:
    p = pathlib.Path(path) if path else DEFAULT_MANIFEST
    if not p.exists():
        raise KitError(f"manifest not found: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not data.get("gods"):
        raise KitError(f"{p}: no 'gods' block")
    return data


def check_pack(manifest: dict) -> list[str]:
    """The artifact-hygiene gate. Empty list means the pack is shippable."""
    problems: list[str] = []
    gods: dict[str, dict] = manifest.get("gods") or {}
    required = (manifest.get("verify") or {}).get(
        "every_god_has", ["display_name", "color", "domain", "icon", "role"]
    )
    if not manifest.get("conductor"):
        problems.append("manifest has no conductor")
    elif manifest["conductor"] not in gods:
        problems.append(f"conductor '{manifest['conductor']}' is not a shipped god")

    for name, god in gods.items():
        for field in required:
            if not god.get(field):
                problems.append(f"{name}: missing '{field}'")
        icon = str(god.get("icon") or "")
        if icon.lower().startswith(("data:", "data:image")):
            problems.append(f"{name}: icon is an inline data-url — extract it or drop it")
        if icon.startswith("<") and icon.endswith(">"):
            problems.append(f"{name}: icon is a roster placeholder ('{icon}') — not an asset")
        domain = str(god.get("domain") or "")
        if domain and not (re.search(r"·", domain) or re.match(r"^[A-Z]{2,}", domain)):
            problems.append(f"{name}: domain '{domain}' is not in the house style "
                            f"'Thing · Thing · Thing'")
        for slot, dest in (god.get("routes_to") or {}).items():
            if dest not in gods:
                problems.append(
                    f"{name}: routes_to.{slot} -> '{dest}' is not a shipped god "
                    f"(dead handoff)"
                )
        if god.get("safety") and not isinstance(god["safety"], dict):
            problems.append(f"{name}: safety must be a mapping")
    return problems


# ── rendering ──────────────────────────────────────────────────────────────

def _rename_god(artifacts: dict[str, str], god: str, old: str, new: str) -> list[str]:
    """Propagate a manifest rename through every artifact that names the god.

    A rename that lands in ``god.json`` but not in SOUL.md / persona.md /
    MEMORY.md / the Codex directory leaves the install internally inconsistent —
    the same class of defect the roster audit found (one domain string rendered
    four different ways). Returns the relative paths it touched.
    """
    pattern = re.compile(rf"\b{re.escape(old)}\b")
    touched: list[str] = []
    for rel in (f"gods/{god}/SOUL.md", f"gods/{god}/persona.md", f"gods/{god}/MEMORY.md",
                f"gods/{god}/.env", f"gods/{god}/config.yaml"):
        if rel in artifacts:
            artifacts[rel] = pattern.sub(new, artifacts[rel])
            touched.append(rel)
    engine_codex = f"athenaeum/Codex-God-{old}/INDEX.md"
    if engine_codex in artifacts:
        moved = artifacts.pop(engine_codex).replace(f"Codex-{old}", f"Codex-{new}")
        artifacts[f"athenaeum/Codex-God-{new}/INDEX.md"] = moved
        touched.append(f"athenaeum/Codex-God-{new}/INDEX.md")
    return touched


def render_roster(manifest: dict, answers: dict | None = None,
                  engine_path: pathlib.Path | None = None) -> dict[str, str]:
    """Render the install tree with the Phase-1 engine, then overlay the manifest.

    The manifest wins on identity (domain/colour/icon) so the shipped pack renders
    identically whether or not the client answered the interview.
    """
    ie = load_engine(engine_path)
    spec = ie.load_spec(REPO_ROOT / "plans" / "pantheon-client-kit" / "interview.yaml")
    roster = ie.load_roster(REPO_ROOT / "plans" / "pantheon-client-kit" / "roster.yaml")
    engine = ie.InterviewEngine(spec, roster)
    for key, value in (answers or {}).items():
        try:
            engine.answer(key, value)
        except ie.SpecError:
            continue
    artifacts = ie.render_artifacts(engine, spec, roster)

    gods = manifest["gods"]
    shipped = list(gods)
    for god in shipped:
        meta = gods[god]
        god_json = {
            "display_name": meta["display_name"],
            "icon": meta["icon"],
            "color": meta["color"],
            "domain": meta["domain"],
        }
        # The manifest is authoritative for the kit — it is the file a maintainer
        # edits — so this overlay must actually land. Keying it on the bare god
        # name never matches (artifact keys are 'gods/<god>/god.json'), which
        # silently turns the manifest into decoration: the engine's own defaults
        # are close enough that a test cannot tell the two apart unless it makes
        # the manifest *differ* first.
        god_json_key = f"gods/{god}/god.json"
        if god_json_key not in artifacts:
            raise KitError(
                f"the engine rendered no {god_json_key}; refusing to build a pack "
                f"with a god that has no visual identity"
            )
        # Read the engine's name BEFORE overwriting, so a rename can be propagated
        # to everything else that spells it out.
        engine_display = json.loads(artifacts[god_json_key])["display_name"]
        artifacts[god_json_key] = json.dumps(god_json, indent=2, ensure_ascii=False) + "\n"
        if meta["display_name"] != engine_display:
            _rename_god(artifacts, god, engine_display, meta["display_name"])
    artifacts["PHONEBOOK.json"] = _phonebook(manifest)
    artifacts["CLIENT-README.md"] = _client_readme(manifest, engine)
    artifacts["MANIFEST.json"] = json.dumps(
        {
            "schema_version": "0.1",
            "kit": manifest.get("kit"),
            "kit_version": manifest.get("version"),
            "generated": manifest.get("generated"),
            "conductor": manifest.get("conductor"),
            "gods": shipped,
            "files": sorted(artifacts),
            "known_limits": [lim["id"] for lim in manifest.get("known_limits") or []],
        },
        indent=2,
        ensure_ascii=False,
    ) + "\n"
    return artifacts


def _phonebook(manifest: dict) -> str:
    gods = manifest["gods"]
    book: dict[str, Any] = {"conductor": manifest["conductor"], "gods": {}}
    for name, meta in gods.items():
        book["gods"][name] = {
            "display_name": meta["display_name"],
            "home_channel": "",
            "free_response": True,
            "routes_to": {k: v for k, v in (meta.get("routes_to") or {}).items() if v in gods},
        }
    return json.dumps(book, indent=2, ensure_ascii=False) + "\n"


def _client_readme(manifest: dict, engine) -> str:
    rows = "\n".join(
        f"| {m['display_name']} | {m['role']} | {m['domain']} |" for m in manifest["gods"].values()
    )
    limits = "\n\n".join(
        f"**{lim['label']}.** {str(lim['detail']).strip()}" for lim in manifest.get("known_limits") or []
    )
    gaps = [u.key for u in engine.unknowns()]
    return f"""# {manifest.get('kit', 'Pantheon Client Kit')} v{manifest.get('version', '0')}

The six gods below are installed and wired. Every fact the install knows came
from the setup interview; gaps stayed gaps (`❓ open`) rather than being guessed.

## Your gods

| God | Role | Domain |
|---|---|---|
{rows}

**Conductor:** {manifest['conductor']} — the one bot you set up by hand; it creates
and wires the rest.

## Known limits (by design)

{limits}

## Before you start

1. Fill each `profiles/<god>/.env` (tokens are blank on purpose — the kit ships none).
2. Set model/provider in the onboarding wizard; it probes this machine.
3. Verify every platform ID before trusting it — a wrong ID fails silently.

## Open questions from the interview

{chr(10).join(f"- ❓ open: {k}" for k in gaps) if gaps else "- none"}
"""


# ── placement ──────────────────────────────────────────────────────────────

def _resolve_within(root: pathlib.Path, relative: str) -> pathlib.Path:
    """Join and prove the result stays inside ``root`` (no traversal, no escapes)."""
    target = (root / relative).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise KitError(f"refusing to write outside the target root: {relative}") from exc
    return target


def plan_placements(manifest: dict, artifacts: dict[str, str]) -> dict[str, str]:
    """Map rendered artifact -> path relative to the client's $HOME."""
    layout = manifest["layout"]
    plan: dict[str, str] = {}
    for god, meta in manifest["gods"].items():
        profile = layout["profile_dir"].format(god=god)
        god_json = json.loads(artifacts[f"gods/{god}/god.json"])
        codex = layout["codex_dir"].format(display_name=god_json["display_name"])
        for name in ("SOUL.md", "persona.md", "god.json", "MEMORY.md", ".env", "config.yaml"):
            key = f"gods/{god}/{name}"
            if key in artifacts:
                plan[key] = f"{profile}/{name}"
        # Direct lookup: after _rename_god() the key IS the manifest's name, and a
        # fuzzy match here silently dropped the Codex entry for a renamed god.
        codex_index = f"athenaeum/Codex-God-{god_json['display_name']}/INDEX.md"
        if codex_index not in artifacts:
            raise KitError(f"{god}: no Codex index rendered for {god_json['display_name']}")
        plan[codex_index] = f"{codex}/INDEX.md"
    for key in ("tenant.json", "PHONEBOOK.json", "CLIENT-README.md", "MANIFEST.json"):
        if key in artifacts:
            plan[key] = layout["tenant_file"] if key == "tenant.json" else f".hermes/client-kit/{key}"
    for key in artifacts:
        if key.startswith("person_roots/"):
            plan[key] = f"{layout['person_roots_dir']}/{key[len('person_roots/'):]}"
    return plan


def check_no_secrets(artifacts: dict[str, str]) -> list[str]:
    problems: list[str] = []
    for rel, text in artifacts.items():
        if rel.endswith(".env"):
            for line in text.splitlines():
                if line.startswith("#") or "=" not in line:
                    continue
                value = line.split("=", 1)[1].strip()
                if value.startswith(SECRET_PREFIXES) or SECRET_RE.match(value):
                    problems.append(f"{rel}: line '{line.split('=')[0]}' looks like a real secret")
        if '"icon"' in text and "data:image" in text:
            problems.append(f"{rel}: contains inline image data")
    return problems


def install_roster(root: pathlib.Path, manifest: dict, artifacts: dict[str, str],
                   *, dry_run: bool = False, force: bool = False,
                   scrub: bool = True) -> dict:
    """Write the tree under ``root`` and scrub the created profiles."""
    root = pathlib.Path(root).expanduser().resolve()
    plan = plan_placements(manifest, artifacts)
    written: list[str] = []
    kept: list[str] = []
    removed: list[str] = []

    for key, relative in sorted(plan.items()):
        target = _resolve_within(root, relative)
        if target.exists() and not force:
            kept.append(relative)
            continue
        if dry_run:
            written.append(relative)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(artifacts[key], encoding="utf-8")
        written.append(relative)

    if scrub:
        for god in manifest["gods"]:
            profile = _resolve_within(root, manifest["layout"]["profile_dir"].format(god=god))
            removed.extend(scrub_profile(profile, dry_run=dry_run))
        removed.extend(scrub_shared_memory(_resolve_within(root, ".hermes/memories"), dry_run=dry_run))

    return {
        "root": str(root),
        "written": written,
        "kept": kept,
        "removed": removed,
        "dry_run": dry_run,
    }


# ── scrub ──────────────────────────────────────────────────────────────────

def scrub_profile(profile_dir: pathlib.Path, *, dry_run: bool = False) -> list[str]:
    """Delete runtime history from one profile. Returns what was (or would be) removed."""
    removed: list[str] = []
    if not profile_dir.exists():
        return removed
    for pattern in SCRUB_GLOBS:
        for path in sorted(profile_dir.glob(pattern)):
            if path.is_dir():
                continue
            removed.append(str(path))
            if not dry_run:
                path.unlink(missing_ok=True)
    for name in SCRUB_DIRS:
        path = profile_dir / name
        if path.is_dir():
            removed.append(str(path))
            if not dry_run:
                shutil.rmtree(path, ignore_errors=True)
    # Blanks, not deletions: Hermes expects the files to exist.
    for name in ("MEMORY.md", "USER.md"):
        path = profile_dir / name
        if path.exists():
            removed.append(f"{path} (blanked)")
            if not dry_run:
                path.write_text("", encoding="utf-8")
    return removed


def scrub_shared_memory(memories_dir: pathlib.Path, *, dry_run: bool = False) -> list[str]:
    """Blank the fleet-level MEMORY.md / USER.md the runtime would inherit."""
    removed: list[str] = []
    if not memories_dir.is_dir():
        return removed
    for pattern in ("MEMORY.md", "USER.md"):
        path = memories_dir / pattern
        if path.exists():
            removed.append(f"{path} (blanked)")
            if not dry_run:
                path.write_text("", encoding="utf-8")
    for pattern in ("*.meta", "*.bak*"):
        for extra in sorted(memories_dir.glob(pattern)):
            removed.append(str(extra))
            if not dry_run:
                extra.unlink(missing_ok=True)
    return removed


# ── sanitize an existing tree (the §7.2 roster defects) ─────────────────────

def _sniff_image_ext(blob: bytes, header: str = "") -> str:
    """Prefer the payload's magic bytes over the data-url's declared mime type.

    Live profiles mislabel this: rheta's icon *declares* ``data:image/png`` while
    the bytes are JPEG. The WebUI sniffs magic bytes when it serves them, so the
    wrong extension is survivable — but it is the kind of mislabel that breaks the
    first tool which trusts the filename.
    """
    if blob[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return ".webp"
    if blob[:3] == b"GIF":
        return ".gif"
    low = (header or "").lower()
    for token, suffix in (("jpeg", ".jpg"), ("jpg", ".jpg"), ("webp", ".webp"),
                          ("gif", ".gif"), ("png", ".png")):
        if token in low:
            return suffix
    return ".png"


def sanitize_god_json(path: pathlib.Path, *, dry_run: bool = False,
                      domain: str | None = None, bootstrap: dict | None = None) -> dict:
    """Extract an inline icon to ``icon.png`` and rewrite the reference.

    Deleting a 2.7 MB data-url would delete the artwork too, so the bytes are
    written to ``icon.png`` beside god.json (which is what ``/api/gods/<n>/icon``
    already serves) and the field becomes a served path. Backs up the original.
    """
    result: dict[str, Any] = {"path": str(path), "actions": []}
    if not path.exists():
        if not bootstrap:
            result["actions"].append("missing — no god.json, and no --bootstrap data")
            return result
        result["actions"].append(
            "no god.json existed — created one (display name, colour, domain; "
            "avatar still to be supplied by the client)"
        )
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(bootstrap, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        return result
    raw = path.read_text(encoding="utf-8")
    try:
        meta = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise KitError(f"{path}: not valid JSON ({exc})") from exc
    icon = str(meta.get("icon") or "")
    if icon.lower().startswith("data:"):
        header, _, payload = icon.partition(",")
        blob = base64.b64decode(payload + "=" * (-len(payload) % 4))
        declared = header.split(":", 1)[1].split(";", 1)[0] if ":" in header else "unknown"
        actual_ext = _sniff_image_ext(blob, header)
        # The serving route reads exactly `icon.png` and sniffs magic bytes itself,
        # so the filename must NOT follow the payload format — only the report does.
        target = path.parent / "icon.png"
        note = "" if actual_ext == ".png" else f", payload is actually {actual_ext}"
        result["actions"].append(
            f"extracted inline icon ({len(icon)} chars, declared {declared}{note}) "
            f"-> {target.name} ({len(blob)} bytes)"
        )
        if not dry_run:
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak-inline-icon"))
            target.write_bytes(blob)
            meta["icon"] = f"/api/gods/{path.parent.name}/icon"
    elif icon.startswith("<") and icon.endswith(">"):
        result["actions"].append(
            f"placeholder icon '{icon[:40]}…' -> /api/gods/{path.parent.name}/icon"
        )
        if not dry_run:
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak-inline-icon"))
            meta["icon"] = f"/api/gods/{path.parent.name}/icon"
    if domain and meta.get("domain") != domain:
        result["actions"].append(f"domain '{meta.get('domain')}' -> '{domain}'")
        if not dry_run:
            path.with_suffix(path.suffix + ".bak-domain").write_text(raw, encoding="utf-8")
            meta["domain"] = domain
    if result["actions"] and not dry_run:
        path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


# ── CLI ────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="roster_install",
        description="Install the shipped god roster onto a client box, then scrub it.",
    )
    parser.add_argument("--manifest", default=None)
    parser.add_argument("--engine-path", default=None)
    parser.add_argument("--root", default=None, help="client $HOME to install into")
    parser.add_argument("--answers", default=None, help="interview answers JSON")
    parser.add_argument("--check", action="store_true", help="validate the pack, exit 1 on problems")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    parser.add_argument("--no-scrub", action="store_true", help="skip the memory scrub (operator only)")
    parser.add_argument("--sanitize", default=None,
                        help="sanitize an existing profiles/ dir (extract inline icons)")
    parser.add_argument("--bootstrap", action="store_true",
                        help="with --sanitize: create a god.json for any shipped god "
                             "that has none (kairos had none at all)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(args.manifest)
    except KitError as exc:
        print(f"kit error: {exc}", file=sys.stderr)
        return 2

    if args.check:
        problems = check_pack(manifest)
        if args.json:
            print(json.dumps({"ok": not problems, "problems": problems}, indent=2))
        elif problems:
            print(f"pack check FAILED — {len(problems)} problem(s):")
            for problem in problems:
                print(f"  - {problem}")
        else:
            gods = ", ".join(manifest["gods"])
            print(f"pack check OK — {len(manifest['gods'])} gods ({gods}); "
                  f"conductor={manifest['conductor']}; "
                  f"{len(manifest.get('known_limits') or [])} documented limits")
        return 1 if problems else 0

    if args.sanitize:
        root = pathlib.Path(args.sanitize).expanduser()
        results = []
        for god in manifest["gods"]:
            meta = manifest["gods"][god]
            seed = {"display_name": meta["display_name"], "icon": meta["icon"],
                    "color": meta["color"], "domain": meta["domain"]}
            results.append(sanitize_god_json(root / god / "god.json",
                                             dry_run=args.dry_run,
                                             domain=meta["domain"],
                                             bootstrap=seed if args.bootstrap else None))
        for row in results:
            print(f"{row['path']}: " + ("; ".join(row["actions"]) or "clean"))
        return 0

    try:
        answers = json.loads(pathlib.Path(args.answers).read_text(encoding="utf-8")) if args.answers else {}
        answers = answers.get("answers", answers)
        artifacts = render_roster(manifest, answers, pathlib.Path(args.engine_path) if args.engine_path else None)
    except KitError as exc:
        print(f"kit error: {exc}", file=sys.stderr)
        return 2

    leaks = check_no_secrets(artifacts)
    if leaks:
        print("refusing to install — secret-shaped values in the rendered pack:", file=sys.stderr)
        for leak in leaks:
            print(f"  - {leak}", file=sys.stderr)
        return 2

    if not args.root:
        print(json.dumps({"artifacts": sorted(artifacts)}, indent=2))
        return 0

    summary = install_roster(pathlib.Path(args.root), manifest, artifacts,
                             dry_run=args.dry_run, force=args.force,
                             scrub=not args.no_scrub)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        verb = "would write" if args.dry_run else "wrote"
        print(f"{verb} {len(summary['written'])} files under {summary['root']}")
        if summary["kept"]:
            print(f"  kept {len(summary['kept'])} existing files (use --force to overwrite)")
        if summary["removed"]:
            print(f"  scrubbed {len(summary['removed'])} runtime paths")
        for relative in summary["written"]:
            print(f"    + {relative}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
