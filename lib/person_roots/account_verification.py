"""Account verification workflow for Person Roots.

Account links prove that a platform account maps to a person root. They do not
broaden context access by themselves; ACL rules still decide what the account
may retrieve. This module provides the deterministic file-update primitive used
after live platform proof has already been obtained by the operator.

For Discord, pass a member proof dictionary from ``discord_admin member_info``.
The proof must match the supplied account ID and must not be a bot account.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from lib.person_roots.accounts import parse_account_links, resolve_account
from lib.person_roots.resolver import DEFAULT_ROOT, PersonRootsRepository

_SUPPORTED_PLATFORMS = {'discord', 'telegram'}


@dataclass(frozen=True)
class AccountVerificationPlan:
    """A bounded mutation plan for one account-link verification."""

    root: Path
    person_id: str
    platform: str
    account_id: str
    verified_by: str
    status_note: str
    index_path: Path
    permissions_path: Path
    already_verified: bool
    current_resolved_person: str | None


def build_account_verification_plan(
    *,
    person_id: str,
    platform: str,
    account_id: str,
    verified_by: str = 'owner',
    root: str | Path = DEFAULT_ROOT,
    proof: Mapping[str, Any] | None = None,
    today: str | None = None,
) -> AccountVerificationPlan:
    """Validate inputs and build a one-person account verification plan."""

    root_path = Path(root).expanduser()
    platform_key = platform.strip().casefold()
    account_key = str(account_id).strip()
    verifier = str(verified_by).strip() or 'owner'
    if platform_key not in _SUPPORTED_PLATFORMS:
        raise ValueError(f'Unsupported platform: {platform}')
    if not account_key or account_key.startswith('(pending'):
        raise ValueError('A real account_id is required')

    repo = PersonRootsRepository(root_path)
    canonical_person = repo.resolve_name(person_id) or person_id
    repo.load_person(canonical_person)

    existing_person = resolve_account(platform_key, account_key, root_path)
    if existing_person and existing_person != canonical_person:
        raise ValueError(f'{platform_key}:{account_key} already resolves to {existing_person}')

    status_note = _proof_status_note(platform_key, account_key, proof, today=today)
    return AccountVerificationPlan(
        root=root_path,
        person_id=canonical_person,
        platform=platform_key,
        account_id=account_key,
        verified_by=verifier,
        status_note=status_note,
        index_path=root_path / 'INDEX.md',
        permissions_path=root_path / canonical_person / 'PERMISSIONS.md',
        already_verified=existing_person == canonical_person,
        current_resolved_person=existing_person,
    )


def apply_account_verification_plan(plan: AccountVerificationPlan, *, dry_run: bool = False) -> dict[str, Any]:
    """Apply a verified account-link plan to INDEX.md and PERMISSIONS.md."""

    index_text = plan.index_path.read_text(encoding='utf-8')
    permissions_text = plan.permissions_path.read_text(encoding='utf-8')

    new_index = _upsert_account_link_row(index_text, plan)
    new_permissions = _upsert_permissions_account_id(permissions_text, plan)

    changed_files: list[str] = []
    if new_index != index_text:
        changed_files.append(str(plan.index_path))
    if new_permissions != permissions_text:
        changed_files.append(str(plan.permissions_path))

    if not dry_run:
        if new_index != index_text:
            plan.index_path.write_text(new_index, encoding='utf-8')
        if new_permissions != permissions_text:
            plan.permissions_path.write_text(new_permissions, encoding='utf-8')

    return {
        'dry_run': bool(dry_run),
        'person_id': plan.person_id,
        'platform': plan.platform,
        'account_id': plan.account_id,
        'verified_by': plan.verified_by,
        'already_verified': plan.already_verified,
        'changed_files': changed_files,
        'would_change': bool(changed_files),
        'status_note': plan.status_note,
    }


def verify_account_link(
    *,
    person_id: str,
    platform: str,
    account_id: str,
    verified_by: str = 'owner',
    root: str | Path = DEFAULT_ROOT,
    proof: Mapping[str, Any] | None = None,
    today: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Convenience wrapper: build and apply one account verification plan."""

    plan = build_account_verification_plan(
        person_id=person_id,
        platform=platform,
        account_id=account_id,
        verified_by=verified_by,
        root=root,
        proof=proof,
        today=today,
    )
    return apply_account_verification_plan(plan, dry_run=dry_run)


def _proof_status_note(
    platform: str,
    account_id: str,
    proof: Mapping[str, Any] | None,
    *,
    today: str | None,
) -> str:
    day = today or date.today().isoformat()
    if platform != 'discord':
        return f'Verified by operator on {day}.'
    if proof is None:
        raise ValueError('Discord verification requires member_info proof')
    proof_id = str(proof.get('user_id') or '').strip()
    if proof_id != account_id:
        raise ValueError(f'Discord proof user_id {proof_id!r} does not match account_id {account_id!r}')
    if bool(proof.get('bot')):
        raise ValueError('Discord proof belongs to a bot account, not a human user')
    display = str(proof.get('display_name') or proof.get('username') or account_id).strip()
    username = str(proof.get('username') or '').strip()
    label = f'{display} ({username})' if username and username != display else display
    return f'Live Discord guild member verified as {label} on {day}.'


def _upsert_account_link_row(text: str, plan: AccountVerificationPlan) -> str:
    lines = text.splitlines()
    start = _find_heading(lines, 'Account Links')
    if start is None:
        raise ValueError('INDEX.md is missing ## Account Links')
    table_start = _find_next_table_line(lines, start + 1)
    if table_start is None or table_start + 1 >= len(lines):
        raise ValueError('Account Links table is missing')
    table_end = table_start
    while table_end < len(lines) and lines[table_end].lstrip().startswith('|'):
        table_end += 1

    new_row = _account_link_row(plan)
    replaced = False
    body = lines[table_start + 2:table_end]
    for offset, row in enumerate(body, start=table_start + 2):
        cells = _split_table_row(row)
        if len(cells) < 6:
            continue
        if cells[0].casefold() == plan.platform and cells[2] == plan.person_id:
            lines[offset] = new_row
            replaced = True
            break
    if not replaced:
        lines.insert(table_end, new_row)
    return '\n'.join(lines) + '\n'


def _account_link_row(plan: AccountVerificationPlan) -> str:
    return (
        f'| {plan.platform} | {plan.account_id} | {plan.person_id} | verified | '
        f'{plan.verified_by} | {plan.status_note} |'
    )


def _upsert_permissions_account_id(text: str, plan: AccountVerificationPlan) -> str:
    lines = text.splitlines()
    platform_line = None
    for index, line in enumerate(lines):
        if line.strip() == f'{plan.platform}:':
            platform_line = index
            break
    if platform_line is None:
        raise ValueError(f'PERMISSIONS.md is missing {plan.platform} account block')

    user_ids_line = None
    for index in range(platform_line + 1, min(len(lines), platform_line + 8)):
        if lines[index].strip().startswith('user_ids:'):
            user_ids_line = index
            break
    if user_ids_line is None:
        raise ValueError(f'PERMISSIONS.md is missing {plan.platform}.user_ids')

    existing_ids, block_end = _collect_yaml_list(lines, user_ids_line)
    if plan.account_id not in existing_ids:
        indent = lines[user_ids_line][:len(lines[user_ids_line]) - len(lines[user_ids_line].lstrip())]
        if lines[user_ids_line].strip() == 'user_ids: []':
            lines[user_ids_line] = f'{indent}user_ids:'
            lines.insert(user_ids_line + 1, f'{indent}  - "{plan.account_id}"')
        else:
            lines.insert(block_end, f'{indent}  - "{plan.account_id}"')

    for index, line in enumerate(lines):
        if line.startswith('Status:'):
            lines[index] = f'Status: verified — {plan.status_note}'
            break
    else:
        lines.insert(block_end + 1, f'Status: verified — {plan.status_note}')

    return '\n'.join(lines) + '\n'


def _find_heading(lines: list[str], title: str) -> int | None:
    wanted = f'## {title}'.casefold()
    for index, line in enumerate(lines):
        if line.strip().casefold() == wanted:
            return index
    return None


def _find_next_table_line(lines: list[str], start: int) -> int | None:
    for index in range(start, len(lines)):
        if lines[index].lstrip().startswith('|'):
            return index
    return None


def _split_table_row(row: str) -> list[str]:
    return [cell.strip() for cell in row.strip().strip('|').split('|')]


def _collect_yaml_list(lines: list[str], user_ids_line: int) -> tuple[list[str], int]:
    current = lines[user_ids_line].strip()
    if current == 'user_ids: []':
        return [], user_ids_line + 1
    ids: list[str] = []
    index = user_ids_line + 1
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped.startswith('- '):
            break
        ids.append(stripped[2:].strip().strip('"\''))
        index += 1
    return ids, index
