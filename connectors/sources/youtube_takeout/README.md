# YouTube Takeout Connector

The first per-source connector for the Pantheon connectors library.
Reads a Google Takeout `watch-history.json`, fetches a transcript for
each watched video, and drops a markdown file per video into the
Athenaeum inbox where the existing `process-inbox.py` pipeline picks
it up.

File-drop mode (per UCE v0.3 Konan decision **D2**). The user
exports YouTube data from Google Takeout, drops `watch-history.json`
somewhere on disk, and runs the connector with a path to it. OAuth
and live API access are deferred to v0.6+.

---

## Quick start

```bash
cd ~/pantheon/connectors

# One-shot run against a Takeout export.
python run.py youtube --file ~/Downloads/watch-history.json

# Show the inbox output (D2 is non-destructive — the originals stay put).
ls -la ~/athenaeum/inbox/

# Then process the new files into Codex-YouTube via the existing pipeline.
python ~/athenaeum/scripts/process-inbox.py
```

For programmatic use:

```python
from sources.youtube_takeout.connector import YouTubeTakeoutConnector

c = YouTubeTakeoutConnector(file_path="watch-history.json")
c.user_id = "konan"
c.codex = "Codex-YouTube"
n = c.run()
print(f"dropped {n} items")
```

---

## How to export from Google Takeout

1. Go to <https://takeout.google.com>.
2. Click **Deselect all**, then scroll to **YouTube and YouTube Music** and toggle it on.
3. Click **All YouTube data included** → at minimum, toggle on **history** (watch history). You can include the rest if you want, but the connector only reads `watch-history.json`.
4. Choose **Export once** and **`.json`** format. Hit **Create export**.
5. Google emails you when the export is ready (usually a few hours). Download the `.zip`.
6. Unzip it. The watch-history file is at:
   ```
   Takeout/YouTube and YouTube Music/history/watch-history.json
   ```
7. Move (or symlink) it somewhere on the local filesystem. Pass the absolute path to `--file`:
   ```bash
   python run.py youtube --file /path/to/watch-history.json
   ```

### State and re-runs

Each run creates or updates a state file at:

```
~/pantheon/connectors/state/<user_id>/youtube_takeout.json
```

The file tracks the cursor (the most recent `time` field seen), the
total items processed, and the last 20 errors. A second run against
the same file will drop zero new items — the cursor skips everything
we've already ingested. To re-process from scratch, delete the state
file or pass `--since 1970-01-01T00:00:00Z` to override the cursor.

---

## What gets dropped in the inbox

For each watched video, the connector writes a file like:

```
~/athenaeum/inbox/20260617-143022--youtube_takeout--how-to-write-a-connector--vidAAAA0001.md
```

with the standard process-inbox.py frontmatter plus YouTube-specific
extras:

```yaml
---
title: "How To Write A Connector"
source: "https://www.youtube.com/watch?v=vidAAAA0001"
clipped_at: "2026-06-17T14:30:22Z"
connector: "youtube_takeout"
codex: "Codex-YouTube"
published_at: "2024-01-15T10:30:00Z"
video_id: "vidAAAA0001"
channel: "Pantheon Academy"
duration: ""
---
# How To Write A Connector

## Fetched Content
[transcript text here]
```

The downstream pipeline picks these up and writes them to
`Codex-Stream/raw/youtube/`. Each inbox file corresponds to one
watch-history entry (one YouTube video), not one Takeout export — so
a 500-entry export produces 500 inbox files (minus anything the
parser drops, see below).

---

## What the connector skips

The parser is intentionally tolerant of Google Takeout's quirks. It
drops:

* **Non-YouTube entries** (header ≠ `"YouTube"`) — e.g. YouTube Music
  records and ads.
* **Entries with no `titleUrl`** — usually malformed exports.
* **Entries where the video ID can't be extracted** from the URL.

It **keeps** entries where the title says the video is removed or no
longer available, but yields them with a placeholder body. The
frontmatter is valid so process-inbox.py can still route them; the
operator can decide what to do with "consumed but unrescuable"
records downstream.

---

## Transcript fetch

Transcripts come from the shared `media/youtube-content` skill (the
same one Hermes uses for ad-hoc YouTube summarization). The
connector:

1. Imports the skill's `fetch_transcript.py` helper directly via
   `importlib` (fast path).
2. Falls back to invoking the helper as a subprocess if the import
   path is unavailable.
3. Returns `None` on any failure — the connector drops a placeholder
   file rather than crashing the run.

The skill requires `youtube-transcript-api`:

```bash
pip install youtube-transcript-api
```

To override the language preference list:

```python
c = YouTubeTakeoutConnector(
    file_path="watch-history.json",
    fetch_languages=("en", "tr", "de"),
)
```

---

## CLI reference

```
python run.py youtube --file PATH [--user-id ID] [--codex CODEX] [--since TS]
```

| Flag | Required | Default | Description |
|---|---|---|---|
| `--file PATH` | yes | — | Absolute or workspace-relative path to `watch-history.json`. |
| `--user-id ID` | no | `konan` | Tenant identifier. Controls the state-file subdirectory. |
| `--codex CODEX` | no | `Codex-YouTube` | Target codex written to each inbox file's frontmatter. |
| `--since TS` | no | state cursor | ISO-8601 UTC timestamp; overrides the cursor. Use `--since 1970-01-01T00:00:00Z` to force a re-process. |

Exit codes:

| Code | Meaning |
|---|---|
| 0 | At least one item was dropped. |
| 0 | No new items (the cursor skipped everything). |
| 1 | Authentication / file-not-found error. The state file's `errors` list has the message. |

`run.py` is silent unless something fails — pair it with `--verbose`
in the wrapper if you want progress logs.

---

## Known gaps (downstream, not blocking D2)

* **`process-inbox.py` ignores the `codex:` frontmatter field.**
  Today it derives the target codex from the URL via its domain
  classifier. YouTube URLs currently route to `Codex-General` because
  the domain map doesn't include `youtube.com`. The connector still
  emits `codex: "Codex-YouTube"` per the design doc — closing the
  loop on the consumer side is a v0.3 / v0.5 follow-up.
* **No dedupe by transcript hash.** If you run the connector twice
  with `--since 1970-01-01`, you get two inbox files per video. The
  cursor is the only dedupe mechanism.
* **No retry queue for transcript failures.** A network blip drops a
  placeholder file. Re-running the connector with the cursor
  advanced past that entry will not re-attempt. To retry a single
  failure, edit the state file's `last_cursor` back to a value
  before that video's `time`.

---

## Tests

```bash
cd ~/pantheon/connectors
python -m pytest sources/youtube_takeout/tests/ -v
```

23 tests cover:

* `parse_watch_history` — 7 tests for schema tolerance (non-YouTube
  headers, missing URLs, removed videos, missing subtitles, bad
  timestamps, alternate URL forms, mixed-type payloads).
* `YouTubeTakeoutConnector` end-to-end — 13 tests for the full
  `run()` loop, inbox frontmatter regex, cursor advance, transcript
  failure handling, removed-video handling, missing/malformed file
  handling, wrong top-level shape, the public API surface, and the
  cursor-skipping behavior on the second run.
* CLI smoke — 1 test confirming the package exports the connector.
