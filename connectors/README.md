# Pantheon Connectors

A connector turns an external content source (YouTube Takeout, Gmail, RSS,
Claude export, etc.) into markdown files in the Athenaeum inbox, where the
existing `process-inbox.py` pipeline picks them up for classification,
deduplication, and routing.

This is the v0.3 deliverable: the **library** that every connector
implement. The actual per-source connectors (YouTube, Gemini, …) are
separate packages in `sources/`.

## The pattern

Every connector follows the same four steps:

```
authenticate → fetch → normalize → drop in inbox
                                       ↓
                            process-inbox.py picks it up
                                       ↓
                            Codex-Stream/ingest/pipeline.py
                                       ↓
                            Codex-Stream/raw/{provider}/...
```

The connector is responsible for steps 1–4. Everything after the drop is
existing infrastructure; we don't add a new pipeline.

## What's in this directory

```
connectors/
├── README.md                  ← you are here
├── conftest.py                ← pytest setup (makes `lib` importable)
├── lib/
│   ├── __init__.py            ← public API: ConnectorBase, normalize_to_inbox, load_state, save_state
│   ├── base.py                ← ConnectorBase ABC + default run() loop
│   ├── normalize.py           ← RawItem → inbox-ready markdown
│   ├── state.py               ← per-user, per-source JSON state (atomic writes)
│   └── __tests__/             ← unit tests
│       ├── test_base.py
│       ├── test_normalize.py
│       └── test_state.py
├── sources/                   ← per-source connectors (next deliverable)
├── run.py                     ← CLI: `python run.py youtube` (next deliverable)
└── state/                     ← per-user JSON state files (created on first run)
    └── konan/
        └── <source>.json
```

## The connector contract

A connector is a class that inherits from `ConnectorBase` and implements
three methods:

```python
from datetime import datetime
from lib import ConnectorBase, RawItem


class MyConnector(ConnectorBase):
    name = "my_source"               # used for state file naming
    default_cadence = timedelta(hours=24)

    def authenticate(self) -> None:
        # OAuth, Takeout check, browser cookies, etc.
        # Raise on failure — run() catches and records the error.
        ...

    def fetch_since(self, since: datetime | None) -> Iterable[RawItem]:
        # Yield raw items newer than `since`.
        # `since` is the last `last_cursor` from state, or None.
        ...

    def normalize(self, item: RawItem) -> str:
        # Render the item as inbox-ready markdown.
        # Most connectors should just call self.normalize_default(item).
        ...
```

The default `run()` does everything else: authenticates, fetches, drops
each item into `~/athenaeum/inbox/`, and updates the cursor/state file.

### The RawItem dataclass

`RawItem` is the minimum a connector must yield from `fetch_since`:

| Field | Type | Notes |
|---|---|---|
| `item_id` | `str` | Source-unique (e.g. YouTube video ID). |
| `title` | `str` | Human-readable. Sanitized before emission. |
| `url` | `str` | Canonical source URL. Falls back to `{source}:{item_id}`. |
| `content` | `str` | Body as plain text or markdown. |
| `published_at` | `datetime \| None` | When the source content was created (not when we processed it). |
| `extra` | `Mapping` | Connector-specific frontmatter (channel, duration, etc.). |

## The inbox contract

The output of `normalize()` must match `process-inbox.py`'s expectations:

```yaml
---
title: "..."                       # required
source: "https://..."              # required — URL or source:item_id
clipped_at: "2026-06-16T..."       # required — ISO-8601 UTC, when we processed
connector: "my_source"             # always emitted by the library
codex: "Codex-XYZ"                 # optional — overrides URL classifier
note: "..."                        # optional — ≤200 char highlight
published_at: "2026-06-15T..."     # optional — from RawItem
<extra fields>                     # optional — from RawItem.extra
---

# Title

> Highlighted text

## Fetched Content
...
```

`process-inbox.py` reads `title` and `source` from the frontmatter to
classify and route. Everything else is metadata for humans or
downstream tooling.

## State

Per-connector state lives at:

```
~/pantheon/connectors/state/{user_id}/{source}.json
```

Schema (from the design doc Appendix B):

```json
{
  "source": "my_source",
  "user_id": "konan",
  "last_run": "2026-06-16T07:00:00Z",
  "last_cursor": "2026-06-15T07:00:00Z",
  "items_processed": 47,
  "oauth_expires": "2026-07-16T07:00:00Z",
  "errors": []
}
```

Writes are atomic: write to a temp file in the same directory, then
`os.replace`. A per-path `threading.Lock` serializes concurrent
`update_state()` calls (read-modify-write must be atomic, not just the
write). `process-inbox.py` failures, missing files, and corrupt JSON
are all handled gracefully — `load_state()` returns the empty default
rather than raising.

## CLI usage (next deliverable)

```bash
# Once sources/ and run.py are built:
cd ~/pantheon/connectors
python run.py youtube --since 7d
python run.py youtube --file watch-history.json
```

For now, call connectors directly from a Python script:

```python
from sources.youtube_takeout.connector import YouTubeTakeoutConnector

c = YouTubeTakeoutConnector()
c.user_id = "konan"
c.codex = "Codex-YouTube"
n = c.run()
print(f"dropped {n} items")
```

## Testing

```bash
cd ~/pantheon/connectors
python -m pytest lib/__tests__/ -v
```

39 tests cover:
- `state.py`: roundtrip, missing/corrupt files, cursor updates, error
  capping, concurrent saves, concurrent updates, identity-field forcing.
- `normalize.py`: YouTube item shape, end-to-end regex compatibility
  with `process-inbox.py`, optional fields, edge cases (empty title,
  control characters, dict input, naive datetimes).
- `base.py`: default `run()` loop, inbox drop, error handling at each
  step, cursor pickup from state, name enforcement.

## What's NOT here

This deliverable is the **library only**. Not included:

- Per-source connectors (YouTube, Gemini, etc.) — those are the next
  deliverable in `sources/`.
- The CLI entrypoint (`run.py`) — comes with the first concrete connector.
- The cron scheduler — comes with the YouTube connector.
- A "central API" or event bus — the design explicitly cuts this.

## Design doc

`~/athenaeum/Codex-Pantheon/design/user-context-engine.md` — full
context, per-source notes, profile-update loop (next phase), and the
decisions that shaped this design.
