"""Deterministic source-file observer for Person Roots candidate facts.

This module turns explicit operator-authored marker lines into structured
``CandidateFact`` dictionaries for the existing ingest pipeline. It deliberately
avoids free-form prose extraction: if a line does not use a supported marker
syntax, it is ignored rather than guessed.

Supported marker lines::

    PERSON_ROOT: <name> | <field> | <value>
    PERSON_FACT: <name> | <field> | <value>
    @person-root <name> | <field> | <value>
    @person-fact <name> | <field> | <value>
    PERSON_ROOT candidate_name="Demo Person" field="profile.known_context" value="..."

No name resolution, proposal classification, queue writes, or profile mutation
happens here. The output is JSONL fuel for ``unattended_ingest_files``.
"""

from __future__ import annotations

import hashlib
import json
import shlex
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from lib.person_roots.ingest import candidate_from_mapping

_SUPPORTED_SUFFIXES = {'.md', '.txt', '.json', '.jsonl'}
_PIPE_PREFIXES = ('PERSON_ROOT:', 'PERSON_FACT:', '@person-root', '@person-fact')
_KV_PREFIXES = ('PERSON_ROOT ', 'PERSON_FACT ', '@person-root ', '@person-fact ')
_EXTRACTOR_NAME = 'person_roots_observer'


def extract_candidates_from_text(
    text: str,
    *,
    source_path: str | None = None,
    source_person_id: str = 'owner',
    source_type: str = 'owner_account',
    sensitivity: str = 'private',
) -> list[dict[str, Any]]:
    """Extract explicit Person Roots candidate marker lines from ``text``.

    Extraction is intentionally conservative. Malformed marker lines are
    ignored, not repaired. Returned dictionaries are validated through
    ``candidate_from_mapping`` so callers can feed them to the ingest core.
    """

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        parsed = _parse_marker_line(
            raw_line,
            source_path=source_path,
            line_number=line_number,
            source_person_id=source_person_id,
            source_type=source_type,
            default_sensitivity=sensitivity,
        )
        if parsed is None:
            continue

        try:
            # Normalize and validate the exact shape consumed by ingest.py.
            fact = candidate_from_mapping(parsed)
        except ValueError:
            continue

        normalized = {
            'candidate_name': fact.candidate_name,
            'field': fact.field,
            'value': fact.value,
            'source_person_id': fact.source_person_id,
            'source_type': fact.source_type,
            'sensitivity': fact.sensitivity,
            'observed_context': fact.observed_context,
            'provenance': fact.provenance,
        }
        key = json.dumps(normalized, sort_keys=True, ensure_ascii=False, default=str)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(normalized)

    return candidates


def observe_source_files(
    sources: Iterable[str | Path],
    *,
    incoming_dir: str | Path,
    source_person_id: str = 'owner',
    source_type: str = 'owner_account',
    sensitivity: str = 'private',
    recursive: bool = False,
    today: str | None = None,
) -> dict[str, Any]:
    """Read source files/directories and write extracted candidates to JSONL.

    Returns a serializable summary. If no candidates are found, no incoming
    file is created.
    """

    source_paths = _expand_sources(sources, recursive=recursive)
    files_read = 0
    errors: list[str] = []
    candidates: list[dict[str, Any]] = []

    for path in source_paths:
        try:
            text = path.read_text(encoding='utf-8')
        except UnicodeDecodeError as exc:
            errors.append(f'{path}: cannot decode as UTF-8: {exc}')
            continue
        except OSError as exc:
            errors.append(f'{path}: {exc}')
            continue

        files_read += 1
        candidates.extend(
            extract_candidates_from_text(
                text,
                source_path=str(path),
                source_person_id=source_person_id,
                source_type=source_type,
                sensitivity=sensitivity,
            )
        )

    output_path: Path | None = None
    if candidates:
        incoming = Path(incoming_dir).expanduser()
        incoming.mkdir(parents=True, exist_ok=True)
        output_path = _unique_output_path(incoming, candidates, today=today)
        _write_jsonl(output_path, candidates)

    return {
        'files_seen': len(source_paths),
        'files_read': files_read,
        'candidates': len(candidates),
        'output_path': str(output_path) if output_path is not None else None,
        'errors': errors,
    }


def _parse_marker_line(
    raw_line: str,
    *,
    source_path: str | None,
    line_number: int,
    source_person_id: str,
    source_type: str,
    default_sensitivity: str,
) -> dict[str, Any] | None:
    line = raw_line.strip()
    if not line:
        return None

    pipe_payload: str | None = None
    for prefix in _PIPE_PREFIXES:
        if line.startswith(prefix):
            pipe_payload = line[len(prefix):].strip()
            break
    if pipe_payload is not None and '|' in pipe_payload:
        return _parse_pipe_payload(
            pipe_payload,
            source_path=source_path,
            line_number=line_number,
            source_person_id=source_person_id,
            source_type=source_type,
            sensitivity=default_sensitivity,
            observed_context=raw_line.strip(),
        )

    for prefix in _KV_PREFIXES:
        if line.startswith(prefix):
            return _parse_key_value_payload(
                line[len(prefix):].strip(),
                source_path=source_path,
                line_number=line_number,
                source_person_id=source_person_id,
                source_type=source_type,
                default_sensitivity=default_sensitivity,
                observed_context=raw_line.strip(),
            )
    return None


def _parse_pipe_payload(
    payload: str,
    *,
    source_path: str | None,
    line_number: int,
    source_person_id: str,
    source_type: str,
    sensitivity: str,
    observed_context: str,
) -> dict[str, Any] | None:
    parts = [part.strip() for part in payload.split('|', 2)]
    if len(parts) != 3 or not all(parts):
        return None
    name, field, value = parts
    return _candidate_dict(
        name,
        field,
        value,
        source_path=source_path,
        line_number=line_number,
        source_person_id=source_person_id,
        source_type=source_type,
        sensitivity=sensitivity,
        observed_context=observed_context,
    )


def _parse_key_value_payload(
    payload: str,
    *,
    source_path: str | None,
    line_number: int,
    source_person_id: str,
    source_type: str,
    default_sensitivity: str,
    observed_context: str,
) -> dict[str, Any] | None:
    try:
        tokens = shlex.split(payload)
    except ValueError:
        return None

    pairs: dict[str, str] = {}
    for token in tokens:
        if '=' not in token:
            return None
        key, value = token.split('=', 1)
        key = key.strip()
        if not key:
            return None
        pairs[key] = value.strip()

    name = pairs.get('candidate_name') or pairs.get('name')
    field = pairs.get('field')
    value = pairs.get('value')
    if not name or not field or value is None:
        return None

    return _candidate_dict(
        name,
        field,
        value,
        source_path=source_path,
        line_number=line_number,
        source_person_id=pairs.get('source_person_id', source_person_id),
        source_type=pairs.get('source_type', source_type),
        sensitivity=pairs.get('sensitivity', default_sensitivity),
        observed_context=observed_context,
    )


def _candidate_dict(
    name: str,
    field: str,
    value: str,
    *,
    source_path: str | None,
    line_number: int,
    source_person_id: str,
    source_type: str,
    sensitivity: str,
    observed_context: str,
) -> dict[str, Any]:
    return {
        'candidate_name': name,
        'field': field,
        'value': value,
        'source_person_id': source_person_id,
        'source_type': source_type,
        'sensitivity': sensitivity,
        'observed_context': observed_context,
        'provenance': {
            'source_path': source_path,
            'line_number': line_number,
            'extractor': _EXTRACTOR_NAME,
        },
    }


def _expand_sources(sources: Iterable[str | Path], *, recursive: bool) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for source in sources:
        path = Path(source).expanduser()
        candidates: list[Path]
        if path.is_dir():
            iterator = path.rglob('*') if recursive else path.iterdir()
            candidates = [child for child in iterator if child.is_file() and child.suffix.lower() in _SUPPORTED_SUFFIXES]
        elif path.is_file() and path.suffix.lower() in _SUPPORTED_SUFFIXES:
            candidates = [path]
        else:
            candidates = []
        for candidate in sorted(candidates):
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            files.append(candidate)
    return files


def _unique_output_path(incoming: Path, candidates: list[dict[str, Any]], *, today: str | None) -> Path:
    day = today or date.today().isoformat()
    digest = hashlib.sha256(
        json.dumps(candidates, sort_keys=True, ensure_ascii=False, default=str).encode('utf-8')
    ).hexdigest()[:12]
    path = incoming / f'person-roots-candidates-{day}-{digest}.jsonl'
    if not path.exists():
        return path
    counter = 1
    while True:
        candidate = incoming / f'person-roots-candidates-{day}-{digest}-{counter}.jsonl'
        if not candidate.exists():
            return candidate
        counter += 1


def _write_jsonl(path: Path, candidates: list[dict[str, Any]]) -> None:
    with open(path, 'w', encoding='utf-8') as handle:
        for candidate in candidates:
            handle.write(json.dumps(candidate, ensure_ascii=False, sort_keys=True, default=str) + '\n')
