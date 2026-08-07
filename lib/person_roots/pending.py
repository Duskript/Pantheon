"""Durable pending queue for Person Roots decision items.

Cron-safe ingestion cannot pause for interactive ``clarify`` and should not
auto-write approval- or denial-classified facts, so those items are appended to
a durable JSONL queue at ``<root>/_pending/PROPOSALS.jsonl`` for a later
human/god review pass. This module only appends and reads that queue; it never
writes person-root files, never creates roots, and never links accounts.

Record shape (one JSON object per line):

.. code-block:: json

    {
      "created": "YYYY-MM-DD",
      "queue_reason": "clarification|approval|denied|error|...",
      "source_file": "optional path of the originating candidate file",
      "item": { ... original plan/apply item ... }
    }

This module is importable and side-effect free at import time: no top-level
prints, no bare ``except``, only explicit exception types.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

from lib.person_roots.resolver import DEFAULT_ROOT


def pending_path(root: str | Path = DEFAULT_ROOT) -> Path:
    """Return ``<root>/_pending/PROPOSALS.jsonl``."""

    return Path(root).expanduser() / '_pending' / 'PROPOSALS.jsonl'


def append_pending_items(
    items: Iterable[Mapping[str, Any]],
    root: str | Path = DEFAULT_ROOT,
    reason: str | None = None,
    source_file: str | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    """Append serialized pending entries. Create ``_pending/`` if needed.

    Each entry is wrapped in the durable record shape above with
    ``queue_reason`` defaulting to ``pending`` when ``reason`` is omitted.
    Returns ``{"path": str, "count": int}``; when ``items`` is empty the
    queue file is not created and ``count`` is 0.
    """

    path = pending_path(root)
    day = today or date.today().isoformat()

    records: list[dict[str, Any]] = []
    for item in items:
        records.append(
            {
                'created': day,
                'queue_reason': reason or 'pending',
                'source_file': source_file,
                'item': dict(item),
            }
        )
    if not records:
        return {'path': str(path), 'count': 0}

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a', encoding='utf-8') as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + '\n')
    return {'path': str(path), 'count': len(records)}


def read_pending_items(
    root: str | Path = DEFAULT_ROOT,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Read pending JSONL entries; tolerate blank lines.

    Raises ValueError on malformed JSON or a non-object line (explicit
    exception type, never bare). ``limit`` returns the oldest ``limit``
    records.
    """

    path = pending_path(root)
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    with open(path, 'r', encoding='utf-8') as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f'Invalid JSON on line {line_number} of {path}: {exc}'
                ) from exc
            if not isinstance(record, dict):
                raise ValueError(
                    f'Line {line_number} of {path} is not a JSON object'
                )
            records.append(record)

    if limit is not None:
        return records[:limit]
    return records
