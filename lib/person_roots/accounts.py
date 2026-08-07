"""Account-link parsing for Pantheon Person Roots.

Account links live in ``relationships/INDEX.md`` because account identity is a
resolver concern, not a private note in an individual profile. This module keeps
resolution intentionally conservative: pending rows, placeholder IDs, and empty
IDs never resolve to a person. That enforces Owner's privacy requirement that
profile automapping and context sharing only happen from verified accounts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lib.person_roots.frontmatter import markdown_table_rows
from lib.person_roots.resolver import DEFAULT_ROOT

_PLACEHOLDER_MARKERS = {'', '—', '-', '(pending — no ID)', '(pending - no ID)'}


@dataclass(frozen=True)
class AccountLink:
    """One platform account link parsed from the index table."""

    platform: str
    account_id: str
    person_id: str
    status: str
    verified_by: str
    notes: str = ''


def parse_account_links(root: str | Path = DEFAULT_ROOT) -> list[AccountLink]:
    """Parse all account-link rows from ``INDEX.md``."""

    index_path = Path(root).expanduser().resolve() / 'INDEX.md'
    links: list[AccountLink] = []
    for row in markdown_table_rows(index_path, 'Account Links'):
        links.append(
            AccountLink(
                platform=(row.get('Platform') or '').casefold(),
                account_id=row.get('Account ID') or '',
                person_id=row.get('Person ID') or '',
                status=(row.get('Status') or '').casefold(),
                verified_by=row.get('Verified By') or '',
                notes=row.get('Notes') or '',
            )
        )
    return links


def resolve_account(platform: str, account_id: str, root: str | Path = DEFAULT_ROOT) -> str | None:
    """Resolve an active verified account to a person ID, if one exists."""

    platform_key = platform.casefold()
    account_key = account_id.strip()
    if _is_placeholder(account_key):
        return None
    for link in parse_account_links(root):
        if link.platform != platform_key:
            continue
        if link.status != 'verified':
            continue
        if _is_placeholder(link.account_id):
            continue
        if link.account_id.strip() == account_key:
            return link.person_id
    return None


def _is_placeholder(value: str) -> bool:
    normalized = ' '.join(value.strip().split())
    return normalized in _PLACEHOLDER_MARKERS or normalized.casefold().startswith('(pending')
