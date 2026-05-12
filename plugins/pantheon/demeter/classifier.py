"""Rule engine for Athenaeum ingestion.

Loads the ingest-rules.yaml, matches files against rules, and returns
the target destination + processing instructions.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

# Use REAL home (Hermes overrides Path.home())
_REAL_HOME = os.path.expanduser("~")

# Path to the rules file (overridable via env var so the plugin can point to it)
_DEFAULT_RULES_PATH = os.environ.get(
    "ATHENAEUM_RULES_PATH",
    f"{_REAL_HOME}/.hermes/pantheon/ingest-rules.yaml",
)

# The known Codexes — used by the classifier as valid destinations
KNOWN_CODEXES = [
    "Codex-Forge",
    "Codex-Pantheon",
    "Codex-Infrastructure",
    "Codex-SKC",
    "Codex-Fiction",
    "Codex-Asclepius",
    "Codex-General",
]

# The Athenaeum root
ATHENAEUM_ROOT = Path(f"{_REAL_HOME}/athenaeum")


# ---------------------------------------------------------------------------
# Rule dataclass
# ---------------------------------------------------------------------------


class IngestRule:
    """A single ingestion rule parsed from the YAML."""

    def __init__(self, raw: dict):
        self.name: str = raw.get("name", "Unnamed rule")
        self.description: str = raw.get("description", "")
        self.target_codex: Optional[str] = None
        self.target_subfolder: Optional[str] = None
        self.structure: str = "flat"
        self.metadata: bool = False

        target = raw.get("target", {})
        if target:
            self.target_codex = target.get("codex")
            self.target_subfolder = target.get("subfolder")
            self.target_structure = target.get("structure", "flat")
            self.target_metadata = target.get("metadata", False)

        # Match criteria
        match = raw.get("match", {})
        self.extensions: List[str] = [e.lower() for e in match.get("extensions", [])]
        self.filename_contains: List[str] = [
            kw.lower() for kw in match.get("filename_contains", [])
        ]
        self.companion_of: List[str] = match.get("companion_of", [])

    def matches_extension(self, path: Path) -> bool:
        if not self.extensions:
            return True  # no extension filter = match all
        return path.suffix.lower() in self.extensions

    def matches_filename(self, path: Path) -> bool:
        if not self.filename_contains:
            return True  # no keyword filter = match all
        name_lower = path.stem.lower()
        return any(kw in name_lower for kw in self.filename_contains)

    def matches(self, path: Path) -> bool:
        return self.matches_extension(path) and self.matches_filename(path)

    def __repr__(self) -> str:
        return f"IngestRule({self.name!r} → {self.target_codex}/{self.target_subfolder})"


# ---------------------------------------------------------------------------
# Suggest queue
# ---------------------------------------------------------------------------

_SUGGEST_FILE = Path(f"{_REAL_HOME}/.hermes/pantheon/suggested-codexes.json")


def _load_suggestions() -> List[dict]:
    import json

    if _SUGGEST_FILE.exists():
        try:
            return json.loads(_SUGGEST_FILE.read_text())
        except Exception:
            return []
    return []


def _save_suggestions(suggestions: List[dict]) -> None:
    import json

    _SUGGEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SUGGEST_FILE.write_text(json.dumps(suggestions, indent=2))


def add_suggestion(suggestion: dict) -> None:
    """Add a Codex suggestion to the queue for the 7am report."""
    suggestions = _load_suggestions()
    # Dedup by name
    name = suggestion.get("suggested_codex", "")
    suggestions = [s for s in suggestions if s.get("suggested_codex") != name]
    suggestions.append(suggestion)
    _save_suggestions(suggestions)


def pop_suggestions() -> List[dict]:
    """Get and clear all pending suggestions."""
    suggestions = _load_suggestions()
    _save_suggestions([])
    return suggestions


# ---------------------------------------------------------------------------
# Rule loading
# ---------------------------------------------------------------------------


def load_rules(path: Optional[str] = None) -> List[IngestRule]:
    """Load rules from the YAML file. Returns ordered list of rules."""
    rules_path = Path(path or _DEFAULT_RULES_PATH)
    if not rules_path.exists():
        logger.warning("Rules file not found: %s", rules_path)
        return []

    try:
        raw = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
        if not raw or not isinstance(raw, dict):
            return []
        rule_dicts = raw.get("rules", [])
        return [IngestRule(r) for r in rule_dicts]
    except Exception as exc:
        logger.warning("Failed to load rules: %s", exc)
        return []


def match_rule(path: Path, rules: Optional[List[IngestRule]] = None) -> Optional[IngestRule]:
    """Find the first rule that matches *path*. Returns None if no match."""
    if rules is None:
        rules = load_rules()

    for rule in rules:
        if rule.matches(path):
            return rule
    return None


# ---------------------------------------------------------------------------
# Target path builder
# ---------------------------------------------------------------------------


def build_target_path(
    rule: IngestRule,
    filename: str,
    *,
    song_name: str = "",
    artist: str = "",
    album: str = "",
) -> Path:
    """Build the destination path within the Athenaeum for a matched file.

    Args:
        rule: The matched rule.
        filename: Original filename (or new name for the file).
        song_name: Used for 'grouped' structure.
        artist: Used for 'id3_artist' structure.
        album: Used for 'id3_artist' structure.

    Returns:
        Path relative to Athenaeum root (e.g. Codex-SKC/audio/MySong--2026-04-29/).
    """
    from datetime import date

    codex = rule.target_codex or "Codex-General"
    subfolder = rule.target_subfolder or ""
    structure = getattr(rule, "target_structure", "flat")

    # Base: Codex-SKC/audio/ or Codex-General/images/
    parts = [codex]
    if subfolder:
        parts.append(subfolder)

    if structure == "grouped":
        # Codex-SKC/audio/SongName--YYYY-MM-DD/
        today = date.today().isoformat()
        group_name = f"{song_name or Path(filename).stem}--{today}"
        parts.append(group_name)
    elif structure == "id3_artist":
        # Codex-General/audio/ArtistName/AlbumName/
        artist_dir = artist or "Unknown Artist"
        album_dir = album or "Unknown Album"
        parts.extend([artist_dir, album_dir])
    # else 'flat' — file goes directly into the subfolder

    return ATHENAEUM_ROOT.joinpath(*parts)


def build_metadata_content(
    rule: IngestRule,
    path: Path,
    *,
    song_name: str = "",
    artist: str = "",
    album: str = "",
    genre: str = "",
    year: str = "",
    style_prompt: str = "",
    lyrics_file: str = "",
) -> str:
    """Build metadata .md content for a filed asset."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    lines = [
        f"---",
        f"name: {song_name or path.stem}",
        f"source: {path.name}",
        f"ingested_at: {now.isoformat()}",
        f"rule: {rule.name}",
    ]
    if artist:
        lines.append(f"artist: {artist}")
    if album:
        lines.append(f"album: {album}")
    if genre:
        lines.append(f"genre: {genre}")
    if year:
        lines.append(f"year: {year}")
    if style_prompt:
        lines.append(f"style_prompt: |")
        for line in style_prompt.strip().split("\n"):
            lines.append(f"  {line}")
    if lyrics_file:
        lines.append(f"lyrics_file: {lyrics_file}")
    lines.append("---")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Codex classifier (LLM-based)
# ---------------------------------------------------------------------------


def classify_content(content: str, filename: str = "") -> Tuple[Optional[str], bool]:
    """Use LLM to classify *content* into a Codex.

    Returns:
        (codex_name_or_None, is_suggestion)
        If the LLM thinks no existing Codex fits, it may return
        (SUGGESTED_CODEX_NAME, True) to suggest a new one.
    """
    import json
    import httpx

    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not openrouter_key:
        logger.warning("No OPENROUTER_API_KEY set — cannot classify")
        return None, False

    codex_list = "\n".join(f"- {c}" for c in KNOWN_CODEXES)
    sample = content[:2000]

    prompt = f"""You are the Pantheon Codex Classifier. A user has submitted content to be added to the Athenaeum knowledge store.

Available Codexes:
{codex_list}

Rules:
1. Read the content below.
2. Determine which Codex it best belongs to.
3. If it fits one of the existing Codexes, respond ONLY with the Codex name.
4. If NO existing Codex is a good fit, respond with "SUGGEST: Codex-<ProposedName>" followed by a brief reason on the next line.

Content (filename: {filename}):
---
{sample}
---

Return ONLY the Codex name or SUGGEST line."""

    try:
        response = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {openrouter_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "openai/gpt-4o-mini",  # fast + cheap for classification
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 100,
                "temperature": 0.1,
            },
            timeout=15.0,
        )
        response.raise_for_status()
        result = response.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        logger.warning("Classifier LLM call failed: %s", exc)
        return None, False

    # Parse result
    if result.startswith("SUGGEST:"):
        suggestion = result.replace("SUGGEST:", "").strip().split("\n")[0].strip()
        # Add to the suggestion queue
        add_suggestion({
            "suggested_codex": suggestion,
            "reason": result.split("\n")[1].strip() if "\n" in result else "",
            "from_filename": filename,
            "content_preview": sample[:200],
        })
        return suggestion, True

    # Validate it's a known Codex
    if result in KNOWN_CODEXES:
        return result, False

    # Fallback: unknown response
    return None, False
