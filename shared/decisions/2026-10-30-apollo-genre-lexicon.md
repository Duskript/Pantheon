# 2026-10-30 — Apollo: a cron run cannot write `genres/soul.md` (protected-file guard), and the standing lexicon handoffs

**Filed by:** Apollo (02:00 genre-lexicon cron, 39th stand-alone cycle).

## Finding 1 — `genres/soul.md` is un-writable from an unattended run (new, blocking for cross-links)

During the 39th cycle's two-way cross-link pass, `patch` against
`~/athenaeum/Codex-Apollo/knowledge/reference/genres/soul.md` was refused:

```
BLOCKED: write to protected agent-instruction file(s) (soul.md) requires approval
but no interactive user or gateway is present to approve it.
```

The guard is matching the basename `soul.md` against the agent-instruction filename `SOUL.md`, and the
refusal message explicitly forbids retrying via terminal/execute_code. Consequence: the
`**Philadelphia Soul:**` Related bullet in `genres/soul.md` cannot be updated to point at the new
`genres/philly-soul.md`, and **every future lexicon cycle that wants to cross-link into `soul.md` will hit
the same wall**. The write itself is trivial and safe (append ` See `philly-soul.md`.` to one bullet).

**Ask:** either narrow the protected-file guard so it only matches true agent-instruction files (the
profile's own `SOUL.md`/`AGENTS.md`/`CLAUDE.md` at the profile root, not a genre reference file), or
perform the one-line edit in a supervised session. No other file in the library is affected —
`soul-jazz.md`, `psychedelic-soul.md` and `neo-soul.md` all wrote fine.

**Suggested one-line fix for a supervised run** (`genres/soul.md`, line 27, end of the Philadelphia Soul
bullet): append `` See `philly-soul.md`. ``

## Finding 2 — standing handoffs still open

- **Stale cron prompt `f606e92fc6ee`** names the retired staging file `Genre-Lexicon.md`. The 39th cycle
  ran the current contract instead (profiles written straight into `genres/<slug>.md`); the prompt text
  has now been wrong for 20+ cycles. The cron job has since been re-registered under a new id and its
  task text still says "iteratively build and expand the 'Genre-Lexicon.md' file".
- **`auto-split-refs.py` merge-instead-of-replace** — still open. Harmless in practice now that nothing
  stages a monolith in `knowledge/reference/` (`genres/` is in `SKIP_DIRS`), so this is latent, not live.
- **`genres/vaporwave.md`** still carries the mis-merged industrial profile block (now dated: it also
  contributes a second top-level `# ` heading, so a whole-corpus verifier assembly parses 276 profiles
  from 275 files).
- **The corpus has never been swept by the packaged verifier** — flagged 2026-10-29, still unfixed:
  139 pass / 131 fail across the pre-existing files, almost all of it tag counts below 12 and
  descriptions under 150 words, i.e. historic files written to looser rules. Sweep-and-top-up versus
  recalibrate-the-minimums is an author decision, not an Apollo one.
- **`genres/INDEX.md` duplicate table-header block** — fixed in the 2026-10-29 rebuild; this cycle's
  rebuild asserts exactly one header line and exactly one `Total:` line, which held (275 rows).

**Notification:** none sent — Konan's active preference disables Apollo status notifications.
