"""
base.py — ConnectorBase ABC and the default ``run()`` loop.

The base class encodes the connector pattern from the design doc (§3):

    1. Authenticate (OAuth, Takeout, browser cookies, etc.)
    2. Fetch new content since last run
    3. Normalize to the standard ``process-inbox.py`` input format
    4. Drop into ``~/athenaeum/inbox/``
    5. Update the connector's own dedupe/cursor state

The default :meth:`ConnectorBase.run` implements steps 1-5 using the helpers
in :mod:`.normalize` and :mod:`.state`. Concrete connectors (e.g.
``YouTubeTakeoutConnector``) only have to implement the three abstract
methods that are source-specific: ``authenticate``, ``fetch_since``,
``normalize``.

The ``codex`` and ``user_id`` parameters are kept on the instance so
connectors don't have to thread them through every call. The CLI
(``run.py``) constructs a connector, sets ``user_id``, then calls
``run()``.
"""

from __future__ import annotations

import logging
import os
import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from .normalize import RawItem, normalize_to_inbox
from .state import load_state, update_state


logger = logging.getLogger(__name__)


# Inbox location. Mirrors ``process-inbox.py``'s ``INBOX_DIR``. Resolved at
# import time so tests can monkeypatch it.
INBOX_DIR = Path(os.path.expanduser("~/athenaeum/inbox"))


# Filename slug rules. We strip everything except alphanumerics and dashes,
# collapse runs of dashes, and cap at 60 chars. Matches the existing inbox
# file naming pattern (``clip-1778936270--<slug>.md``).
_SLUG_NONALNUM = re.compile(r"[^a-z0-9]+")
_SLUG_MAX = 60


def _slugify(text: str) -> str:
    """Make ``text`` filesystem-safe. Returns ``"clip"`` for empty input."""
    s = _SLUG_NONALNUM.sub("-", text.lower()).strip("-")
    return s[:_SLUG_MAX].rstrip("-") or "clip"


def _build_inbox_path(item: RawItem, source: str) -> Path:
    """Compute the destination path in the inbox for ``item``.

    Filename shape: ``<UTC-timestamp>--<source>--<slug>.md``. Including the
    source in the filename makes it obvious where a file came from when
    reviewing the inbox by hand.
    """
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    # Sub-second collisions are possible if a connector yields multiple
    # items in the same call; append the item_id hash for uniqueness.
    suffix_id = re.sub(r"[^a-zA-Z0-9_-]", "", item.item_id)[:16] or "x"
    fname = f"{ts}--{source}--{_slugify(item.title)}--{suffix_id}.md"
    return INBOX_DIR / fname


class ConnectorBase(ABC):
    """Base class for all Pantheon connectors.

    Subclasses must define :attr:`name` and :attr:`default_cadence`, and
    implement the three abstract methods. The default :meth:`run` does
    everything else.

    Attributes
    ----------
    name
        Connector identifier. Must match the state file basename
        (``{user_id}/{name}.json``) so that the cursor stays consistent
        across runs.
    default_cadence
        How often this connector is intended to run. Used by the scheduler
        to decide whether a run is overdue. The default ``run()`` ignores
        it — the scheduler is responsible for throttling.
    user_id
        Tenant identifier. Set by ``run.py`` before calling ``run()``.
    codex
        Optional target codex for the connector's output. If set, every
        item will land in the inbox with a ``codex:`` field that
        ``process-inbox.py`` will respect (skipping its URL classifier).
    """

    name: str = ""
    default_cadence: timedelta = timedelta(hours=24)

    # Set by the CLI / scheduler before calling ``run()``.
    user_id: str = "konan"
    codex: Optional[str] = None

    # ---------- abstract methods (subclass responsibility) ----------

    @abstractmethod
    def authenticate(self) -> None:
        """Acquire or refresh credentials. May be a no-op for file-drop connectors.

        Should raise on failure; ``run()`` catches and records the error
        in the state file rather than propagating, so a broken auth on
        one connector doesn't kill the cron.
        """

    @abstractmethod
    def fetch_since(self, since: Optional[datetime]) -> Iterable[RawItem]:
        """Yield raw items newer than ``since``.

        ``since`` is the value of the last ``last_cursor`` in state, or
        ``None`` for a fresh connector. The connector decides what
        "newer than" means — it might be a server-side ``updatedAfter``
        filter, or a local file timestamp.
        """

    @abstractmethod
    def normalize(self, item: RawItem) -> str:
        """Render ``item`` as inbox-ready markdown.

        Most connectors should just call :func:`normalize_to_inbox` from
        ``.normalize``. The hook exists so a connector can add connector-
        specific fields (e.g. a YouTube ``video_id`` frontmatter key)
        before delegating.
        """

    # ---------- default loop ----------

    def run(self, since: Optional[datetime] = None) -> int:
        """Run the full connector loop. Returns the number of items dropped.

        The default implementation handles the four steps that every
        connector shares: auth → fetch → normalize → drop → update cursor.
        Subclasses may override to add connector-specific behavior
        (rate limiting, OAuth refresh, etc.) but should call into this
        method for the default flow.

        Parameters
        ----------
        since
            Override the cursor; useful for backfills. ``None`` reads
            ``last_cursor`` from state.

        Returns
        -------
        int
            Number of items written to the inbox during this run. ``0``
            is a valid (and common) result for "no new content."
        """
        if not self.name:
            raise RuntimeError(
                "Connector must define a non-empty `name` attribute"
            )

        logger.info("[%s] run() start (user=%s)", self.name, self.user_id)

        # Step 1: authenticate. Failure here is a hard error — we record
        # it in state and bail rather than re-fetching on broken creds.
        try:
            self.authenticate()
        except Exception as exc:  # noqa: BLE001 — we record and continue
            logger.exception("[%s] authenticate() failed", self.name)
            update_state(
                self.user_id,
                self.name,
                error=f"authenticate: {exc!r}",
            )
            return 0

        # Resolve the cursor: caller override > state > None (full sync).
        if since is None:
            state = load_state(self.user_id, self.name)
            cursor_str = state.get("last_cursor")
            if cursor_str:
                try:
                    since = datetime.fromisoformat(
                        cursor_str.replace("Z", "+00:00")
                    )
                except ValueError:
                    logger.warning(
                        "[%s] could not parse last_cursor %r; ignoring",
                        self.name,
                        cursor_str,
                    )
                    since = None

        # Step 2 + 3 + 4: fetch → normalize → drop.
        dropped = 0
        latest_seen: Optional[datetime] = None
        try:
            for raw in self.fetch_since(since):
                try:
                    md = self.normalize(raw)
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "[%s] normalize() failed for %s", self.name, raw.item_id
                    )
                    update_state(
                        self.user_id,
                        self.name,
                        error=f"normalize {raw.item_id}: {exc!r}",
                    )
                    continue

                path = self._drop_in_inbox(raw, md)
                dropped += 1
                logger.info(
                    "[%s] dropped %s as %s",
                    self.name,
                    raw.item_id,
                    path.name,
                )

                if raw.published_at is not None:
                    if latest_seen is None or raw.published_at > latest_seen:
                        latest_seen = raw.published_at
        except Exception as exc:  # noqa: BLE001
            logger.exception("[%s] fetch_since() failed", self.name)
            update_state(
                self.user_id,
                self.name,
                error=f"fetch_since: {exc!r}",
            )
            # Don't return early — we may have already dropped some items
            # and we want to record the run timestamp.

        # Step 5: update cursor + run timestamp.
        new_cursor: Optional[str] = None
        if latest_seen is not None:
            new_cursor = latest_seen.astimezone(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        update_state(
            self.user_id,
            self.name,
            cursor=new_cursor,
            items_added=dropped,
        )

        logger.info("[%s] run() done: dropped=%d", self.name, dropped)
        return dropped

    # ---------- inbox drop ----------

    def _drop_in_inbox(self, item: RawItem, markdown: str) -> Path:
        """Write ``markdown`` to a unique path in the inbox.

        Default filename pattern: ``<UTC-timestamp>--<source>--<slug>--<id>.md``.
        Subclasses may override to customize the filename (e.g. to put
        all of a source's items in a subdirectory for batch review).
        """
        path = _build_inbox_path(item, self.name)
        path.write_text(markdown, encoding="utf-8")
        return path

    # ---------- helpers for subclasses ----------

    def normalize_default(
        self,
        item: RawItem,
        *,
        codex: Optional[str] = None,
        note: Optional[str] = None,
    ) -> str:
        """Render ``item`` with the library's default frontmatter shape.

        Connectors that don't need extra frontmatter fields can either
        implement :meth:`normalize` as ``return self.normalize_default(item)``
        or skip the override entirely (the base class doesn't provide a
        default ``normalize`` — subclasses must implement it).
        """
        return normalize_to_inbox(
            item,
            source=self.name,
            codex=codex if codex is not None else self.codex,
            note=note,
        )

    def items_to_markdown(self, items: Iterable[RawItem]) -> List[str]:
        """Helper for tests: render a batch of items using ``normalize_default``."""
        return [self.normalize_default(i) for i in items]
