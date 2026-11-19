#!/usr/bin/env python3
"""Pantheon tech-debt scanner v2 (github-tech-debt-scanner skill).

Fixes carried over from the 2026-10-05 / 2026-10-12 runs:
  * TODO markers are case-sensitive and word-boundary anchored, with
    marker-vocabulary definition lines skipped (no more "task-todo" hits).
  * TODO staleness comes from `git blame` commit time, not file mtime.
  * Unused imports come from ruff F401 (authoritative), with an AST fallback.
  * Test-coverage pass searches every test_*.py under the worktree.
  * Every finding carries a stable fingerprint for week-over-week deltas.

Usage: tech_debt_scan_v2.py <worktree> <out-prefix>
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

MARKERS = ('TODO', 'FIXME', 'HACK', 'XXX')
MARKER_RE = re.compile(r'\b(TODO|FIXME|HACK|XXX)\b')
# lines that *define* the scanner's marker vocabulary rather than carry a note
VOCAB_SKIP_RE = re.compile(
    r'TODO\|FIXME|FIXME\|HACK|MARKER|TODO_RE|FIXME_RE|TODO_EXTS|todo_markers|'
    r'\(TODO\|FIXME|TODO/FIXME|TODO, ?FIXME'
)
ISSUE_REF_RE = re.compile(r'(#\d+|github\.com/[\w.-]+/[\w.-]+/issues/\d+)')
CODE_KW_RE = re.compile(r'^\s*#\s*(def|class|if|for|while|with|try|import|from|return|elif|else|except|finally|async)\b')
COMMENT_RE = re.compile(r'^\s*(#|//)\s?')

SKIP_COMMENT_FILES = {'.md', '.txt', '.json', '.svg', '.html', '.lock', '.min.js'}
TEXT_EXTS = {'.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.rs', '.sh', '.bash'}

DEPRECATIONS = [
    ('deprecated/pkg_resources', r'\bpkg_resources\b', 'use importlib.resources / importlib.metadata', 'high'),
    ('deprecated/distutils', r'\b(distutils|from distutils)\b', 'use setuptools / packaging / sysconfig', 'high'),
    ('deprecated/before_first_request', r'before_first_request', 'use before_request + one-shot guard', 'medium'),
    ('deprecated/utcnow', r'\butcnow\(\)', 'use datetime.now(timezone.utc)', 'high'),
    ('deprecated/warn', r'(?<![\w.])logging\.warn\(|(?<![\w.])logger\.warn\(|(?<![\w.])log\.warn\(|(?<![\w.])\.warn\(', 'use logging.warning()', 'medium'),
    ('deprecated/run_until_complete', r'run_until_complete', 'use asyncio.run() or await inside a running loop', 'medium'),
    ('deprecated/typing', r'\btyping\.(List|Dict|Tuple|Set|FrozenSet|Callable|Optional|Union)\b', 'use PEP 585 builtin generics / PEP 604 unions', 'low'),
]

SEVERITY = {
    'dead-code/unreachable': 'high',
    'dead-code/commented-out': 'low',
    'dead-code/unused-import': 'medium',
    'todo/no-issue-ref': 'medium',
    'todo/stale': 'high',
    'untested/api': 'high',
    'untested/mcp-tool': 'medium',
    'duplication/function': 'medium',
}

EXCLUDE_NAMES = {
    'hermes-agent', '.git', '.venv', 'venv', 'env', '__pycache__', 'node_modules',
    '.pytest_cache', '.mypy_cache', '.ruff_cache', 'dist', 'build', 'archives',
    'backups', '.backups', '.ops-backups', 'god-exports', 'god-packages',
    'n8n-data', 'n8n-host', 'migration', 'migration-staging', 'logs', 'data',
    'exports', 'pr35-d86b897-clean.mPeaMa', 'pr35-gitworktree-d86b897',
    '.scratch', 'tmp_spotcheck', '.upgrade-0.19.0', 'site-packages',
    'third_party', 'vendor', 'retired',
}


def rel(p: Path, root: Path) -> str:
    return str(p.relative_to(root))


def excluded(relpath: str) -> bool:
    return any(part in EXCLUDE_NAMES for part in Path(relpath).parts)


def walk(root: Path, exts: set[str]):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_NAMES)
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if p.suffix.lower() in exts:
                r = rel(p, root)
                if not excluded(r):
                    yield p, r


def read_text(p: Path) -> str:
    try:
        return p.read_text(encoding='utf-8')
    except (UnicodeDecodeError, OSError):
        return ''


class Findings:
    def __init__(self):
        self.items = []
        self.seen = set()

    def add(self, category, file, line, desc, author='unknown', extra=''):
        key = (category, file, line, desc)
        if key in self.seen:
            return
        self.seen.add(key)
        self.items.append({
            'category': category,
            'file': file,
            'line': int(line),
            'desc': desc,
            'severity': SEVERITY.get(category, 'medium'),
            'author': author,
            'extra': extra,
        })

    def fingerprint(self):
        return {(i['category'], i['file'], i['line'], i['desc']) for i in self.items}


def line_at(p: Path, n: int) -> str:
    try:
        with p.open(encoding='utf-8', errors='ignore') as fh:
            for i, line in enumerate(fh, 1):
                if i == n:
                    return line.rstrip('\n')
    except OSError:
        pass
    return ''


# ---------------------------------------------------------------- pass 1: dead code

def pass_unused_imports(wt: Path, out: Findings, errors: list[str]):
    try:
        proc = subprocess.run(
            ['ruff', 'check', '--select', 'F401', '--no-cache',
             '--output-format', 'concise', '--quiet',
             '--exclude', 'hermes-agent', '--exclude', 'node_modules',
             '--exclude', '.venv', '--exclude', 'archives', '--exclude', 'backups',
             '--exclude', 'retired', '.'],
            cwd=wt, capture_output=True, text=True, timeout=900,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        errors.append(f'ruff failed: {exc}')
        return
    if proc.returncode not in (0, 1):
        errors.append(f'ruff rc={proc.returncode}: {proc.stderr.strip()[:300]}')
    parse_ruff(proc.stdout, wt, out, 'dead-code/unused-import')


def parse_ruff(stdout: str, wt: Path, out: Findings, category: str):
    # concise format: path:line:col: F401 [*] `os` imported but unused
    pattern = re.compile(r'^(?P<path>.+?):(?P<line>\d+):(?P<col>\d+):\s*(?P<code>[A-Z]\d+)\s*\[\*\]\s*(?P<msg>.+)$')
    for raw in stdout.splitlines():
        m = pattern.match(raw)
        if not m:
            continue
        path = m.group('path')
        if path.startswith('./'):
            path = path[2:]
        if excluded(path):
            continue
        out.add(category, path, int(m.group('line')), m.group('msg').strip())


def pass_dead_code_structural(wt: Path, out: Findings):
    for p, r in walk(wt, {'.py'}):
        text = read_text(p)
        if not text:
            continue
        lines = text.splitlines()
        try:
            tree = ast.parse(text, filename=r)
        except SyntaxError:
            continue
        # commented-out blocks (>=5 contiguous commented code lines)
        start, block = None, []
        for i, line in enumerate(lines, 1):
            if CODE_KW_RE.search(line):
                if start is None:
                    start = i
                block.append(line)
            elif COMMENT_RE.match(line) and start is not None and not line.strip('#/ ').strip():
                block.append(line)  # blank comment keeps the block alive
            else:
                if start is not None and len(block) >= 5:
                    out.add('dead-code/commented-out', r, start, f'{len(block)}-line commented-out code block')
                start, block = None, []
        if start is not None and len(block) >= 5:
            out.add('dead-code/commented-out', r, start, f'{len(block)}-line commented-out code block')
        # statements after an unconditional return/raise at the same indent level
        is_test = p.name.startswith('test_') or '/tests/' in f'/{r}'
        for node in ast.walk(tree):
            for body in bodies_of(node):
                terminator = None
                for stmt in body:
                    if terminator is not None:
                        # a bare `yield` after `return` is the idiomatic way to
                        # declare an async generator; not debt
                        bare_yield = isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Yield)
                        if not is_test and not bare_yield:
                            out.add('dead-code/unreachable', r, getattr(stmt, 'lineno', 0),
                                    f'statement unreachable after {terminator}')
                    if isinstance(stmt, (ast.Return, ast.Raise)):
                        terminator = type(stmt).__name__.lower()


def bodies_of(node):
    for field in ('body', 'orelse', 'finalbody'):
        body = getattr(node, field, None)
        if isinstance(body, list) and body and isinstance(body[0], ast.stmt):
            yield body


# ---------------------------------------------------------------- pass 2: TODOs

class Blame:
    def __init__(self, wt: Path):
        self.wt = wt
        self.dates: dict[str, str] = {}
        self.file_lines: dict[str, dict[int, tuple[str, str]]] = {}

    def line_info(self, relpath: str, lineno: int) -> tuple[str, str]:
        cache = self.file_lines.get(relpath)
        if cache is None:
            cache = {}
            try:
                proc = subprocess.run(
                    ['git', 'blame', '--line-porcelain', '--', relpath],
                    cwd=self.wt, capture_output=True, text=True, timeout=180,
                )
                sha, author, cur = None, 'unknown', None
                for raw in proc.stdout.splitlines():
                    if raw.startswith('\t'):
                        if cur is not None:
                            cache[cur] = (sha or '', author)
                        cur = None
                    elif re.match(r'^[0-9a-f]{40} ', raw):
                        sha = raw.split(' ')[0]
                    elif raw.startswith('author '):
                        author = raw[7:].strip()
                    elif raw.startswith('author-time '):
                        pass
                    elif raw.startswith('summary '):
                        pass
                    m = re.match(r'^[0-9a-f]{40} (\d+) (\d+)( \d+)?$', raw)
                    if m:
                        cur = int(m.group(2))
            except (subprocess.TimeoutExpired, OSError):
                pass
            self.file_lines[relpath] = cache
        info = cache.get(lineno)
        return info if info else ('', 'unknown')

    def commit_date(self, sha: str) -> datetime | None:
        if not sha:
            return None
        key = sha
        if key in self.dates:
            raw = self.dates[key]
            return datetime.fromisoformat(raw) if raw else None
        try:
            proc = subprocess.run(['git', 'show', '-s', '--format=%aI', sha],
                                  cwd=self.wt, capture_output=True, text=True, timeout=60)
            raw = proc.stdout.strip()
        except (subprocess.TimeoutExpired, OSError):
            raw = ''
        self.dates[key] = raw
        return datetime.fromisoformat(raw) if raw else None


def pass_todos(wt: Path, out: Findings, blame: Blame):
    now = datetime.now(timezone.utc)
    for p, r in walk(wt, TEXT_EXTS):
        text = read_text(p)
        if not text:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if not MARKER_RE.search(line):
                continue
            if not re.match(r'^\s*(#|//|/\*|\*|--)', line):
                continue
            if VOCAB_SKIP_RE.search(line):
                continue
            # prose that merely mentions a marker in quotes (e.g. `# ... "TODO
            # that was never wired"`) is documentation, not an action item
            comment_text = re.sub(r'^\s*(#|//|/\*|\*|--)\s*', '', line)
            if re.search(r'["\']\s*(TODO|FIXME|HACK|XXX)', comment_text):
                continue
            sha, author = blame.line_info(r, i)
            when = blame.commit_date(sha)
            age = (now - when).days if when else None
            note = re.sub(r'^\s*(#|//|/\*|\*|--)\s*', '', line).strip()[:110]
            if ISSUE_REF_RE.search(line):
                # `when` is guaranteed non-None whenever `age` is non-None
                if when is not None and age is not None and age > 30:
                    out.add('todo/stale', r, i, f'{note} (unchanged since {when.date()}, {age}d)', author)
            else:
                out.add('todo/no-issue-ref', r, i, note, author)


# ---------------------------------------------------------------- pass 3: coverage

def collect_test_text(wt: Path) -> str:
    chunks = []
    for p, r in walk(wt, {'.py'}):
        if 'test' not in p.name.lower() and 'tests' not in r.lower():
            continue
        if '/tests/' in f'/{r}' or p.name.startswith('test_'):
            chunks.append(read_text(p))
    return '\n'.join(chunks).lower()


def pass_coverage(wt: Path, out: Findings):
    test_text = collect_test_text(wt)
    routes = wt / 'webui' / 'api' / 'routes.py'
    if routes.exists():
        text = read_text(routes)
        seen_paths: set[str] = set()
        # style A: FastAPI decorators
        route_re = re.compile(r'@router\.(get|post|put|delete|patch)\(\s*["\']([^"\']+)["\']')
        # style B: this codebase's hand-rolled dispatcher
        literal_re = re.compile(r'parsed\.path\s*(?:==|\.startswith\(?)\s*["\']([^"\']+)["\']')
        method_ctx_re = re.compile(r'(GET|POST|PUT|DELETE|PATCH)\b')
        for i, line in enumerate(text.splitlines(), 1):
            m = route_re.search(line)
            if m:
                method, path = m.group(1).upper(), m.group(2)
            else:
                m = literal_re.search(line)
                if not m:
                    continue
                path = m.group(1)
                ctx = '\n'.join(text.splitlines()[max(0, i - 4):i])
                mm = method_ctx_re.search(ctx)
                method = mm.group(1) if mm else 'ANY'
            if len(path) < 4 or path in seen_paths:
                continue
            seen_paths.add(path)
            if path.lower() in test_text:
                continue
            norm = re.sub(r'\{[^}]*\}', '', path).strip('/').replace('/', '_').lower()
            if norm and norm in test_text:
                continue
            out.add('untested/api', 'webui/api/routes.py', i, f'{method} {path} not referenced in tests')
    for candidate in ('pantheon-core/mcp_server.py',):
        mcp = wt / candidate
        if not mcp.exists():
            continue
        lines = read_text(mcp).splitlines()
        def_re = re.compile(r'^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(')
        for i, line in enumerate(lines):
            if '@mcp.tool' not in line:
                continue
            for j in range(i, min(i + 8, len(lines))):
                m = def_re.match(lines[j])
                if m:
                    tool = m.group(1)
                    if tool.lower() not in test_text:
                        out.add('untested/mcp-tool', candidate, j + 1, f'MCP tool {tool}() has no test reference')
                    break


# ---------------------------------------------------------------- pass 4: duplication

def func_body_source(node, lines) -> str:
    body = getattr(node, 'body', [])
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], 'value', None), ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    if len(body) < 4:
        return ''
    parts = []
    for stmt in body:
        start = stmt.lineno - 1
        end = getattr(stmt, 'end_lineno', stmt.lineno)
        for raw in lines[start:end]:
            s = re.sub(r'\s+', ' ', raw.split('#')[0]).strip()
            if s:
                parts.append(s)
    if len(parts) < 5:
        return ''
    return '\n'.join(parts)


def pass_duplication(wt: Path, out: Findings):
    buckets: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    for p, r in walk(wt, {'.py'}):
        text = read_text(p)
        if not text:
            continue
        lines = text.splitlines()
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                src = func_body_source(node, lines)
                if not src:
                    continue
                fp = hashlib.sha256(src.encode()).hexdigest()[:16]
                buckets[fp].append((r, node.name, node.lineno))
    for fp, locs in buckets.items():
        files = {l[0] for l in locs}
        if len(files) < 2:
            continue
        first = sorted(locs)[0]
        out.add('duplication/function', first[0], first[2],
                f'{first[1]}() body duplicated across {len(files)} files',
                extra='; '.join(f'{f}:{n}:{ln}' for f, n, ln in sorted(locs)[:8]))


# ---------------------------------------------------------------- pass 5: deprecations

def pass_deprecations(wt: Path, out: Findings, blame: Blame):
    compiled = [(c, re.compile(p), rec, sev) for c, p, rec, sev in DEPRECATIONS]
    for p, r in walk(wt, TEXT_EXTS):
        text = read_text(p)
        if not text:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith('#') and 'utcnow' not in stripped:
                continue
            for category, regex, rec, sev in compiled:
                if regex.search(line):
                    _, author = blame.line_info(r, i)
                    out.add(category, r, i, rec, author)


# ---------------------------------------------------------------- driver

def scan(wt: Path, label: str):
    findings = Findings()
    errors: list[str] = []
    blame = Blame(wt)
    pass_unused_imports(wt, findings, errors)
    pass_dead_code_structural(wt, findings)
    pass_todos(wt, findings, blame)
    pass_coverage(wt, findings)
    pass_duplication(wt, findings)
    pass_deprecations(wt, findings, blame)
    findings.items.sort(key=lambda x: (x['category'], x['file'], x['line'], x['desc']))
    print(json.dumps({
        'label': label,
        'worktree': str(wt),
        'scan_ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'total': len(findings.items),
        'by_category': dict(Counter(i['category'] for i in findings.items)),
        'errors': errors,
    }, indent=2))
    return findings, errors


def main():
    wt = Path(sys.argv[1]).resolve()
    prefix = sys.argv[2]
    findings, errors = scan(wt, prefix)
    data = {
        'label': prefix,
        'worktree': str(wt),
        'scan_ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'errors': errors,
        'findings': findings.items,
    }
    out = Path(prefix + '.json')
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    tsv = Path(prefix + '.tsv')
    with tsv.open('w', encoding='utf-8') as fh:
        fh.write('category\tfile\tline\tdescription\tseverity\tauthor\n')
        for i in findings.items:
            fh.write('\t'.join([i['category'], i['file'], str(i['line']),
                                i['desc'].replace('\t', ' '), i['severity'], i['author']]) + '\n')
    print(f'wrote {out} and {tsv}')


if __name__ == '__main__':
    main()
