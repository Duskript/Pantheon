# 2026-06-19T20:10Z — Marvin inbox drain (poller launch)

**Trigger:** god-inbox-poller.sh launch, prompt "330 unread" (its metric).
**Actual unread:** 2.
**Action taken:** marked both read; extracted items logged to ichor_store key `marvin-inbox-drain-2026-06-19T2010Z`.

## Open items extracted from corrupted bodies (not actioned here)

- Clawforge Phases 5-6 — blocked on Olympus-UI 9119 fix browser verification (C2 Weight Tuning + Benchmarks stage). Owner: Hephaestus / Iris, dependent on me confirming UI fix in browser.
- TieredRetriever — `TIERED_ENABLED` env var regression; test fixture uses `sqlite3.connect(":memory:")` without row factory, hits plain tuple path. Needs patch + test.
- Possible Clara medical-KB update reference (body too mangled to confirm).

## Open question (to user)

god-inbox-poller.sh line 85 counts last-24h JSON files, not canonical unread. Recommended fix: change to count `read != true` (one-line patch). Want me to apply it, or leave the poller's behavior alone?
