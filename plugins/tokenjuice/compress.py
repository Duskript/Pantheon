"""TokenJuice — 10 deterministic compression rules for tool outputs.

Each rule is a pure function: text in → text out. No LLM calls, no network,
no state. Rules are applied in order; each subsequent rule sees the output
of the previous one.

Rules:
  1. ANSI escape stripping  — remove terminal color/control codes
  2. Base64/data URL truncation — replace with [base64: N chars]
  3. HTML → plain text       — strip HTML tags
  4. Whitespace collapse     — collapse 3+ blank lines → 1, trim trailing spaces
  5. Repeated line removal   — squash 3+ identical consecutive lines → 1 + marker
  6. Log noise reduction     — strip ISO8601 timestamps + log levels from common formats
  7. URL shortening          — truncate URLs > 80 chars to domain + "/…"
  8. JSON array truncation   — cap arrays at 10 items with "[+N more]"
  9. CSV/table compression   — if > 20 rows, keep header + first 5 + last 5 + "[+N rows]"
  10. Total output cap       — if result still > max_chars, truncate with context

Config (from config.yaml plugins.tokenjuice section):
  - max_output_chars: int (default 8000) — hard cap on total result size
  - enabled_rules: list[str] | None — subset of rules to apply; None = all
"""

from __future__ import annotations

import re
import logging

logger = logging.getLogger("tokenjuice_plugin")

# ── Defaults ────────────────────────────────────────────────────────────────

DEFAULT_MAX_OUTPUT_CHARS = 8000
DEFAULT_MAX_ARRAY_ITEMS = 10
DEFAULT_MAX_TABLE_ROWS = 20
DEFAULT_URL_MAX_LEN = 80

# ── Rule registry ───────────────────────────────────────────────────────────

_RULES: list[tuple[str, callable]] = []  # (name, fn)


def _rule(name: str):
    """Decorator to register a compression rule."""
    def decorator(fn):
        _RULES.append((name, fn))
        return fn
    return decorator


# ══════════════════════════════════════════════════════════════════════════════
# Rule 1: ANSI Escape Stripping
# ══════════════════════════════════════════════════════════════════════════════

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\][0-9;]*[^\x07]*\x07|\x1b\(B')


@_rule("ansi_strip")
def _rule_ansi_strip(text: str) -> str:
    """Remove ANSI escape sequences (terminal colors, cursor movement, etc.)."""
    before = len(text)
    text = _ANSI_RE.sub('', text)
    after = len(text)
    if before != after:
        logger.debug("TokenJuice [ansi_strip]: %d → %d chars (-%d)", before, after, before - after)
    return text


# ══════════════════════════════════════════════════════════════════════════════
# Rule 2: Base64 / Data URL Truncation
# ══════════════════════════════════════════════════════════════════════════════

_BASE64_DATA_RE = re.compile(
    r'(data:[^;"]*;base64,)[A-Za-z0-9+/=]{200,}',
    re.IGNORECASE,
)
_BASE64_STANDALONE_RE = re.compile(
    r'(?:^|\n)([A-Za-z0-9+/=]{200,})(?:\n|$)',
)


@_rule("base64_truncate")
def _rule_base64_truncate(text: str) -> str:
    """Replace long base64 strings and data URLs with placeholders."""
    count = 0

    def _replace_data(m):
        nonlocal count
        count += 1
        prefix = m.group(1)
        payload = m.group(0)[len(prefix):]
        return f'{prefix}[base64: {len(payload)} chars]'

    def _replace_standalone(m):
        nonlocal count
        count += 1
        payload = m.group(1)
        return f'[base64: {len(payload)} chars]'

    text = _BASE64_DATA_RE.sub(_replace_data, text)
    text = _BASE64_STANDALONE_RE.sub(_replace_standalone, text)

    if count:
        logger.debug("TokenJuice [base64_truncate]: %d base64 blob(s) truncated", count)
    return text


# ══════════════════════════════════════════════════════════════════════════════
# Rule 3: HTML → Plain Text
# ══════════════════════════════════════════════════════════════════════════════

_HTML_TAG_RE = re.compile(r'<[^>]+>')
_HTML_ENTITY_RE = re.compile(r'&[a-z]+;|&#\d+;')
_HTML_WHITESPACE_RE = re.compile(r'\n\s*\n\s*\n+')


@_rule("html_strip")
def _rule_html_strip(text: str) -> str:
    """Strip HTML tags and entities, compressing to plain text."""
    # Only process if it looks like HTML (> 5 tags)
    tag_count = len(_HTML_TAG_RE.findall(text))
    if tag_count < 5:
        return text

    text = _HTML_TAG_RE.sub(' ', text)
    text = _HTML_ENTITY_RE.sub(' ', text)
    text = _HTML_WHITESPACE_RE.sub('\n\n', text)
    text = text.strip()

    logger.debug("TokenJuice [html_strip]: %d tags removed", tag_count)
    return text


# ══════════════════════════════════════════════════════════════════════════════
# Rule 4: Whitespace Collapse
# ══════════════════════════════════════════════════════════════════════════════

_MULTI_BLANK_RE = re.compile(r'\n{3,}')
_TRAILING_SPACE_RE = re.compile(r'[ \t]+$', re.MULTILINE)


@_rule("whitespace_collapse")
def _rule_whitespace_collapse(text: str) -> str:
    """Collapse 3+ consecutive blank lines to 1, strip trailing whitespace."""
    before = len(text)
    text = _MULTI_BLANK_RE.sub('\n\n', text)
    text = _TRAILING_SPACE_RE.sub('', text)
    after = len(text)
    if before != after:
        logger.debug("TokenJuice [whitespace_collapse]: %d → %d chars (-%d)", before, after, before - after)
    return text


# ══════════════════════════════════════════════════════════════════════════════
# Rule 5: Repeated Line Removal
# ══════════════════════════════════════════════════════════════════════════════


@_rule("dedup_lines")
def _rule_dedup_lines(text: str) -> str:
    """Remove 3+ identical consecutive lines, replacing with one + marker."""
    lines = text.split('\n')
    result = []
    i = 0
    removed = 0
    while i < len(lines):
        line = lines[i]
        # Count consecutive identical lines
        j = i + 1
        while j < len(lines) and lines[j] == line and line.strip():
            j += 1
        run = j - i
        if run >= 3:
            result.append(line)
            result.append(f'  [×{run - 1}]')
            removed += run - 2
            i = j
        else:
            result.extend(lines[i:j])
            i = j

    if removed:
        logger.debug("TokenJuice [dedup_lines]: %d duplicate lines removed", removed)
    return '\n'.join(result)


# ══════════════════════════════════════════════════════════════════════════════
# Rule 6: Log Noise Reduction
# ══════════════════════════════════════════════════════════════════════════════

# Common log patterns: ISO8601 timestamps + log levels
_LOG_PREFIX_RE = re.compile(
    r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\s+(?:DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|TRACE|FATAL)\s+',
    re.MULTILINE,
)
# Python traceback lines
_TRACEBACK_RE = re.compile(
    r'^Traceback \(most recent call last\):\n(?:  File ".+?", line \d+, in .+\n    .+\n)+(?:\w+(?:Error|Exception|Warning).*$)',
    re.MULTILINE,
)
# Stack frame lines
_FRAME_LINE_RE = re.compile(r'^  File ".+?", line \d+, in .+$', re.MULTILINE)


@_rule("log_noise")
def _rule_log_noise(text: str) -> str:
    """Strip log timestamps/levels, compress tracebacks to summary."""
    count = 0

    # Detect if this looks like log output (> 5 timestamped lines)
    log_lines = len(_LOG_PREFIX_RE.findall(text))
    if log_lines > 5:
        text = _LOG_PREFIX_RE.sub('', text)
        count += log_lines
        logger.debug("TokenJuice [log_noise]: %d log prefixes stripped", log_lines)

    # Compress tracebacks to single-line summaries
    tb_count = len(_TRACEBACK_RE.findall(text))
    if tb_count > 0:

        def _summarize_tb(m):
            lines = m.group(0).split('\n')
            error_line = lines[-1] if lines else ''
            frame_count = len([l for l in lines if _FRAME_LINE_RE.match(l)])
            return f'[Traceback: {frame_count} frames → {error_line}]'

        text = _TRACEBACK_RE.sub(_summarize_tb, text)
        count += tb_count
        logger.debug("TokenJuice [log_noise]: %d traceback(s) compressed", tb_count)

    return text


# ══════════════════════════════════════════════════════════════════════════════
# Rule 7: URL Shortening
# ══════════════════════════════════════════════════════════════════════════════

_URL_RE = re.compile(r'https?://[^\s<>"\')\]}]{' + str(DEFAULT_URL_MAX_LEN) + r',}')


@_rule("url_shorten")
def _rule_url_shorten(text: str) -> str:
    """Truncate long URLs to domain + path prefix."""
    count = 0

    def _shorten(m):
        nonlocal count
        count += 1
        url = m.group(0)
        # Extract domain + first path segment
        parts = url.split('/')
        if len(parts) >= 3:
            domain = parts[2]
            path = '/'.join(parts[3:4]) if len(parts) > 3 else ''
            short = f'{parts[0]}//{domain}/{path}…' if path else f'{parts[0]}//{domain}/…'
        else:
            short = url[:60] + '…'
        return short

    text = _URL_RE.sub(_shorten, text)
    if count:
        logger.debug("TokenJuice [url_shorten]: %d URLs shortened", count)
    return text


# ══════════════════════════════════════════════════════════════════════════════
# Rule 8: JSON Array Truncation
# ══════════════════════════════════════════════════════════════════════════════

_JSON_ARRAY_RE = re.compile(r'(\[\s*)((?:\{[^}]*\}|"[^"]*"|[^\[\]])+?)(\s*\])', re.DOTALL)


@_rule("json_truncate")
def _rule_json_truncate(text: str) -> str:
    """Truncate large JSON arrays to first N items."""
    import json
    count = 0

    # Try to find JSON arrays and truncate them
    def _process_json(text_inner):
        nonlocal count
        # Find balanced JSON arrays
        results = []
        depth = 0
        start = -1
        for i, ch in enumerate(text_inner):
            if ch == '[':
                if depth == 0:
                    start = i
                depth += 1
            elif ch == ']':
                depth -= 1
                if depth == 0 and start >= 0:
                    segment = text_inner[start:i + 1]
                    try:
                        arr = json.loads(segment)
                        if isinstance(arr, list) and len(arr) > DEFAULT_MAX_ARRAY_ITEMS:
                            truncated = json.dumps(
                                arr[:DEFAULT_MAX_ARRAY_ITEMS], indent=None
                            )
                            truncated = truncated[:-1]  # remove closing ]
                            truncated += f', "... [+{len(arr) - DEFAULT_MAX_ARRAY_ITEMS} more items]" ]'
                            results.append((start, i + 1, truncated))
                            count += 1
                    except (json.JSONDecodeError, ValueError):
                        pass

        # Apply replacements from end to start (preserve positions)
        for s, e, replacement in reversed(results):
            text_inner = text_inner[:s] + replacement + text_inner[e:]
        return text_inner, count

    text, c = _process_json(text)
    if c:
        logger.debug("TokenJuice [json_truncate]: %d JSON arrays truncated", c)
    return text


# ══════════════════════════════════════════════════════════════════════════════
# Rule 9: CSV / Table Compression
# ══════════════════════════════════════════════════════════════════════════════

@_rule("table_compress")
def _rule_table_compress(text: str) -> str:
    """Compress large tables (CSV/Markdown/TSV) to header + first 5 + last 5 rows."""
    lines = text.split('\n')
    if len(lines) <= DEFAULT_MAX_TABLE_ROWS:
        return text

    # Detect if this is a table: consistent column count, separator line
    sep_indices = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and all(ch in '|-+=: ' for ch in stripped.replace(' ', '')):
            sep_indices.append(i)

    if not sep_indices:
        return text

    # Use first separator to identify table format
    sep_idx = sep_indices[0]
    if sep_idx == 0:
        return text  # can't determine header

    header_lines = lines[:sep_idx + 1]
    body = lines[sep_idx + 1:]
    if len(body) <= DEFAULT_MAX_TABLE_ROWS:
        return text

    compressed = header_lines + body[:5] + [
        f'  ... [+{len(body) - 10} rows omitted] ...'
    ] + body[-5:]

    logger.debug("TokenJuice [table_compress]: table %d → %d rows", len(lines), len(compressed))
    return '\n'.join(compressed)


# ══════════════════════════════════════════════════════════════════════════════
# Rule 10: Total Output Cap
# ══════════════════════════════════════════════════════════════════════════════


def _rule_output_cap(text: str, max_chars: int = DEFAULT_MAX_OUTPUT_CHARS) -> str:
    """Hard cap on total result size. Preserves beginning and end context."""
    if len(text) <= max_chars:
        return text

    half = (max_chars - 100) // 2
    head = text[:half]
    tail = text[-half:]
    truncated = (
        f'{head}\n\n'
        f'... [... {len(text) - max_chars + 100} chars truncated — '
        f'{len(text)} → {max_chars} total ...]\n\n'
        f'{tail}'
    )
    logger.debug(
        "TokenJuice [output_cap]: %d → %d chars (cap=%d)",
        len(text), len(truncated), max_chars,
    )
    return truncated


# ══════════════════════════════════════════════════════════════════════════════
# Hook handler
# ══════════════════════════════════════════════════════════════════════════════


def _compress_tool_result(
    tool_name: str = '',
    args: dict | None = None,
    result: str = '',
    task_id: str = '',
    session_id: str = '',
    tool_call_id: str = '',
    duration_ms: int = 0,
) -> str | None:
    """Apply all 10 compression rules and the output cap. Returns compressed string or None."""
    if not result or not isinstance(result, str):
        return None

    # Skip very short results — not worth compressing
    if len(result) < 200:
        return None

    before = len(result)

    # Apply each rule in order
    for name, fn in _RULES:
        try:
            prev = len(result)
            result = fn(result)
            if not isinstance(result, str):
                logger.warning("TokenJuice: rule %s returned non-string, skipping", name)
                result = ''  # safety
                return None
        except Exception:
            logger.debug("TokenJuice: rule %s failed, continuing", name, exc_info=True)

    # Rule 10: Output cap
    result = _rule_output_cap(result)

    after = len(result)
    if after < before:
        pct = round((1 - after / before) * 100, 1)
        logger.info(
            "TokenJuice: %s — %d → %d chars (-%d%%, %d ms)",
            tool_name, before, after, pct, duration_ms or 0,
        )
        return result

    return None  # unchanged
