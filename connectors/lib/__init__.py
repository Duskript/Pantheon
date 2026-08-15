"""
Pantheon connector library.

A connector turns an external content source (YouTube, Gmail, RSS, etc.)
into markdown files in the Athenaeum inbox. Each connector implements
:class:`ConnectorBase`; the default :meth:`ConnectorBase.run` does the
authenticate → fetch → normalize → drop → update-cursor loop.

Typical usage from a CLI (``run.py``):

    from lib import YouTubeTakeoutConnector
    c = YouTubeTakeoutConnector()
    c.user_id = "konan"
    c.codex = "Codex-YouTube"
    n = c.run()
    print(f"dropped {n} items")

The three building blocks:

- :class:`ConnectorBase` — the abstract base class.
- :func:`normalize_to_inbox` — convert a :class:`RawItem` to inbox-ready
  markdown with the correct frontmatter.
- :func:`load_state` / :func:`save_state` / :func:`update_state` — per-user,
  per-source cursor and run history, with atomic writes.
"""

from .base import (
    INBOX_DIR,
    ConnectorBase,
)
from .normalize import (
    RawItem,
    normalize_to_inbox,
    parse_frontmatter,
)
from .state import (
    STATE_ROOT,
    empty_state,
    load_state,
    save_state,
    update_state,
)

__all__ = [
    "ConnectorBase",
    "INBOX_DIR",
    "RawItem",
    "STATE_ROOT",
    "empty_state",
    "load_state",
    "normalize_to_inbox",
    "parse_frontmatter",
    "save_state",
    "update_state",
]
