# Hades Nightly Run — 2026-06-03

## Status: Complete (with caveats)

**Ran at:** 2026-06-03 ~13:17 UTC

## Results
- **Health:** 7 codexes checked, all INDEX.md files present
- **Distillation:** 315 files written from 443 sessions (Codex-Forge: 228, Codex-Pantheon: 86, Codex-Infrastructure: 1)
- **Archive:** 0 stale candidates found
- **Suggestions:** None pending

## Issues
- **Embed backfill SKIPPED** — full `run_hades()` timed out at 600s during embed phase. Root causes:
  1. Dimension mismatch: ChromaDB collection expects 768-dim but embedder produces 1024-dim (likely from embedding model upgrade). Affected: Codex-Agent, Codex-Apollo files.
  2. Timeouts on large files in Codex-Apollo/methodology
  3. Codex-SKC has 0 ChromaDB vectors for 137 embeddable files
- **50 files unembedded** across Codex-SKC (bulk) and Codex-General

## Actions Needed
1. Investigate ChromaDB dimension mismatch — may need collection recreation with 1024-dim
2. Fix Codex-SKC embedding gap
3. Consider increasing hades timeout or making embed backfill async

## Deliverables
- Report: `/home/konan/athenaeum/Codex-Pantheon/reports/hades-2026-06-03.md`
- Mailbox: `~/pantheon/gods/messages/hermes/hades-20260603-*.json`
- Heartbeat: written

## Binary Fix
Fixed stale `~/.local/bin/hades` binary — was importing `run_tartarus_sweep` which doesn't exist. Rewrote to delegate to `hades.main()`.
