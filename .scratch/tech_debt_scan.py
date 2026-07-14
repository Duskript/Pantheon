from __future__ import annotations

import ast
import json
import os
import re
import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path('/home/konan/pantheon')
REPORTS = ROOT / 'reports'
EXCLUDE_DIRS = {'hermes-agent', '.venv', 'venv', '__pycache__', 'node_modules', '.git', '.pytest_cache', '.scratch', 'scratch', 'dist', '.backups', 'backups', 'archives', 'exports', 'god-exports', 'god-packages', 'reports', 'migration-staging', 'n8n-data', 'n8n-host', 'data', 'logs', 'tmp_spotcheck', 'pr35-d86b897-clean.mPeaMa', 'pr35-gitworktree-d86b897'}
PY_EXTS = {'.py'}
TODO_EXTS = {'.py', '.js', '.ts', '.go', '.rs', '.sh'}
ALL_TEXT_EXTS = TODO_EXTS | {'.md', '.yaml', '.yml', '.toml', '.json', '.txt', '.html', '.svg'}

scan_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
scan_ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


@dataclass
class Finding:
    category: str
    file: str
    line: int
    desc: str
    severity: str
    author: str = 'unknown'
    snippet: str = ''
    extra: str = ''


def is_excluded(path: Path) -> bool:
    return any(part in EXCLUDE_DIRS for part in path.parts)


def iter_files(exts: set[str]) -> Iterable[Path]:
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for name in files:
            p = Path(root) / name
            if p.suffix.lower() in exts and not is_excluded(p):
                yield p


def read_text(p: Path) -> str:
    try:
        return p.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        return p.read_text(encoding='utf-8', errors='ignore')


def line_snippet(lines: list[str], line_no: int, context: int = 1) -> str:
    start = max(1, line_no - context)
    end = min(len(lines), line_no + context)
    return '\n'.join(f'{i+1}:{lines[i]}' for i in range(start - 1, end))


def add_finding(findings: list[Finding], seen: set[tuple], category: str, file: str, line: int, desc: str, severity: str, snippet: str = '', author: str = 'unknown', extra: str = ''):
    key = (category, file, line, desc)
    if key in seen:
        return
    seen.add(key)
    findings.append(Finding(category, file, line, desc, severity, author=author, snippet=snippet, extra=extra))


# --- Dead code: unused imports ---

def collect_imports_and_names(tree: ast.AST):
    imported = {}  # name -> (lineno, desc)
    used = set()

    class V(ast.NodeVisitor):
        def visit_Import(self, node: ast.Import):
            for alias in node.names:
                if alias.name == '__future__':
                    continue
                name = alias.asname or alias.name.split('.')[0]
                imported[name] = (node.lineno, f"import {alias.name}{' as ' + alias.asname if alias.asname else ''}")
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom):
            if node.module == '__future__':
                return
            for alias in node.names:
                if alias.name == '*':
                    continue
                name = alias.asname or alias.name
                imported[name] = (node.lineno, f"from {'.' * node.level + (node.module or '')} import {alias.name}{' as ' + alias.asname if alias.asname else ''}")
            self.generic_visit(node)

        def visit_Name(self, node: ast.Name):
            if isinstance(node.ctx, ast.Load):
                used.add(node.id)
            self.generic_visit(node)

        def visit_Attribute(self, node: ast.Attribute):
            # capture module usage like import os; os.path
            if isinstance(node.value, ast.Name) and isinstance(node.value.ctx, ast.Load):
                used.add(node.value.id)
            self.generic_visit(node)

    V().visit(tree)
    return imported, used


# --- Dead code: unreachable statements in bodies ---
TERMINATORS = (ast.Return, ast.Raise)
try:
    TERMINATORS = TERMINATORS + (ast.Break, ast.Continue)
except Exception:
    pass


def body_children(node: ast.AST):
    for field in ('body', 'orelse', 'finalbody'):
        body = getattr(node, field, None)
        if isinstance(body, list):
            yield field, body


def terminates(stmt: ast.AST) -> bool:
    return isinstance(stmt, (ast.Return, ast.Raise, ast.Break, ast.Continue))


def scan_unreachable_in_body(body: list[ast.stmt], file: str, findings: list[Finding], seen: set[tuple], lines: list[str]):
    terminated = False
    for idx, stmt in enumerate(body):
        if terminated:
            if hasattr(stmt, 'lineno'):
                desc = f'code after {type(body[idx-1]).__name__.lower()}'
                snippet = line_snippet(lines, stmt.lineno)
                add_finding(findings, seen, 'dead-code/unreachable', file, stmt.lineno, desc, 'high', snippet)
            continue
        # recurse first into nested blocks
        for _, child_body in body_children(stmt):
            scan_unreachable_in_body(child_body, file, findings, seen, lines)
        if terminates(stmt):
            terminated = True


def scan_python_file_for_dead_code(p: Path, findings: list[Finding], seen: set[tuple]):
    text = read_text(p)
    lines = text.splitlines()
    try:
        tree = ast.parse(text, filename=str(p))
    except SyntaxError:
        return

    imported, used = collect_imports_and_names(tree)
    for name, (lineno, desc) in imported.items():
        if name not in used:
            snippet = line_snippet(lines, lineno)
            add_finding(findings, seen, 'dead-code/unused-import', str(p), lineno, desc, 'medium', snippet)

    # commented-out code blocks
    block_start = None
    block = []
    kw_re = re.compile(r'^\s*#\s*(def|class|if|for|while|with|try|import|from|return|elif|else|except|finally)\b')
    for i, line in enumerate(lines, start=1):
        if kw_re.search(line):
            if block_start is None:
                block_start = i
            block.append((i, line))
        else:
            if block_start is not None and len(block) >= 5:
                desc = f'{len(block)}-line commented block'
                snippet = '\n'.join(f'{ln}:{txt}' for ln, txt in block[:8])
                add_finding(findings, seen, 'dead-code/commented-out', str(p), block_start, desc, 'low', snippet)
            block_start = None
            block = []
    if block_start is not None and len(block) >= 5:
        desc = f'{len(block)}-line commented block'
        snippet = '\n'.join(f'{ln}:{txt}' for ln, txt in block[:8])
        add_finding(findings, seen, 'dead-code/commented-out', str(p), block_start, desc, 'low', snippet)

    # unreachable code
    scan_unreachable_in_body(tree.body, str(p), findings, seen, lines)


# --- TODO scanner ---
TODO_RE = re.compile(r'\b(TODO|FIXME|HACK|XXX)\b')
ISSUE_REF_RE = re.compile(r'(#\d+|github\.com/.*/issues/\d+)')


def scan_todos(findings: list[Finding], seen: set[tuple]):
    comment_res = {
        '.py': re.compile(r'^\s*#.*(TODO|FIXME|HACK|XXX)'),
        '.sh': re.compile(r'^\s*#.*(TODO|FIXME|HACK|XXX)'),
        '.js': re.compile(r'^\s*//.*(TODO|FIXME|HACK|XXX)'),
        '.ts': re.compile(r'^\s*//.*(TODO|FIXME|HACK|XXX)'),
        '.go': re.compile(r'^\s*//.*(TODO|FIXME|HACK|XXX)'),
        '.rs': re.compile(r'^\s*//.*(TODO|FIXME|HACK|XXX)'),
    }
    for p in iter_files(TODO_EXTS):
        text = read_text(p)
        lines = text.splitlines()
        matcher = comment_res.get(p.suffix.lower())
        if not matcher:
            continue
        for i, line in enumerate(lines, start=1):
            if not matcher.search(line):
                continue
            desc = line.strip().lstrip('#/').strip()
            snippet = line_snippet(lines, i)
            if not ISSUE_REF_RE.search(line):
                add_finding(findings, seen, 'todo/no-issue-ref', str(p), i, desc[:120], 'medium', snippet)
            # stale TODOs cannot be validated without git history; approximate with file mtime if older than 30 days
            try:
                mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
                age_days = (datetime.now(timezone.utc) - mtime).days
                if age_days > 30:
                    add_finding(findings, seen, 'todo/stale', str(p), i, f'{desc[:120]} (file older than {age_days}d)', 'high', snippet, extra='mtime-proxy')
            except Exception:
                pass


# --- Test coverage ---
ROUTES_FILE = ROOT / 'webui' / 'api' / 'routes.py'
MCP_FILE = ROOT / 'pantheon-core' / 'mcp_server.py'
TEST_DIRS = [ROOT / 'tests', ROOT / 'webui' / 'tests', ROOT / 'pantheon-core' / 'tests']


def gather_test_text() -> str:
    chunks = []
    for d in TEST_DIRS:
        if d.exists():
            for p in d.rglob('test*.py'):
                if is_excluded(p):
                    continue
                chunks.append(read_text(p))
    return '\n'.join(chunks)


def scan_test_coverage(findings: list[Finding], seen: set[tuple]):
    test_text = gather_test_text().lower()
    # routes
    if ROUTES_FILE.exists():
        text = read_text(ROUTES_FILE)
        lines = text.splitlines()
        route_re = re.compile(r'@router\.(get|post|put|delete|patch)\(([^)]*)\)')
        for i, line in enumerate(lines, start=1):
            m = route_re.search(line)
            if not m:
                continue
            method = m.group(1).upper()
            path = m.group(2).strip().strip('"\'')
            norm = re.sub(r'[^a-zA-Z0-9]+', '_', path).strip('_').lower()
            if norm not in test_text and path.lower() not in test_text:
                add_finding(findings, seen, 'untested/api', str(ROUTES_FILE), i, f'{method} {path} not referenced in tests', 'high', line_snippet(lines, i))
    # mcp tools
    if MCP_FILE.exists():
        text = read_text(MCP_FILE)
        lines = text.splitlines()
        dec_re = re.compile(r'@mcp\.tool\(\)')
        def_re = re.compile(r'^\s*def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(')
        for i, line in enumerate(lines, start=1):
            if dec_re.search(line):
                # find next def
                for j in range(i, min(i+10, len(lines)) + 1):
                    dm = def_re.search(lines[j-1]) if j-1 < len(lines) else None
                    if dm:
                        tool = dm.group(1)
                        if tool.lower() not in test_text:
                            add_finding(findings, seen, 'untested/mcp-tool', str(MCP_FILE), j, f'{tool}() has no obvious test reference', 'medium', line_snippet(lines, j))
                        break


# --- Duplication detection ---

def normalize_func(node: ast.AST, lines: list[str]) -> str:
    if not hasattr(node, 'lineno') or not hasattr(node, 'end_lineno'):
        return ''
    start = getattr(node, 'lineno', 1) - 1
    end = getattr(node, 'end_lineno', start + 1)
    chunk = lines[start:end]
    if len(chunk) <= 1:
        return ''
    body = chunk[1:]
    stripped = []
    for line in body:
        s = line.strip()
        if not s:
            continue
        stripped.append(s)
    return '\n'.join(stripped)


def scan_duplication(findings: list[Finding], seen: set[tuple]):
    fingerprints: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    for p in iter_files(PY_EXTS):
        text = read_text(p)
        lines = text.splitlines()
        try:
            tree = ast.parse(text, filename=str(p))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if len(getattr(node, 'body', [])) < 4:
                    continue
                body_text = normalize_func(node, lines)
                if len(body_text.splitlines()) < 5:
                    continue
                fp = hashlib.sha256(body_text.encode()).hexdigest()[:16]
                fingerprints[fp].append((str(p), node.name, node.lineno))
    for fp, locs in fingerprints.items():
        files = {f for f, _, _ in locs}
        if len(files) >= 2:
            desc = f'{locs[0][1]}() duplicated across {len(files)} files'
            file, _, line = locs[0]
            add_finding(findings, seen, 'duplication/function', file, line, desc, 'medium', extra='; '.join(f'{f}:{n}:{ln}' for f, n, ln in locs[:10]))


# --- Deprecation detection ---
DEPRECATED_PATTERNS = [
    ('deprecated/pkg_resources', 'pkg_resources', 'use importlib.resources', 'high'),
    ('deprecated/distutils', r'\bdistutils\b', 'use setuptools/packaging', 'high'),
    ('deprecated/run_until_complete', 'run_until_complete', 'use asyncio.run()', 'medium'),
    ('deprecated/before_first_request', 'before_first_request', 'use before_request + flag', 'medium'),
    ('deprecated/utcnow', 'utcnow()', 'use datetime.now(timezone.utc)', 'high'),
    ('deprecated/warn', r'\.warn\(', 'use .warning()', 'medium'),
    ('deprecated/typing', r'\btyping\.(List|Dict|Tuple|Set|Callable|Optional|Union)\b', 'use builtin generics', 'low'),
]


def scan_deprecations(findings: list[Finding], seen: set[tuple]):
    for p in iter_files(TODO_EXTS):
        text = read_text(p)
        lines = text.splitlines()
        for category, pat, rec, sev in DEPRECATED_PATTERNS:
            regex = re.compile(pat)
            for i, line in enumerate(lines, start=1):
                if regex.search(line):
                    add_finding(findings, seen, category, str(p), i, rec, sev, line_snippet(lines, i))


def write_outputs(findings: list[Finding]):
    REPORTS.mkdir(parents=True, exist_ok=True)
    tsv = REPORTS / f'tech-debt-{scan_date}.tsv'
    issues_json = REPORTS / f'tech-debt-{scan_date}-issues.json'
    summary_md = REPORTS / f'tech-debt-{scan_date}-summary.md'
    errors_log = REPORTS / f'tech-debt-{scan_date}-errors.log'
    filed_json = REPORTS / f'tech-debt-{scan_date}-filed.json'

    with tsv.open('w', encoding='utf-8') as f:
        for item in findings:
            f.write('\t'.join([item.category, item.file, str(item.line), item.desc.replace('\t', ' '), item.severity, item.author]) + '\n')
    issues_payload = [asdict(item) for item in findings]
    issues_json.write_text(json.dumps(issues_payload, indent=2, ensure_ascii=False), encoding='utf-8')
    counts = Counter(item.category for item in findings)
    sev_counts = Counter(item.severity for item in findings)
    lines = [
        f'# Tech Debt Scan Summary — {scan_date}',
        '',
        f'- Generated: {scan_ts}',
        f'- Total findings: {len(findings)}',
        f'- Severity counts: {dict(sev_counts)}',
        '',
        '## By category',
    ]
    for cat, count in sorted(counts.items()):
        lines.append(f'- {cat}: {count}')
    summary_md.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    errors_log.write_text('', encoding='utf-8')
    filed_json.write_text('[]\n', encoding='utf-8')
    return tsv, issues_json, summary_md, errors_log, filed_json


def main():
    findings: list[Finding] = []
    seen: set[tuple] = set()
    for p in iter_files(PY_EXTS):
        scan_python_file_for_dead_code(p, findings, seen)
    scan_todos(findings, seen)
    scan_test_coverage(findings, seen)
    scan_duplication(findings, seen)
    scan_deprecations(findings, seen)
    findings.sort(key=lambda x: (x.category, x.file, x.line, x.desc))
    outputs = write_outputs(findings)
    print(json.dumps({
        'scan_date': scan_date,
        'scan_ts': scan_ts,
        'findings': len(findings),
        'outputs': [str(p) for p in outputs],
        'by_category': Counter(item.category for item in findings),
        'by_severity': Counter(item.severity for item in findings),
    }, indent=2, default=int))


if __name__ == '__main__':
    main()
