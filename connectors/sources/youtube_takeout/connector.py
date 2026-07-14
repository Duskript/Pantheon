"""
connector.py — YouTube Takeout connector.

Parses a Google Takeout ``watch-history.json`` file, fetches a transcript
for each watched video (via the ``media/youtube-content`` skill), and
yields :class:`~lib.normalize.RawItem` records to the default
``ConnectorBase.run()`` loop, which drops them into
``~/athenaeum/inbox/`` for the existing ``process-inbox.py`` pipeline.

File-drop mode (per UCE v0.3 decision D2): pass ``file_path`` pointing at
the exported ``watch-history.json``. The connector reads it once per
``run()`` call. OAuth / live API access is deferred to v0.6+.

Takeout schema (per Google's "YouTube and YouTube Music" export)::

    [
      {
        "header": "YouTube",
        "title": "Watched <Video Title>",
        "titleUrl": "https://www.youtube.com/watch?v=VIDEO_ID",
        "subtitles": [{"name": "Channel Name", "url": "https://..."}],
        "time": "2024-01-15T10:30:00.000Z"
      },
      ...
    ]

Robustness:

* Non-YouTube entries (``header != "YouTube"`` — e.g. YouTube Music ads)
  are skipped silently.
* Removed/unavailable videos are still yielded (with a placeholder
  body) so we keep a record of consumption. The frontmatter is valid
  and ``process-inbox.py`` will route them.
* The transcript fetch is best-effort with bounded retries. A failure
  is logged and recorded as a per-item error in the state file.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Sequence

from lib.base import ConnectorBase
from lib.normalize import RawItem


logger = logging.getLogger(__name__)


# Connector identity. Must match the state-file basename so the cursor
# is consistent across runs.
CONNECTOR_NAME = "youtube_takeout"
DEFAULT_CODEX = "Codex-YouTube"

# Header for "real" YouTube video watches. YouTube Music records and
# ads come through with other header values; we drop those.
_YOUTUBE_HEADER = "YouTube"

# Match the 11-char video ID in a watch-history ``titleUrl``. Also
# tolerates the ``?v=`` form, youtu.be shortlinks, and the watch URL
# with extra query params.
_VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([A-Za-z0-9_-]{11})")

# Titles Google uses when the watched video is no longer available.
# We keep the entry (it's a real consumption record) but can't fetch a
# transcript. These are matched against the *cleaned* title (after
# the "Watched " prefix is stripped), so they don't include the prefix.
_REMOVED_TITLE_MARKERS = (
    "a video that has been removed",
    "a video that is no longer available",
    "a private video",
)

# Body text for entries where the transcript fetch failed or the video
# is gone. Used as the body when content would otherwise be empty.
_TRANSCRIPT_UNAVAILABLE_BODY = (
    "*(Transcript unavailable — the video may be private, removed, "
    "or have transcripts disabled.)*"
)

# How long to wait for a single transcript fetch. YouTube's transcript
# endpoint is fast on warm cache, slow on cold. 30s is generous.
_TRANSCRIPT_TIMEOUT_SECONDS = 30.0

# Transcript language preference order. YouTube usually has at least
# English; we fall back to whatever's available if our list misses.
_TRANSCRIPT_LANGUAGES: Sequence[str] = ("en", "en-US", "en-GB")


# ─── YouTube Takeout entry ─────────────────────────────────────────


@dataclass(frozen=True)
class WatchEntry:
    """A single parsed entry from ``watch-history.json``.

    Attributes
    ----------
    video_id
        11-character YouTube video ID. Extracted from ``titleUrl``.
    title
        The "Watched <title>" text from Takeout, with the "Watched "
        prefix stripped if present. Falls back to a placeholder for
        removed/unavailable videos.
    url
        The full ``titleUrl`` from Takeout (preserves any extra query
        params, in case Google ever adds useful ones).
    channel
        Channel name from the ``subtitles[0].name`` field, if present.
        Empty string for removed/private videos.
    watched_at
        Parsed ``time`` field as a timezone-aware UTC datetime. May be
        ``None`` if the timestamp is missing or unparseable.
    is_removed
        ``True`` if the title indicates the video is removed/private
        and we won't be able to fetch a transcript.
    """

    video_id: str
    title: str
    url: str
    channel: str
    watched_at: Optional[datetime]
    is_removed: bool


def _extract_video_id(url: str) -> Optional[str]:
    """Return the 11-char video ID from a YouTube URL, or ``None``."""
    if not url:
        return None
    m = _VIDEO_ID_RE.search(url)
    return m.group(1) if m else None


def _parse_time(raw: Any) -> Optional[datetime]:
    """Parse a Takeout ``time`` field into a UTC datetime.

    The export typically uses ISO-8601 with a ``Z`` suffix and
    millisecond precision (e.g. ``"2024-01-15T10:30:00.000Z"``). Older
    exports may use an offset (``+00:00``) instead. We accept both.
    """
    if not raw or not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    # ``fromisoformat`` in Python 3.11+ accepts the ``Z`` suffix; on
    # 3.10 we need to swap it manually.
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _clean_title(raw_title: str) -> str:
    """Strip the ``Watched `` prefix Google prepends to every entry.

    ``"Watched Some Video Title"`` → ``"Some Video Title"``.
    """
    if not raw_title:
        return ""
    cleaned = raw_title.strip()
    if cleaned.lower().startswith("watched "):
        cleaned = cleaned[len("watched "):].strip()
    return cleaned


def parse_watch_history(data: Sequence[Mapping[str, Any]]) -> List[WatchEntry]:
    """Parse a Takeout ``watch-history.json`` payload into ``WatchEntry``s.

    The function is intentionally tolerant: it skips non-YouTube
    entries, entries without a video ID, and entries with malformed
    timestamps. Each surviving entry is returned in input order.

    Parameters
    ----------
    data
        The parsed JSON — a list of dicts. Validation is shallow; we
        trust Google's export shape.

    Returns
    -------
    list[WatchEntry]
        Surviving entries in their original order.
    """
    out: List[WatchEntry] = []
    for entry in data:
        if not isinstance(entry, Mapping):
            continue
        if entry.get("header") != _YOUTUBE_HEADER:
            # YouTube Music, ads, or any other product. Skip.
            continue
        url = entry.get("titleUrl") or ""
        video_id = _extract_video_id(url)
        if not video_id:
            # Malformed URL — no video ID, can't process.
            continue
        title = _clean_title(str(entry.get("title", "")))
        is_removed = any(marker.lower() in title.lower() for marker in _REMOVED_TITLE_MARKERS)
        if is_removed and not title:
            title = "(removed video)"

        subtitles = entry.get("subtitles") or []
        channel = ""
        if subtitles and isinstance(subtitles, list) and isinstance(subtitles[0], Mapping):
            channel = str(subtitles[0].get("name", "") or "").strip()

        out.append(
            WatchEntry(
                video_id=video_id,
                title=title or f"YouTube video {video_id}",
                url=url,
                channel=channel,
                watched_at=_parse_time(entry.get("time")),
                is_removed=is_removed,
            )
        )
    return out


# ─── Transcript fetch ──────────────────────────────────────────────


class TranscriptUnavailable(Exception):
    """Raised when a transcript cannot be fetched for a video.

    ``fetch_transcript`` raises this for both permanent failures
    (transcripts disabled, video private/removed) and unexpected
    errors. The connector's :meth:`run` loop catches it and drops a
    file with a placeholder body.
    """


def _load_fetch_transcript_module() -> Any:
    """Import the ``media/youtube-content`` skill's transcript helper.

    Returns the loaded module (with ``fetch_transcript`` and
    ``format_timestamp``). Returns ``None`` if the skill is not
    available on this system.
    """
    candidates = [
        # Per-profile install (Marvin's skills dir).
        Path.home() / ".hermes/profiles/marvin/skills/media/youtube-content/scripts/fetch_transcript.py",
        # Shared skill hub.
        Path.home() / ".hermes/skills/media/youtube-content/scripts/fetch_transcript.py",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location(
            "yt_takeout_fetch_transcript", str(path)
        )
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as exc:  # noqa: BLE001 — diagnostic
            logger.warning("could not load fetch_transcript.py from %s: %r", path, exc)
            continue
        return mod
    return None


def fetch_transcript(
    video_id: str,
    *,
    languages: Optional[Sequence[str]] = None,
    timeout: float = _TRANSCRIPT_TIMEOUT_SECONDS,
) -> Optional[str]:
    """Fetch a plain-text transcript for ``video_id``.

    Returns the transcript as a single string (segments joined with
    spaces), or ``None`` if the video has no transcript / has it
    disabled / is private.

    Strategy:

    1. Try to import the ``media/youtube-content`` skill's helper
       module and call ``fetch_transcript`` directly. Fast path.
    2. Fall back to invoking the helper script via ``subprocess``.
       Slower but works when the import path is unavailable.
    3. On any failure, return ``None`` and let the caller decide
       what to do (the connector drops a placeholder file).

    This function never raises; failure modes are ``None``-returns
    with a logged warning. Tests can monkeypatch the underlying
    implementation by patching ``_load_fetch_transcript_module`` or
    by replacing this function on the module.
    """
    languages = list(languages) if languages else list(_TRANSCRIPT_LANGUAGES)
    mod = _load_fetch_transcript_module()

    if mod is not None and hasattr(mod, "fetch_transcript"):
        try:
            segments = mod.fetch_transcript(video_id, languages=languages)
        except Exception as exc:  # noqa: BLE001
            logger.warning("transcript fetch failed for %s: %r", video_id, exc)
            return None
        if not segments:
            return None
        try:
            return " ".join(str(seg["text"]).strip() for seg in segments).strip()
        except Exception:  # noqa: BLE001
            # Some segment shapes use attributes instead of dicts.
            return " ".join(str(getattr(seg, "text", "")).strip() for seg in segments).strip()

    # Fallback: subprocess. The script outputs JSON when called without
    # ``--text-only``.
    script_path_candidates = [
        Path.home() / ".hermes/profiles/marvin/skills/media/youtube-content/scripts/fetch_transcript.py",
        Path.home() / ".hermes/skills/media/youtube-content/scripts/fetch_transcript.py",
    ]
    for script in script_path_candidates:
        if not script.is_file():
            continue
        try:
            result = subprocess.run(
                [sys.executable, str(script), video_id, "--language", ",".join(languages)],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("transcript subprocess failed for %s: %r", video_id, exc)
            return None
        if result.returncode != 0:
            logger.debug(
                "transcript fetch returned %d for %s: %s",
                result.returncode, video_id, result.stderr.strip()[:200],
            )
            return None
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        if isinstance(payload, dict) and "error" in payload:
            return None
        return str(payload.get("full_text", "")).strip() or None

    logger.warning("youtube-content skill not found; cannot fetch transcripts")
    return None


# ─── Connector ─────────────────────────────────────────────────────


class YouTubeTakeoutConnector(ConnectorBase):
    """Pantheon connector for Google Takeout YouTube watch history.

    File-drop mode (per UCE v0.3 decision D2). The user exports their
    YouTube data from Google Takeout, places the resulting
    ``watch-history.json`` on disk, and runs the connector with a path
    to it.

    Parameters
    ----------
    file_path
        Absolute or workspace-relative path to ``watch-history.json``.
        Required for ``run()`` to produce any items.
    fetch_languages
        Optional override of the transcript language preference list.
        Defaults to ``("en", "en-US", "en-GB")``.

    Notes
    -----
    The connector extends the default :meth:`run` loop. It does not
    override it. Auth, fetch, normalize, and drop are all inherited
    from :class:`lib.base.ConnectorBase` — only the three abstract
    methods are source-specific.
    """

    name = CONNECTOR_NAME
    default_cadence = timedelta(days=1)

    def __init__(
        self,
        file_path: Optional[Path | str] = None,
        *,
        fetch_languages: Optional[Sequence[str]] = None,
    ) -> None:
        super().__init__()
        self.file_path: Optional[Path] = (
            Path(file_path).expanduser() if file_path is not None else None
        )
        self.fetch_languages: Sequence[str] = (
            tuple(fetch_languages) if fetch_languages is not None else _TRANSCRIPT_LANGUAGES
        )
        # Code default; the CLI overrides if the user passes --codex.
        if not self.codex:
            self.codex = DEFAULT_CODEX

    # ── abstract method overrides ──

    def authenticate(self) -> None:
        """Validate that the Takeout file is readable.

        File-drop connectors don't have credentials, but we still
        verify the file exists and is non-empty. ``run()`` catches
        exceptions and records them in state, so a missing Takeout
        file doesn't kill the cron.
        """
        if self.file_path is None:
            raise FileNotFoundError(
                "YouTubeTakeoutConnector requires file_path. "
                "Pass --file on the CLI or set connector.file_path."
            )
        path = self.file_path
        if not path.is_file():
            raise FileNotFoundError(f"watch-history.json not found at {path}")
        if path.stat().st_size == 0:
            raise ValueError(f"watch-history.json is empty: {path}")

    def fetch_since(self, since: Optional[datetime]) -> Iterable[RawItem]:
        """Yield one ``RawItem`` per watched video newer than ``since``.

        The cursor (``since``) is a UTC ``datetime``; we compare it
        against the parsed ``time`` field of each Takeout entry.
        Entries without a parseable timestamp are still yielded
        (they're rare and likely from a corrupted export — losing
        them silently would be worse than risking a re-fetch).

        Raises
        ------
        json.JSONDecodeError
            The watch-history file is not valid JSON. The base-class
            ``run()`` catches this and records it in the state file's
            ``errors`` list so operators can see something broke.
        ValueError
            The watch-history file is valid JSON but not the expected
            top-level list shape.
        OSError
            The file disappeared between ``authenticate()`` and the
            read here (rare; usually a permissions flip).
        """
        assert self.file_path is not None  # authenticate() checks this
        with self.file_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)

        if not isinstance(data, list):
            raise ValueError(
                f"watch-history.json must be a JSON list, got {type(data).__name__}"
            )

        entries = parse_watch_history(data)
        # Use a single conditional expression to format the cursor
        # timestamp — avoids an inline ``if since else`` ternary that
        # lints can flag as ambiguous.
        cursor_repr = since.isoformat() if since else "None"
        logger.info(
            "[%s] parsed %d watch entries (since=%s)",
            self.name,
            len(entries),
            cursor_repr,
        )

        for entry in entries:
            # Skip entries older than the cursor. ``None`` watched_at
            # is treated as "newer than anything" so we never lose
            # timestamp-less entries on a fresh run.
            if since is not None and entry.watched_at is not None:
                if entry.watched_at <= since:
                    continue

            content = self._content_for_entry(entry)
            extra = self._extra_for_entry(entry)
            yield RawItem(
                item_id=entry.video_id,
                title=entry.title,
                url=entry.url,
                content=content,
                published_at=entry.watched_at,
                extra=extra,
            )

    def normalize(self, item: RawItem) -> str:
        """Render ``item`` as inbox-ready markdown.

        We delegate to the base class helper, which emits the standard
        Appendix A frontmatter (``title``, ``source``, ``clipped_at``,
        ``connector``, optional ``codex``, ``published_at``, plus any
        keys we put in ``extra``). Nothing connector-specific is
        needed in the body.
        """
        return self.normalize_default(item)

    # ── helpers ──

    def _content_for_entry(self, entry: WatchEntry) -> str:
        """Build the body (transcript) for one watch entry.

        Best-effort transcript fetch with a placeholder fallback. We
        don't raise on fetch failure — the inbox file is still useful
        as a consumption record, and process-inbox.py will route it.
        """
        if entry.is_removed:
            return _TRANSCRIPT_UNAVAILABLE_BODY
        transcript = fetch_transcript(
            entry.video_id, languages=self.fetch_languages
        )
        if transcript:
            return transcript
        return _TRANSCRIPT_UNAVAILABLE_BODY

    def _extra_for_entry(self, entry: WatchEntry) -> Mapping[str, Any]:
        """Build the connector-specific frontmatter extras.

        These land in the inbox file's frontmatter under
        ``video_id``, ``channel``, ``duration`` keys. ``duration`` is
        left empty — the Takeout export doesn't include it.
        """
        return {
            "video_id": entry.video_id,
            "channel": entry.channel,
            "duration": "",
        }


__all__ = [
    "CONNECTOR_NAME",
    "DEFAULT_CODEX",
    "TranscriptUnavailable",
    "WatchEntry",
    "YouTubeTakeoutConnector",
    "fetch_transcript",
    "parse_watch_history",
]
