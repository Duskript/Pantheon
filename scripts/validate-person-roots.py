#!/usr/bin/env python3
"""Structural validator for the Pantheon Person Roots seed tree.

Checks (per PERSON_ROOTS_SCHEMA.md section 12 and the Wave 1/2 fusion build):
  1.  root directory exists
  2.  INDEX.md exists at the root
  3.  every person folder listed in INDEX.md exists (and every non-underscore
      folder on disk is listed in the index)
  4.  required base files exist for each person:
      PROFILE.md, RELATIONSHIP_TO_OWNER.md, ALIASES.md, PERMISSIONS.md,
      MEMORY_POLICY.md, INTERACTION_LOG.md, NOTES.md
  5.  direct users have ROOT.md, PREFERENCES.md, RELATIONSHIPS/owner.md, and
      at least one PROJECTS/*.md when a project lane is declared
  6.  every markdown file has YAML frontmatter
  7.  frontmatter parses (PyYAML when installed; stdlib fallback otherwise)
  8.  person_id matches the folder slug for person files
  9.  document_type is one of the allowed enum values
 10.  sensitivity is one of the allowed enum values
 11.  trust_tier, when present, is one of the allowed enum values
 12.  RELATIONSHIP_TO_OWNER.md defaults to shareable_by_default: false

CLI:
    python3 validate-person-roots.py --root <relationships-root>

Output ends with `RESULT: PASS` or `RESULT: FAIL`.
Exit code is 0 on pass, 1 on fail.
"""

import argparse
import os
import sys

try:
    import yaml as _yaml
    HAVE_YAML = True
except ImportError:  # noqa: E722 - deliberate narrow catch
    _yaml = None
    HAVE_YAML = False

BASE_FILES = (
    "PROFILE.md",
    "RELATIONSHIP_TO_OWNER.md",
    "ALIASES.md",
    "PERMISSIONS.md",
    "MEMORY_POLICY.md",
    "INTERACTION_LOG.md",
    "NOTES.md",
)

DIRECT_USER_FILES = ("ROOT.md", "PREFERENCES.md")

DOCUMENT_TYPES = frozenset({
    "index", "profile", "relationship_to_owner", "aliases", "permissions",
    "memory_policy", "interaction_log", "notes", "root", "preferences",
    "relationship", "project",
})

SENSITIVITIES = frozenset({"public", "basic", "private", "sensitive", "secret"})

TRUST_TIERS = frozenset({
    "tier_0_unknown", "tier_1_recognized", "tier_2_collaborator",
    "tier_3_family_close", "tier_4_owner_admin",
})

_TRUE_VALUES = (True, "true", "True", "yes", "Yes", "on", "On")


# ---------------------------------------------------------------------------
# Minimal YAML-subset frontmatter parser (fallback when PyYAML is unavailable)
# ---------------------------------------------------------------------------

def _parse_scalar(text):
    """Parse a scalar for the stdlib fallback parser."""
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part) for part in _split_inline_list(inner)]
    low = text.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "none", "~", ""):
        return None
    try:
        return int(text)
    except ValueError:
        return text


def _split_inline_list(inner):
    """Split an inline list body on commas, respecting quoted segments."""
    parts = []
    buf = []
    quote = None
    for ch in inner:
        if quote is not None:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return parts


def _parse_block(lines, index, indent):
    """Parse a mapping or list whose lines sit at ``indent``.

    Returns ``(value, next_index)``. Supports the subset of YAML used by the
    Person Roots seed files: nested block mappings, block lists of scalars,
    and inline scalars/lists.
    """
    if index >= len(lines):
        return {}, index
    cur_indent, cur_text = lines[index]
    if cur_indent != indent:
        return {}, index
    if cur_text.startswith("- "):
        items = []
        while index < len(lines):
            line_indent, line_text = lines[index]
            if line_indent != indent or not line_text.startswith("- "):
                break
            items.append(_parse_scalar(line_text[2:].strip()))
            index += 1
        return items, index
    mapping = {}
    while index < len(lines):
        line_indent, line_text = lines[index]
        if line_indent < indent:
            break
        if line_indent != indent:
            index += 1
            continue
        if line_text.startswith("- "):
            break
        if ":" not in line_text:
            index += 1
            continue
        key, _, value = line_text.partition(":")
        key = key.strip()
        value = value.strip()
        index += 1
        if value == "":
            if index < len(lines) and lines[index][0] > indent:
                child, index = _parse_block(lines, index, lines[index][0])
                mapping[key] = child
            else:
                mapping[key] = None
        else:
            mapping[key] = _parse_scalar(value)
    return mapping, index


def _parse_frontmatter_fallback(text):
    """Parse frontmatter with stdlib only (simple key/list/nested fields)."""
    lines = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        lines.append((indent, line.lstrip()))
    if not lines:
        return {}
    value, _ = _parse_block(lines, 0, lines[0][0])
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# Frontmatter loading
# ---------------------------------------------------------------------------

def _load_frontmatter(path):
    """Return ``(ok, data_or_error_message)`` for a markdown file."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
    except OSError as exc:
        return False, "cannot read file: %s" % exc
    if not content.startswith("---"):
        return False, "missing YAML frontmatter (file must start with '---')"
    lines = content.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return False, "frontmatter block not closed (missing trailing '---')"
    fm_text = "\n".join(lines[1:end])
    if not fm_text.strip():
        return False, "empty frontmatter block"
    if HAVE_YAML:
        assert _yaml is not None  # HAVE_YAML implies the import succeeded
        try:
            data = _yaml.safe_load(fm_text)
        except _yaml.YAMLError as exc:
            return False, "YAML parse error: %s" % exc
    else:
        data = _parse_frontmatter_fallback(fm_text)
    if not isinstance(data, dict):
        return False, "frontmatter must parse to a mapping, got %s" % type(data).__name__
    return True, data


# ---------------------------------------------------------------------------
# INDEX.md resolver table
# ---------------------------------------------------------------------------

def _person_ids_from_index(index_path):
    """Return the list of person IDs declared in the INDEX.md Resolver Table."""
    person_ids = []
    try:
        with open(index_path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return person_ids
    in_table = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            in_table = stripped == "## Resolver Table"
            continue
        if not in_table or not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.split("|")]
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        if len(cells) < 2:
            continue
        if set(cells[0]) <= set("- "):  # separator row like |---|---|
            continue
        if cells[0].lower() in ("person id", "person_id"):
            continue
        person_ids.append(cells[0])
    return person_ids


# ---------------------------------------------------------------------------
# Core validation
# ---------------------------------------------------------------------------

def validate(root):
    """Run all checks. Returns ``(errors, warnings, stats)``."""
    errors = []
    warnings = []
    stats = {"persons": 0, "files": 0}

    # 1. root exists
    if not os.path.isdir(root):
        return ["root directory does not exist: %s" % root], warnings, stats

    # 2. INDEX.md exists
    index_path = os.path.join(root, "INDEX.md")
    if not os.path.isfile(index_path):
        errors.append("missing INDEX.md at root")

    # Discover person folders (skip underscore-prefixed dirs like _templates)
    folder_names = []
    try:
        entries = sorted(os.listdir(root))
    except OSError as exc:
        return ["cannot list root: %s" % exc], warnings, stats
    for name in entries:
        if name.startswith("_"):
            continue
        if os.path.isdir(os.path.join(root, name)):
            folder_names.append(name)

    index_ids = _person_ids_from_index(index_path) if os.path.isfile(index_path) else []

    # 3. person folders listed in index exist (and vice versa)
    for pid in index_ids:
        if pid not in folder_names:
            errors.append("INDEX.md lists person '%s' but folder '%s/' does not exist" % (pid, pid))
    for name in folder_names:
        if name not in index_ids:
            errors.append("folder '%s/' exists on disk but is not listed in INDEX.md resolver table" % name)

    person_ids = folder_names
    stats["persons"] = len(person_ids)

    # 4/5. per-person checks
    for pid in person_ids:
        person_dir = os.path.join(root, pid)

        for base in BASE_FILES:
            if not os.path.isfile(os.path.join(person_dir, base)):
                errors.append("%s: missing required base file %s" % (pid, base))

        profile_fm = {}
        profile_path = os.path.join(person_dir, "PROFILE.md")
        if os.path.isfile(profile_path):
            ok, data = _load_frontmatter(profile_path)
            if ok and isinstance(data, dict):
                profile_fm = data

        direct_user = profile_fm.get("direct_user", False) in _TRUE_VALUES

        if direct_user:
            for extra in DIRECT_USER_FILES:
                if not os.path.isfile(os.path.join(person_dir, extra)):
                    errors.append("%s: direct user missing %s" % (pid, extra))
            if not os.path.isfile(os.path.join(person_dir, "RELATIONSHIPS", "owner.md")):
                errors.append("%s: direct user missing RELATIONSHIPS/owner.md" % pid)

            project_lanes = profile_fm.get("project_lanes")
            projects_dir = os.path.join(person_dir, "PROJECTS")
            if isinstance(project_lanes, list) and project_lanes:
                if not os.path.isdir(projects_dir):
                    errors.append("%s: declares project_lanes but PROJECTS/ is missing" % pid)
                else:
                    project_files = [n for n in os.listdir(projects_dir) if n.endswith(".md")]
                    if not project_files:
                        errors.append("%s: declares project_lanes but PROJECTS/ has no .md files" % pid)
                    for lane in project_lanes:
                        if isinstance(lane, str) and not os.path.isfile(
                            os.path.join(projects_dir, lane + ".md")
                        ):
                            errors.append(
                                "%s: declared project lane '%s' has no PROJECTS/%s.md" % (pid, lane, lane)
                            )
            elif os.path.isdir(projects_dir):
                project_files = [n for n in os.listdir(projects_dir) if n.endswith(".md")]
                if not project_files:
                    warnings.append("%s: PROJECTS/ exists but contains no .md files" % pid)

        # Explicit spec: Sample Developer's code-roast lane file
        if pid == "sample-dev" and not os.path.isfile(os.path.join(person_dir, "PROJECTS", "code-review.md")):
            errors.append("sample-dev: expected PROJECTS/code-review.md (code-roast lane)")

    # 6-12. frontmatter / field checks on every markdown file
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fname in sorted(filenames):
            if not fname.endswith(".md"):
                continue
            path = os.path.join(dirpath, fname)
            stats["files"] += 1
            ok, data = _load_frontmatter(path)
            if not ok:
                errors.append("%s: %s" % (os.path.relpath(path, root), data))
                continue
            if not isinstance(data, dict):
                errors.append("%s: frontmatter did not parse to a mapping" % os.path.relpath(path, root))
                continue
            rel_path = os.path.relpath(path, root).replace(os.sep, "/")
            top = rel_path.split("/")[0]

            # 8. person_id matches folder slug for person files
            if top in person_ids:
                pid = data.get("person_id")
                if pid != top:
                    errors.append(
                        "%s: person_id '%s' does not match folder slug '%s'" % (rel_path, pid, top)
                    )

            # 9. document_type
            dtype = data.get("document_type")
            if dtype not in DOCUMENT_TYPES:
                errors.append("%s: invalid document_type %r" % (rel_path, dtype))

            # 10. sensitivity
            sens = data.get("sensitivity")
            if sens not in SENSITIVITIES:
                errors.append("%s: invalid sensitivity %r" % (rel_path, sens))

            # 11. trust_tier when present
            if "trust_tier" in data and data.get("trust_tier") not in TRUST_TIERS:
                errors.append("%s: invalid trust_tier %r" % (rel_path, data.get("trust_tier")))

            # 12. relationship-to-Owner files default to shareable_by_default: false
            if dtype == "relationship_to_owner":
                shareable = data.get("shareable_by_default")
                if shareable in _TRUE_VALUES:
                    errors.append(
                        "%s: shareable_by_default must default to false (got %r)" % (rel_path, shareable)
                    )

    return errors, warnings, stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate the Pantheon Person Roots seed tree."
    )
    parser.add_argument(
        "--root",
        default="~/.pantheon/person-roots/relationships",
        help="Path to the relationships root (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    errors, warnings, stats = validate(args.root)

    for warning in warnings:
        print("WARN: %s" % warning)
    for error in errors:
        print("ERROR: %s" % error)

    if errors:
        print("RESULT: FAIL (%d error(s), %d warning(s))" % (len(errors), len(warnings)))
        return 1
    print(
        "RESULT: PASS (%d person folder(s), %d file(s) checked, %d warning(s))"
        % (stats["persons"], stats["files"], len(warnings))
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
