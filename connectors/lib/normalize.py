"""
normalize.py — Convert raw connector output to inbox-ready markdown.

The Athenaeum's intake pipeline (``athenaeum/scripts/process-inbox.py``)
expects a markdown file with YAML frontmatter containing at least ``title`` and
``source``, plus a body. This module is the single point where raw external
content is shaped into that contract.

Contract (from design doc Appendix A):

    ---
    title: "..."
    source: "https://..."
    clipped_at: "2026-06-16T..."
    codex: "Codex-XYZ"        # optional — overrides classifier
    note: "..."               # optional — 200 char highlight
    ---
    # Title

    > Highlighted text

    ## Fetched Content
    ...

process-inbox.py's regex is forgiving (``['"]?(.+?)['"]?`` on each line), but
we always emit double-quoted strings for clarity. ``clipped_at`` is the
ISO-8601 UTC timestamp of when the connector processed the item — not when
the original source content was created.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional


# Maximum length for the ``note:`` highlight. process-inbox.py itself
# truncates to 200, so we follow suit to keep both sides consistent.
_NOTE_MAX = 200

# Maximum length for the ``title:`` frontmatter value. Titles longer than
# this cause file-naming issues downstream (the filename is derived from
# the title slug).
_TITLE_MAX = 200

# Match characters that break the YAML-quoted form or are control characters.
# We allow most printable unicode but strip backslashes, unescaped quotes,
# and newlines that would break the frontmatter.
_UNSAFE_TITLE = re.compile(r'[\\\n\r"\x00-\x1f]')


@dataclass(frozen=True)
class RawItem:
    """The minimum a connector must return from ``fetch_since``.

    Attributes
    ----------
    item_id
        Stable, source-unique identifier (e.g. YouTube video ID, email
        message ID). Used for dedupe and logging.
    title
        Human-readable title. Trimmed; ``\\n``/quotes collapsed.
    url
        Canonical source URL. If your connector doesn't have one, use an
        identifier string like ``"youtube_takeout:VIDEO_ID"``.
    content
        The body content as plain text or markdown. The connector is
        responsible for any HTML→markdown or transcript cleanup before
        this point.
    published_at
        Original publication timestamp (when the source content was created),
        if known. Stored in the frontmatter as ``published_at`` for future
        re-sorting, but ``clipped_at`` is what the pipeline keys on.
    extra
        Free-form connector-specific fields (channel name, duration, etc.).
        These are written as additional frontmatter keys, so anything you
        put here ends up in the inbox file. Keep it small — frontmatter is
        for routing, not for content.
    """

    item_id: str
    title: str
    url: str
    content: str
    published_at: Optional[datetime] = None
    extra: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        # ``Mapping`` is invariant; coerce None to {}.
        if self.extra is None:
            object.__setattr__(self, "extra", {})


def _yaml_quote(value: str) -> str:
    """Quote a value for YAML frontmatter.

    We always emit double-quoted strings (matching the existing inbox file
    format at ``athenaeum/inbox/clip-*.md``). Embedded double-quotes and
    backslashes are escaped; newlines are stripped to spaces so the
    frontmatter stays single-line.
    """
    cleaned = _UNSAFE_TITLE.sub(" ", value)
    cleaned = cleaned.replace("\\", "\\\\").replace('"', '\\"')
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return f'"{cleaned}"'


def _truncate(text: str, max_len: int) -> str:
    """Truncate ``text`` so the returned value is ≤ ``max_len`` chars.

    Cuts on a word boundary when possible, then appends a single-character
    ellipsis (``…``) to mark the truncation. The ellipsis is included in
    the budget, so if there are no good word boundaries near the end we
    drop the ellipsis to stay under the limit.
    """
    if len(text) <= max_len:
        return text
    # Reserve 1 char for the ellipsis.
    budget = max_len - 1
    if budget <= 0:
        return text[:max_len]
    cut = text[:budget]
    # Prefer a word boundary; if the cut ends mid-word, back up to the
    # last space. Fall back to a hard cut if there's no space at all.
    if " " in cut and not cut.endswith(" "):
        last_space = cut.rfind(" ")
        if last_space > budget // 2:  # don't truncate more than half the input
            cut = cut[:last_space]
    return cut.rstrip() + "…"


def _format_dt(dt: datetime) -> str:
    """Format a datetime as ISO-8601 UTC with a ``Z`` suffix (no microseconds)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_to_inbox(
    item: RawItem | Mapping[str, Any],
    source: str,
    codex: str | None = None,
    note: str | None = None,
    *,
    clipped_at: datetime | None = None,
) -> str:
    """Build a complete inbox-ready markdown document for ``item``.

    The output matches the design doc Appendix A contract. ``source`` is
    the connector name (e.g. ``"youtube_takeout"``) — it is added to the
    frontmatter so downstream code can trace which connector produced a
    given file even if the URL changes.

    Parameters
    ----------
    item
        Either a :class:`RawItem` or a dict with the same keys.
    source
        Connector name; written to frontmatter ``connector:`` field.
    codex
        Optional target codex (e.g. ``"Codex-YouTube"``). Overrides
        ``process-inbox.py``'s URL-based classifier. Omit to let the
        classifier decide.
    note
        Optional short highlight (≤200 chars). Falls back to the first
        non-empty line of ``item.content`` if not provided.
    clipped_at
        Override the clipped-at timestamp. Defaults to ``now`` (UTC).

    Returns
    -------
    str
        The full markdown document, including the ``---\\n...\\n---\\n``
        frontmatter and the body.
    """
    if isinstance(item, RawItem):
        d: dict[str, Any] = {
            "item_id": item.item_id,
            "title": item.title,
            "url": item.url,
            "content": item.content,
            "published_at": item.published_at,
            **dict(item.extra),
        }
    else:
        d = dict(item)

    title = str(d.get("title", "")).strip() or "Untitled"
    title = _truncate(title, _TITLE_MAX)
    url = str(d.get("url", "")).strip() or f"{source}:{d.get('item_id', 'unknown')}"
    content = str(d.get("content", ""))

    # If the caller didn't provide a note, derive one from the first
    # meaningful line of content. This is what process-inbox.py itself
    # would do as a fallback, but doing it here gives the connector a
    # chance to override with something smarter (e.g. a transcript
    # summary).
    if note is None:
        for line in content.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith(">"):
                note = stripped
                break
    note_str = _truncate((note or "").strip(), _NOTE_MAX)

    # Build the frontmatter dict in the exact key order the design doc
    # specifies (readability matters more than alphabetical sort here).
    frontmatter: dict[str, str] = {
        "title": _yaml_quote(title),
        "source": _yaml_quote(url),
        "clipped_at": _yaml_quote(_format_dt(clipped_at or datetime.now(timezone.utc))),
        "connector": _yaml_quote(source),
    }
    if d.get("published_at") is not None:
        published = d["published_at"]
        if isinstance(published, datetime):
            frontmatter["published_at"] = _yaml_quote(_format_dt(published))
    if codex:
        frontmatter["codex"] = _yaml_quote(codex)
    if note_str:
        frontmatter["note"] = _yaml_quote(note_str)
    # Pass through any additional structured fields the connector provided.
    # Skip keys we already wrote (above) to avoid duplicates.
    for k, v in d.items():
        if k in {"title", "url", "content", "item_id", "published_at"}:
            continue
        if k in frontmatter:
            continue
        if v is None:
            continue
        if isinstance(v, datetime):
            frontmatter[k] = _yaml_quote(_format_dt(v))
        else:
            frontmatter[k] = _yaml_quote(str(v))

    # Serialize frontmatter as ``key: "value"`` lines (YAML-friendly).
    fm_lines = ["---"]
    for k, v in frontmatter.items():
        fm_lines.append(f"{k}: {v}")
    fm_lines.append("---")
    fm_lines.append("")

    # Body. The shape matches the design: H1 title, optional highlight
    # blockquote, optional "## Fetched Content" section.
    body_lines: list[str] = [f"# {title}", ""]
    if note_str:
        body_lines.append(f"> {note_str}")
        body_lines.append("")
    if content.strip():
        body_lines.append("## Fetched Content")
        body_lines.append("")
        body_lines.append(content.rstrip())
        body_lines.append("")

    return "\n".join(fm_lines + body_lines)


def parse_frontmatter(markdown: str) -> dict[str, str]:
    """Parse the YAML frontmatter of an inbox-shaped markdown document.

    Returns a ``{key: value}`` dict with the outer quotes stripped. Used by
    tests and by connector code that wants to verify what it just wrote.
    Raises ``ValueError`` if the document has no frontmatter block.

    This is intentionally a minimal parser — it does not understand
    multi-line strings, anchors, or references. The contract is single-line
    ``key: "value"`` pairs.
    """
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", markdown, re.DOTALL)
    if not match:
        raise ValueError("No YAML frontmatter found")
    fm_text = match.group(1)
    out: dict[str, str] = {}
    for line in fm_text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        # Strip matching outer quotes (single or double).
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        out[key] = value
    return out
