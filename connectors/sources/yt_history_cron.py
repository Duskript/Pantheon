#!/usr/bin/env python3
"""
yt-history-cron.py — Daily YouTube watch history reference list.
No video downloads. No transcripts. Just video metadata (id, title, channel, duration).

Dependencies: yt-dlp (installed at /home/konan/.local/bin/yt-dlp)
Usage:
  python3 yt-history-cron.py --dry-run          # test run, print to stdout
  python3 yt-history-cron.py                    # daily incremental run (cron mode)
  python3 yt-history-cron.py --backfill=500     # grab N most recent entries
"""
import subprocess, json, os, sys
from datetime import datetime, timezone

# ── All paths absolute to avoid HOME env issues in cron ──
COOKIE_FILE = "/home/konan/.hermes/profiles/thoth/cache/documents/doc_9946c278b1b2_YouTubecookies"
YT_DLP = "/home/konan/.local/bin/yt-dlp"
STATE_DIR = "/home/konan/.hermes/profiles/thoth/state"
OUTBOX_DIR = "/home/konan/athenaeum/inbox"
DAILY_LIMIT = 30
BACKFILL_LIMIT = 500
STATE_FILE = os.path.join(STATE_DIR, "yt_history_cursor.json")

os.makedirs(STATE_DIR, exist_ok=True)
os.makedirs(OUTBOX_DIR, exist_ok=True)

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_video_id": None, "last_run": None, "total_fetched": 0}

def save_state(state):
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def fetch_history(limit):
    """Call yt-dlp, return list of entry dicts (newest first)."""
    cmd = [
        YT_DLP, "--flat-playlist",
        "--cookies", COOKIE_FILE,
        "https://www.youtube.com/feed/history",
        "--playlist-end", str(limit),
        "--print", "%(id)s||%(title)s||%(channel)s||%(uploader)s||%(duration)s||%(view_count)s||%(upload_date>%Y-%m-%d)s",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        print(f"yt-dlp exit code {result.returncode}", file=sys.stderr)
        if result.stderr: print(f"stderr: {result.stderr[:300]}", file=sys.stderr)
        return []

    entries = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip() or "||" not in line: continue
        parts = line.split("||")
        if len(parts) < 4: continue
        vid = parts[0].strip()
        title = parts[1].strip()
        channel = parts[2].strip() or parts[3].strip() or ""
        dur_str = parts[4].strip() if len(parts) > 4 else "0"
        views_str = parts[5].strip() if len(parts) > 5 else ""
        upload_date = parts[6].strip() if len(parts) > 6 else ""
        dur = 0
        if dur_str and dur_str != "NA":
            try: dur = int(dur_str)
            except: pass
        views = 0
        if views_str and views_str != "NA":
            try: views = int(views_str)
            except: pass
        entries.append({
            "videoId": vid,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "title": title,
            "channel": channel if channel != "NA" else "",
            "duration_sec": dur,
            "view_count": views,
            "upload_date": upload_date if upload_date != "NA" else "",
        })
    return entries

def build_inbox_file(entry, now_iso):
    d = entry["duration_sec"]
    if d:
        m, s = divmod(d, 60)
        h, m = divmod(m, 60)
        dur_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    else: dur_str = ""
    lines = [
        "---",
        f'title: "{entry["title"]}"',
        f'source: "{entry["url"]}"',
        f'clipped_at: "{now_iso}"',
        f'connector: "yt_history_cron"',
        f'codex: "Codex-YouTube"',
        f'video_id: "{entry["videoId"]}"',
        f'channel: "{entry["channel"]}"',
        f'duration: "{dur_str}"',
        "---",
        f"# {entry['title']}",
        "",
        f"**Channel:** {entry['channel']}",
        f"**Duration:** {dur_str}",
        f"**URL:** {entry['url']}",
        "",
        "*(Watch history reference entry — no transcript fetched)*",
    ]
    return "\n".join(lines)

def write_inbox(entries, dry_run=False):
    now_iso = datetime.now(timezone.utc).isoformat()
    written = 0
    for entry in entries:
        ts = now_iso[:19].replace(":", "-").replace("T", "--")
        filename = f"{ts}--yt_history--{entry['videoId']}.md"
        content = build_inbox_file(entry, now_iso)
        if dry_run:
            print(f"\n=== {filename} ===")
            print(content)
        else:
            path = os.path.join(OUTBOX_DIR, filename)
            with open(path, "w") as f:
                f.write(content)
            written += 1
    return written

def main():
    dry_run = "--dry-run" in sys.argv
    backfill = False
    limit = DAILY_LIMIT
    for arg in sys.argv[1:]:
        if arg == "--dry-run": dry_run = True
        elif arg.startswith("--backfill"):
            backfill = True
            try: limit = int(arg.split("=")[1])
            except: limit = BACKFILL_LIMIT

    state = load_state()
    if dry_run:
        print(f"Mode: {'BACKFILL' if backfill else 'daily'}")
        print(f"Limit: {limit} entries")
        print(f"State: last_video_id={state['last_video_id']}, total_fetched={state['total_fetched']}")

    entries = fetch_history(limit)
    if not entries:
        print("No entries returned.", file=sys.stderr)
        return 1

    last_id = state.get("last_video_id")
    if last_id and not backfill:
        new_entries = []
        for e in entries:
            if e["videoId"] == last_id: break
            new_entries.append(e)
        new_entries.reverse()
    else:
        new_entries = list(reversed(entries)) if not backfill else entries

    if not new_entries:
        print("No new entries since last run.")
        return 0

    print(f"Fetched {len(entries)} total, {len(new_entries)} new")
    count = write_inbox(new_entries, dry_run)

    if not dry_run:
        state["last_video_id"] = entries[0]["videoId"]
        state["total_fetched"] = state.get("total_fetched", 0) + len(new_entries)
        save_state(state)
        print(f"Wrote {count} files to {OUTBOX_DIR}")
    else:
        print(f"\nDry run: would write {len(new_entries)} files")
    return 0

if __name__ == "__main__":
    sys.exit(main())
