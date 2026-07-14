"""Ichor Memory Engine — Safety Layer (Secret Redaction).

Pattern-based detection and sanitization of sensitive data
in text and JSON structures, adapted from the OpenHuman pattern.
"""

import re
from typing import Any


# Default patterns for detecting likely secrets.
# Each entry is a dict with 'name' (human-readable label),
# 'pattern' (compiled regex), and optional 'enabled' flag.
DEFAULT_SECRET_PATTERNS: list[dict[str, Any]] = [
    {
        "name": "bearer_token",
        "pattern": re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]{20,}", re.IGNORECASE),
    },
    {
        "name": "api_key_sk",
        "pattern": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    },
    {
        "name": "api_key_pk",
        "pattern": re.compile(r"pk-[A-Za-z0-9_-]{20,}"),
    },
    {
        "name": "private_key_pem",
        "pattern": re.compile(
            r"-----BEGIN\s.*PRIVATE\sKEY-----[\s\S]*?-----END\s.*PRIVATE\sKEY-----"
        ),
    },
    {
        "name": "certificate_pem",
        "pattern": re.compile(
            r"-----BEGIN\sCERTIFICATE-----[\s\S]*?-----END\sCERTIFICATE-----"
        ),
    },
    {
        "name": "aws_access_key",
        "pattern": re.compile(r"AKIA[0-9A-Z]{16}"),
    },
    {
        "name": "aws_secret_key",
        "pattern": re.compile(r"(?i)aws\s*(secret|access)\s*key[=:]\s*\S+"),
    },
    {
        "name": "github_token",
        "pattern": re.compile(r"ghp_[A-Za-z0-9]{36}"),
    },
    {
        "name": "github_old_token",
        "pattern": re.compile(r"gho_[A-Za-z0-9]{36}"),
    },
    {
        "name": "jwt_token",
        "pattern": re.compile(
            r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
        ),
    },
    {
        "name": "slack_token",
        "pattern": re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    },
    {
        "name": "generic_token",
        "pattern": re.compile(r"(?i)(token|secret|password|apikey|api_key)\s*[=:]\s*\S+"),
    },
    {
        "name": "ssh_private_key",
        "pattern": re.compile(r"-----BEGIN\sOPENSSH\sPRIVATE\sKEY-----[\s\S]*?-----END\sOPENSSH\sPRIVATE\sKEY-----"),
    },
]


class SafetyConfig:
    """Holds the configurable list of secret detection patterns.

    Allows adding, removing, or disabling patterns at runtime.
    """

    def __init__(self, patterns: Optional[list[dict[str, Any]]] = None):
        """Initialize with an optional custom pattern list.

        Args:
            patterns: List of pattern dicts. Each must have 'name' (str)
                      and 'pattern' (compiled regex). Defaults to
                      DEFAULT_SECRET_PATTERNS.
        """
        self.patterns = patterns if patterns is not None else DEFAULT_SECRET_PATTERNS

    def add_pattern(self, name: str, regex: str) -> None:
        """Add a new detection pattern.

        Args:
            name: Human-readable label for the pattern.
            regex: A valid regex string to compile.

        Raises:
            re.error: If the regex is invalid.
        """
        self.patterns.append({"name": name, "pattern": re.compile(regex)})

    def remove_pattern(self, name: str) -> bool:
        """Remove a pattern by name.

        Args:
            name: The name of the pattern to remove.

        Returns:
            True if a pattern was removed, False otherwise.
        """
        before = len(self.patterns)
        self.patterns = [p for p in self.patterns if p["name"] != name]
        return len(self.patterns) < before


_GLOBAL_CONFIG = SafetyConfig()


def configure(config: SafetyConfig) -> None:
    """Replace the global safety configuration.

    Args:
        config: A SafetyConfig instance to use globally.
    """
    global _GLOBAL_CONFIG
    _GLOBAL_CONFIG = config


def has_likely_secret(text: str) -> bool:
    """Check if the given text contains patterns matching known secret types.

    Args:
        text: The string to inspect.

    Returns:
        True if any secret pattern matches, False otherwise.
    """
    for entry in _GLOBAL_CONFIG.patterns:
        if entry["pattern"].search(text):
            return True
    return False


def sanitize_text(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Replace detected secrets with [REDACTED] and return a redaction report.

    Args:
        text: The input string that may contain secrets.

    Returns:
        A tuple of (sanitized_text, redaction_report), where the report
        is a list of dicts with 'pattern' (name) and 'count' (matches found).
    """
    report: dict[str, int] = {}
    sanitized = text

    for entry in _GLOBAL_CONFIG.patterns:
        matches = list(entry["pattern"].finditer(sanitized))
        if matches:
            count = len(matches)
            report[entry["name"]] = report.get(entry["name"], 0) + count
            sanitized = entry["pattern"].sub("[REDACTED]", sanitized)

    report_list = [{"pattern": name, "count": cnt} for name, cnt in report.items()]
    return sanitized, report_list


def _sanitize_value(value: Any, path: str, report: list[dict[str, Any]]) -> Any:
    """Recursively sanitize a single value within a JSON structure.

    Args:
        value: The value to check/sanitize.
        path: Current dot-separated path in the JSON tree (for context).
        report: Accumulator list for redaction events.

    Returns:
        The sanitized value (string redacted, or recursively processed).
    """
    if isinstance(value, str):
        sanitized, findings = sanitize_text(value)
        for finding in findings:
            report.append({**finding, "path": path})
        return sanitized
    elif isinstance(value, dict):
        sanitized_dict, nested_report = sanitize_json(value, path_prefix=path)
        report.extend(nested_report)
        return sanitized_dict
    elif isinstance(value, list):
        result: list[Any] = []
        for i, item in enumerate(value):
            item_path = f"{path}[{i}]"
            result.append(_sanitize_value(item, item_path, report))
        return result
    else:
        return value


def sanitize_json(
    data: dict[str, Any], path_prefix: str = "$"
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Deep-walk a JSON-like dict, redacting values that match secret patterns.

    Key names that are known secret indicators (e.g., 'token', 'password',
    'secret', 'api_key') also trigger redaction of their values.

    Args:
        data: The JSON-compatible dictionary to sanitize.
        path_prefix: Root path label for the redaction report. Default '$'.

    Returns:
        A tuple of (sanitized_data, redaction_report), where the report
        lists each redacted value with its path and pattern name.
    """
    report: list[dict[str, Any]] = []
    sanitized: dict[str, Any] = {}
    secret_key_indicators = {"token", "password", "secret", "api_key", "apikey", "private_key"}

    for key, value in data.items():
        current_path = f"{path_prefix}.{key}"

        # If the key name itself indicates a secret, redact the value directly
        if key.lower() in secret_key_indicators and isinstance(value, str):
            sanitized[key] = "[REDACTED]"
            report.append({"pattern": "sensitive_key", "count": 1, "path": current_path})
            continue

        sanitized[key] = _sanitize_value(value, current_path, report)

    return sanitized, report
