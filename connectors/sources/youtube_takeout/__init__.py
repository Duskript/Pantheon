"""
youtube_takeout — YouTube Takeout connector.

Parses a Google Takeout ``watch-history.json`` file, fetches a transcript
for each watched video (via the ``media/youtube-content`` skill), and
drops the result into the Athenaeum inbox where the existing
``process-inbox.py`` pipeline picks it up.

File-drop mode (per UCE v0.3 Konan decision D2): the user exports
YouTube data from Google Takeout and places ``watch-history.json`` at a
local path. OAuth is deferred to v0.6+.

Usage from a script::

    from sources.youtube_takeout.connector import YouTubeTakeoutConnector
    c = YouTubeTakeoutConnector(file_path="watch-history.json")
    c.user_id = "konan"
    c.codex = "Codex-YouTube"
    n = c.run()
    print(f"dropped {n} items")

Usage from the CLI (see ``run.py``)::

    cd ~/pantheon/connectors
    python run.py youtube --file watch-history.json
"""

from .connector import YouTubeTakeoutConnector

__all__ = ["YouTubeTakeoutConnector"]
