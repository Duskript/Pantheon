"""Person-root resolver for names, aliases, and safe folder paths.

The resolver reads the alpha markdown tree at
``~/.pantheon/person-roots/relationships`` and returns safe in-memory
records. It is read-only by design: account linking, runtime god injection, and
profile mutation happen in later layers after ACL checks.

Resolver responsibilities:

1. List person folders while ignoring implementation directories like
   ``_templates``.
2. Load profile/permission frontmatter into a ``PersonRecord``.
3. Resolve aliases case-insensitively from both PROFILE.md and ALIASES.md.
4. Guard path lookups so callers cannot escape a person root using ``..``.
"""

from __future__ import annotations

import os
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from lib.person_roots.frontmatter import markdown_table_rows, read_frontmatter
from lib.person_roots.schema import PersonRecord

DEFAULT_ROOT = Path(os.environ.get('PERSON_ROOTS_ROOT', str(Path.home() / '.pantheon' / 'person-roots' / 'relationships')))
_TRUE_VALUES = {True, 'true', 'True', 'yes', 'Yes', 'on', 'On'}
_COMMON_AMBIGUOUS_FIRST_NAMES = frozenset({
    'alex',
    'alesample-dev',
    'amy',
    'andrew',
    'anna',
    'anthony',
    'ashley',
    'chris',
    'daniel',
    'david',
    'emily',
    'james',
    'jason',
    'jennifer',
    'john',
    'josh',
    'matt',
    'michael',
    'mike',
    'nick',
    'robert',
    'sam',
    'samantha',
    'samuel',
    'sarah',
    'steve',
    'will',
})


class PersonRootsRepository:
    """Read-only repository for the alpha Person Roots markdown tree."""

    def __init__(self, root: str | Path = DEFAULT_ROOT):
        self.root = Path(root).expanduser().resolve()

    def list_people(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(
            path.name
            for path in self.root.iterdir()
            if path.is_dir() and not path.name.startswith('_')
        )

    def load_person(self, person_id: str) -> PersonRecord:
        if person_id not in self.list_people():
            raise KeyError(f"Unknown person_id: {person_id}")
        folder = self.root / person_id
        profile = read_frontmatter(folder / 'PROFILE.md')
        permissions = read_frontmatter(folder / 'PERMISSIONS.md')
        aliases = _dedupe([person_id, *_as_list(profile.get('aliases'))])
        aliases.extend(alias for alias in _aliases_from_aliases_file(folder / 'ALIASES.md') if alias not in aliases)
        direct_user = profile.get('direct_user') in _TRUE_VALUES or permissions.get('direct_user') in _TRUE_VALUES
        return PersonRecord(
            person_id=person_id,
            display_name=str(profile.get('display_name') or person_id),
            aliases=tuple(aliases),
            direct_user=direct_user,
            trust_tier=str(profile.get('trust_tier') or permissions.get('trust_tier') or 'tier_1_recognized'),
            folder=folder,
            notes=_index_notes(self.root / 'INDEX.md', person_id),
            profile_frontmatter=profile,
            permissions_frontmatter=permissions,
            allowed_context=tuple(_section_list(folder / 'PERMISSIONS.md', 'Allowed context')),
            denied_context=tuple(_section_list(folder / 'PERMISSIONS.md', 'Denied context')),
        )

    def resolve_name(self, name_or_alias: str) -> str | None:
        needle = _normalize(name_or_alias)
        if not needle:
            return None
        for person_id in self.list_people():
            person = self.load_person(person_id)
            candidates = [person.person_id, person.display_name, *person.aliases]
            if any(_normalize(candidate) == needle for candidate in candidates):
                return person_id
        return None

    def classify_candidate_name(self, name_or_alias: str) -> dict[str, Any]:
        """Classify an observed name before automatic person-root creation.

        Confirmed aliases still resolve immediately once the owner has confirmed that mapping. Unknown short/common names or names similar to existing aliases must ask the owner before creating a new root or merging with an existing person.
        """

        needle = _normalize(name_or_alias)
        if not needle:
            return {
                'decision': 'ignore',
                'person_id': None,
                'requires_clarification': False,
                'similar_people': (),
                'reason': 'Empty name candidate.',
            }

        resolved = self.resolve_name(name_or_alias)
        if resolved is not None:
            return {
                'decision': 'known_person',
                'person_id': resolved,
                'requires_clarification': False,
                'similar_people': (),
                'reason': 'Name matches a confirmed person ID, display name, or alias.',
            }

        similar_people = self.find_similar_people(name_or_alias)
        if _is_common_ambiguous_name(needle):
            return {
                'decision': 'needs_owner_approval',
                'person_id': None,
                'requires_clarification': True,
                'similar_people': tuple(similar_people),
                'reason': 'Short/common first name must be clarified before creating or merging a person root.',
            }
        if similar_people:
            return {
                'decision': 'needs_owner_approval',
                'person_id': None,
                'requires_clarification': True,
                'similar_people': tuple(similar_people),
                'reason': 'Name is similar to existing person roots or aliases; ask before creating a duplicate.',
            }
        return {
            'decision': 'new_candidate',
            'person_id': None,
            'requires_clarification': True,
            'similar_people': (),
            'reason': 'Unknown person name must be clarified immediately before creating a new root.',
        }

    def find_similar_people(self, name_or_alias: str) -> list[dict[str, str]]:
        """Return existing people whose IDs/display names/aliases resemble a candidate."""

        needle = _normalize(name_or_alias)
        if not needle:
            return []
        matches: list[dict[str, str]] = []
        seen_people: set[str] = set()
        for person_id in self.list_people():
            person = self.load_person(person_id)
            candidates = [person.person_id, person.display_name, *person.aliases]
            for candidate in candidates:
                normalized_candidate = _normalize(candidate)
                if not normalized_candidate or normalized_candidate == needle:
                    continue
                if _names_are_similar(needle, normalized_candidate):
                    if person_id not in seen_people:
                        matches.append({
                            'person_id': person_id,
                            'display_name': person.display_name,
                            'matched_alias': candidate,
                        })
                        seen_people.add(person_id)
                    break
        return matches

    def path_for(self, person_id: str, relative_path: str | Path) -> Path:
        person_root = (self.root / person_id).resolve()
        if not person_root.is_dir():
            raise KeyError(f"Unknown person_id: {person_id}")
        candidate = (person_root / relative_path).resolve()
        try:
            candidate.relative_to(person_root)
        except ValueError as exc:
            raise ValueError(f"Path escapes person root: {relative_path}") from exc
        return candidate


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = _normalize(value)
        if key and key not in seen:
            seen.add(key)
            out.append(value)
    return out


def _normalize(value: str) -> str:
    return ' '.join(str(value).strip().casefold().split())


def _is_common_ambiguous_name(normalized_name: str) -> bool:
    parts = normalized_name.split()
    if len(parts) != 1:
        return False
    return parts[0] in _COMMON_AMBIGUOUS_FIRST_NAMES or len(parts[0]) <= 3


def _names_are_similar(left: str, right: str) -> bool:
    if len(left) < 3 or len(right) < 3:
        return False
    if left.startswith(right) or right.startswith(left):
        return True
    return SequenceMatcher(None, left, right).ratio() >= 0.78


def _aliases_from_aliases_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    data = read_frontmatter(path)
    return _as_list(data.get('aliases'))


def _index_notes(index_path: Path, person_id: str) -> str:
    for row in markdown_table_rows(index_path, 'Resolver Table'):
        if row.get('Person ID') == person_id:
            return row.get('Notes', '')
    return ''


def _section_list(path: Path, heading: str) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding='utf-8').splitlines()
    in_section = False
    items: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('## '):
            if in_section:
                break
            in_section = stripped == f'## {heading}'
            continue
        if in_section and stripped.startswith('- '):
            items.append(stripped[2:].strip())
    return items
