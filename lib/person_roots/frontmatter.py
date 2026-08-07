"""Markdown frontmatter and table parsing helpers for Person Roots."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml as _yaml
except ImportError:  # pragma: no cover - exercised only on minimal Python envs
    _yaml = None


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    lowered = value.lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    if lowered in {"", "null", "none", "~"}:
        return None
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part) for part in inner.split(",")]
    return value


def _fallback_parse(frontmatter: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current_key: str | None = None
    for raw in frontmatter.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        stripped = raw.strip()
        if stripped.startswith("- ") and current_key:
            result.setdefault(current_key, [])
            if isinstance(result[current_key], list):
                result[current_key].append(_parse_scalar(stripped[2:]))
            continue
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        current_key = key
        result[key] = [] if not value.strip() else _parse_scalar(value)
    return result


def read_frontmatter(path: str | Path) -> dict[str, Any]:
    """Read YAML frontmatter from a markdown file."""

    content = Path(path).read_text(encoding="utf-8")
    if not content.startswith("---"):
        raise ValueError(f"{path} has no YAML frontmatter")
    lines = content.splitlines()
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        raise ValueError(f"{path} frontmatter is not closed")
    frontmatter = "\n".join(lines[1:end])
    if _yaml is not None:
        data = _yaml.safe_load(frontmatter)
        return data if isinstance(data, dict) else {}
    return _fallback_parse(frontmatter)


def markdown_table_rows(path: str | Path, heading: str) -> list[dict[str, str]]:
    """Return rows from a simple markdown table under ``## heading``."""

    lines = Path(path).read_text(encoding="utf-8").splitlines()
    in_section = False
    table_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            if in_section and table_lines:
                break
            in_section = stripped == f"## {heading}"
            continue
        if in_section and stripped.startswith("|"):
            table_lines.append(stripped)
        elif in_section and table_lines and stripped:
            break
    if len(table_lines) < 2:
        return []
    headers = _cells(table_lines[0])
    rows = []
    for line in table_lines[2:]:
        values = _cells(line)
        if len(values) < len(headers):
            continue
        rows.append(dict(zip(headers, values)))
    return rows


def _cells(line: str) -> list[str]:
    cells = [cell.strip() for cell in line.strip().split("|")]
    if cells and cells[0] == "":
        cells = cells[1:]
    if cells and cells[-1] == "":
        cells = cells[:-1]
    return cells
