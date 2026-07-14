from __future__ import annotations

import json
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/home/konan/pantheon')
REPORTS = ROOT / 'reports'
DATE = '2026-07-06'
SCAN_TS = '2026-07-06T11:09:00Z'
REPO = 'Duskript/Pantheon'
MILESTONE = 'tech-debt'
FILED_JSON = REPORTS / f'tech-debt-{DATE}-filed.json'
ISSUES_JSON = REPORTS / f'tech-debt-{DATE}-issues.json'

@dataclass
class IssueSpec:
    title: str
    category: str
    severity: str
    file: str
    line: int
    body: str
    labels: list[str]


def load_findings():
    return json.loads(ISSUES_JSON.read_text())


def gh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(['gh', *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc


def issue_exists(title: str) -> bool:
    proc = gh('issue', 'list', '--repo', REPO, '--search', f'{title} in:title', '--state', 'all', '--json', 'number', '--jq', 'length', check=False)
    if proc.returncode != 0:
        # fallback to no-skip on search failures; better to file than silently skip
        return False
    try:
        return int(proc.stdout.strip() or '0') > 0
    except ValueError:
        return False


def format_table(rows):
    out = ['| File | Line | Description |', '|---|---:|---|']
    for r in rows:
        rel = r['file'].replace(ROOT.as_posix().rstrip('/') + '/', '')
        desc = r['desc'].replace('|', '\|')
        out.append(f"| `{rel}` | {r['line']} | {desc} |")
    return '\n'.join(out)


def format_snippet(snip: str) -> str:
    if not snip:
        return '_No snippet captured._'
    return '```\n' + snip + '\n```'


def body_template(category: str, severity: str, file: str, line: int, headline: str, count: int, rows, recommendation: str, snippet: str = '', author: str = 'unknown'):
    uniq_files = len({r['file'] for r in rows})
    label_category = category.split('/')[0]
    lines = [
        f'## [tech-debt] {category}',
        '',
        '| Field | Value |',
        '|-------|-------|',
        f'| **File** | `{file}` |',
        f'| **Line** | {line} |',
        f'| **Severity** | {severity} |',
        f'| **Detected** | {SCAN_TS} |',
        f'| **Author** | {author} |',
        '',
        '### Context',
        '',
        headline,
        '',
        f'This batch covers **{count} findings across {uniq_files} files**.',
        '',
        '### Samples',
        '',
        format_table(rows[:12]),
        '',
    ]
    if snippet:
        lines += ['### Representative Snippet', '', format_snippet(snippet), '']
    lines += [
        '### Recommendation',
        '',
        recommendation,
        '',
        '### Labels',
        '',
        f'`tech-debt`, `category:{label_category}`, `severity:{severity}`',
    ]
    return '\n'.join(lines) + '\n'


def issue_spec_from_batch(category: str, severity: str, rows, recommendation: str, headline: str):
    first = rows[0]
    title = f"[tech-debt] {category}: {Path(first['file']).relative_to(ROOT)}:{first['line']} — {headline}"
    body = body_template(category, severity, first['file'], first['line'], headline, len(rows), rows, recommendation, first.get('snippet', ''), first.get('author', 'unknown'))
    label_category = category.split('/')[0]
    return IssueSpec(title, category, severity, first['file'], first['line'], body, ['tech-debt', f'category:{label_category}', f'severity:{severity}'])


def issue_spec_individual(row, recommendation: str):
    category = row['category']
    severity = row['severity']
    title = f"[tech-debt] {category}: {Path(row['file']).relative_to(ROOT)}:{row['line']} — {row['desc']}"
    body = body_template(category, severity, row['file'], row['line'], row['desc'], 1, [row], recommendation, row.get('snippet', ''), row.get('author', 'unknown'))
    label_category = category.split('/')[0]
    return IssueSpec(title, category, severity, row['file'], row['line'], body, ['tech-debt', f'category:{label_category}', f'severity:{severity}'])


def create_issue(spec: IssueSpec):
    body_path = ROOT / '.scratch' / (spec.title.replace('/', '_').replace(':', '_').replace(' ', '_')[:160] + '.md')
    body_path.write_text(spec.body, encoding='utf-8')
    if issue_exists(spec.title):
        return {'title': spec.title, 'skipped': True, 'reason': 'duplicate'}
    args = ['issue', 'create', '--repo', REPO, '--title', spec.title, '--body-file', str(body_path), '--milestone', MILESTONE]
    for label in spec.labels:
        args.extend(['--label', label])
    proc = gh(*args, check=True)
    out = proc.stdout.strip()
    url = out.splitlines()[-1] if out else ''
    return {'title': spec.title, 'skipped': False, 'url': url}


def main():
    findings = load_findings()
    groups = defaultdict(list)
    for f in findings:
        groups[f['category']].append(f)
    specs = []

    # High-severity individual findings first.
    for row in groups.get('dead-code/unreachable', []):
        specs.append(issue_spec_individual(row, 'Remove the unreachable statement or move it into the intended control-flow branch.'))

    # Batch the noisy categories.
    if groups.get('dead-code/unused-import'):
        rows = sorted(groups['dead-code/unused-import'], key=lambda r: (r['file'], r['line']))
        specs.append(issue_spec_from_batch(
            'dead-code/unused-import',
            'medium',
            rows,
            'Delete the unused imports or convert them to local imports only where they are intentionally side-effectful.',
            f"{len(rows)} unused imports across {len({r['file'] for r in rows})} files",
        ))
    if groups.get('duplication/function'):
        rows = sorted(groups['duplication/function'], key=lambda r: (r['file'], r['line']))
        specs.append(issue_spec_from_batch(
            'duplication/function',
            'medium',
            rows,
            'Consolidate the repeated function bodies into a shared helper or generated template; if the duplication is intentional, add a comment explaining the divergence.',
            f"{len(rows)} duplicate function fingerprints across {len({r['file'] for r in rows})} files",
        ))
    for cat, sev, recommendation in [
        ('deprecated/run_until_complete', 'medium', 'Replace `loop.run_until_complete(...)` with `asyncio.run(...)` or an explicit async entrypoint.'),
        ('deprecated/utcnow', 'high', 'Replace `datetime.utcnow()` with `datetime.now(timezone.utc)` and update any dependent formatting/tests.'),
        ('deprecated/warn', 'medium', 'Replace `logging.warn()` with `logging.warning()` and keep the callsites on the supported API.'),
    ]:
        if groups.get(cat):
            rows = sorted(groups[cat], key=lambda r: (r['file'], r['line']))
            headline = f"{len(rows)} callsites across {len({r['file'] for r in rows})} files"
            specs.append(issue_spec_from_batch(cat, sev, rows, recommendation, headline))

    filed = []
    for spec in specs:
        result = create_issue(spec)
        filed.append(result)
        print(json.dumps(result))
    FILED_JSON.write_text(json.dumps(filed, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
