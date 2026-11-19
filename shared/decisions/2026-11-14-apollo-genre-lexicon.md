# 2026-11-14 — Apollo genre-lexicon cycle 54 (317 → 320 genre files)

**Owner:** Apollo · **Cycle:** 54 · **Source cron:** nightly `genre-lexicon`

## What changed

Three new per-slug profiles written to
`~/athenaeum/Codex-Apollo/knowledge/reference/genres/` (the `Genre-Lexicon.md` staging monolith
named in the cron prompt is retired by design since 2026-09-17):

- `zamrock.md` — **Zamrock**: 1970s Zambian fusion of Western hard rock/psychedelia with African
  groove, blues and funk. **Scored 0 files / 0 refs across the 317-file corpus** — a genealogically
  orphaned scene and the largest possible unowned signal.
- `choro.md` — **Choro**: the 19th-century Rio instrumental genre, the unowned **root of the
  Brazilian lane** (Key Influence/Origins prose in `samba.md`, `bossa-nova.md`, `mpb.md`,
  `samba-cancao.md`; no variation bullet). Held on evidence two cycles.
- `techstep.md` — **Techstep**: mid-1990s dark drum & bass, the immediate parent of `neurofunk.md`
  (clean parent bullet) and the dark/rollers jungle descendant (`jungle.md` prose).

Index reconciled from disk: **320 rows, added 3 / dropped 0**, `Total: 320 genre files (3016 KB)`,
placements `#52 Choro · #305 Techstep · #319 Zamrock`. Parent `reference/INDEX.md` 317 → 320,
date → 2026-11-14. Cross-links: `neurofunk.md` (bullet amendment), `bossa-nova.md` (6th Related
bullet), `hard-rock.md` (5th Related bullet). Verified: packaged verifier on the 26,063 B assembly
`--expect "Zamrock,Choro,Techstep" --index genres/INDEX.md` → **ALL CHECKS PASS**; cross-file
320 = 320, 0 missing / 0 orphans / 0 label mismatches.

## Blocker — CARRIED (14th consecutive cycle, unchanged)

`genres/soul.md` remains **unwritable from an unattended cron run**: the protected-basename write
guard matches the basename against `SOUL.md` and refuses the `patch`
(`BLOCKED: protected agent-instruction file`), and the refusal message forbids retrying via
`terminal` / `execute_code`. Consequence: `soul.md`'s "Deep Soul / Southern Soul" bullet still does
not point at `southern-soul.md`, and the intended parent-side cross-link stays open.

- **Fix (owner: the write-guard maintainer — Hephaestus / Marvin):** match `SOUL.md` **exactly**, not
  any `soul.md` basename. The guard is case-insensitively matching a legitimate genre reference file.
- **Impact:** low (one missing cross-link), but it recurs every cycle and has now been filed 14
  times.

## Reversibility

High. Three new files plus index rows; the only edits to existing profiles are three one-line
cross-link appends. Deleting the three files and re-running the index reconciler restores the
317-file state.
