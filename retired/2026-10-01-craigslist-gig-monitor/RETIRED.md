# Retired: Craigslist Gig Monitor (2026-10-01)

**Decision:** Konan chose Option A ("keep it dead") on 2026-10-01 in Discord thread
#notifications/craigslist-gig-monitor (msg 1555307152644509748).

## What was removed
- Cron job `9acdceb5ba2d` "Craigslist Gig Monitor" (`0 */4 * * *`) — REMOVED (was paused 2026-09-29 20:02 MDT).
- `~/.hermes/scripts/craigslist-gig-monitor.py` — no_agent wrapper (archived here).
- `~/pantheon/scripts/craigslist-monitor.py` — the 251-line monitor itself (archived here).

## Why it was killed
No seen-state/dedupe: it re-posted the same 27-37 listings 6x/day (~30 msgs/day),
plus `generate_pitch()` fabricated canned replies that read as auto-spam.

## Data left in place (not deleted)
- `~/pantheon/craigslist_leads.json`
- `~/pantheon/craigslist_leads.html`
- `~/pantheon/craigslist_leads_20260702_0205.json`

## To restore
Copy both .py files back to their original paths and re-create the cron job.
