# Genre-Lexicon cycle 53 — Metallic Hardcore · Martial Industrial · New Age (314 → 317)

**Executor:** Apollo (cron) · **Status:** Complete · **Date:** 2026-11-13
**Write target:** `~/athenaeum/Codex-Apollo/knowledge/reference/genres/` (per-entry files — **not** the
retired staging `Genre-Lexicon.md`, which the 03:00 `auto-split-refs` cron would consume and which
truncates `genres/INDEX.md` when it fires)

**Files written (new):**
- `athenaeum/Codex-Apollo/knowledge/reference/genres/metallic-hardcore.md` (7.9 KB) — Metallic Hardcore
- `athenaeum/Codex-Apollo/knowledge/reference/genres/martial-industrial.md` (7.9 KB) — Martial Industrial
- `athenaeum/Codex-Apollo/knowledge/reference/genres/new-age.md` (7.9 KB) — New Age
- `genres/INDEX.md` (rebuilt from disk: 317 rows, casefold order, renumbered 1..317, single
  `Total: 317 genre files (2990 KB)` line, **added 3 / dropped 0**)
- `athenaeum/Codex-Apollo/knowledge/reference/INDEX.md` (count cell 314 → 317; date → 2026-11-13)
- `athenaeum/Codex-God-Apollo/journal/2026-11-13.md` (new)
- `athenaeum/Codex-Apollo/DECISIONS.md` (53rd-cycle entry appended)
- `~/pantheon/shared/active/genre-lexicon.md` (block appended)
- `~/pantheon/shared/athenaeum-writes.md` (appended)

## Selection

Fresh corpus probe over all 314 files: an ~85-candidate word-bounded count with every hit context-read
(`cache/scratch/probe-20261113.py`, `ctx-20261113.py`). Gap-scan rank 1 was owned compound-slug noise
again (`post` 37, `pop` 25, `nu` 23, `punk` 23, `rock` 17 — the `/`-fragment split shreds every
hyphenated label), so the batch was decided by the candidate probe plus hand-read parent evidence.

- **Metallic Hardcore** — unowned 1990s root of the metalcore family; **nine-cycle carry** (held since
  the 44th cycle as "influence prose only"), taken under the carried-more-than-twice rule.
  `metalcore.md`'s Key Influence/Origins names "metallic hardcore (Integrity, Earth Crisis, Converge,
  Hatebreed)" as the pioneer style (prose-parenthood = the productive signal), with `nu-metalcore.md`
  and `progressive-metalcore.md` echoing it.
- **Martial Industrial** — unowned post-industrial ceremonial branch; carried since the 44th cycle →
  taken. **Clean Related bullet in `neofolk.md`** plus `post-industrial.md`'s acoustic-ritual taxonomy.
- **New Age** — unowned therapeutic pole of the ambient family. **Referenced only through exclusion
  tags** (18 files: `new age`, `new age world music`, `new age ambient wash`, `new age spa music`,
  `no new age relaxation music`) plus `vaporwave.md` Key-Influence prose — the exclusion-tag-only green
  light, and the cycle's largest genuine unowned signal.

**Rejected as owned:** Psytrance (`psychedelic-trance.md`) · Emo Pop (`emo-pop-and-pop-emo.md`) ·
Stoner Rock (`stoner-rock-and-desert-rock.md`) · Dark Cabaret (`dark-cabaret.md`) · Trip Hop
(`trip-hop.md`) · Honky Tonk (`country.md` compound bullet) · Dixieland (`jazz.md` compound bullet) ·
Post-Disco (`mutant-disco.md` compound) · Eurodance (`hi-nrg.md` compound).
**Held on evidence:** Southern Gothic (tag usage in `sludge-metal.md` / `southern-rock.md` /
`dark-folk-and-gothic-americana.md`) · Rare Groove (a DJ practice per `acid-jazz.md`) · Celtic (probe
inflated by **Celtic Frost** the band and **Celtic harp** the instrument) · Bolero (sibling/"cousin"
language only) · Bakersfield Sound · Rap Metal · Neue Deutsche Welle · Tejano · Berlin School · Speed
Garage · Techstep · Vocal Jazz · Barbershop · Anti-Folk · Freak Folk.

## Verification

Pre-flight **ALL PASS** (description words 229 / 250 / 221; 20 tags × 4 categories × 3 profiles; 5
related bullets each; exactly 20 unique moods each; no `---`; all backticked filenames resolve).
Packaged verifier on the **24,410 B** assembly (3 separators, clean EOF) `--expect "Martial
Industrial,Metallic Hardcore,New Age" --index genres/INDEX.md` → **ALL CHECKS PASS** (incl. "parent
index names every live profile"). Index rebuilt → **317 rows, added 3 / dropped 0**, casefold order
intact, `Total: 317 genre files (2990 KB)`, measured placements **#185 Martial Industrial · #195
Metallic Hardcore · #212 New Age** (backup `genres/INDEX.md.bak-20261113070435`). Cross-file 317 = 317,
0 missing / 0 orphans / 0 label mismatches, KB column exact. Parent `reference/INDEX.md` 314 → 317,
date → 2026-11-13.

## Cross-links

`metalcore.md` (Key Influence/Origins → appended `See metallic-hardcore.md.`) · `neofolk.md` (existing
"Martial Industrial" Related bullet → `See martial-industrial.md.`) · `ambient.md` (new 6th Related
bullet "New Age (the therapeutic cousin)" → `See new-age.md.`). **Note:** `metalcore.md` and
`neofolk.md` already carry the 6-bullet Related cap, so their cross-links were written as amendments to
existing lines rather than as new bullets.

## Blockers / handoffs

**`genres/soul.md` remains unwritable from an unattended run** — the protected-basename guard matches
`SOUL.md` (refusal message: "write to protected agent-instruction file(s) (soul.md) requires approval
but no interactive user or gateway is present"), and it forbids retrying via `terminal`/`execute_code`.
**Thirteenth consecutive cycle.** Fix: match `SOUL.md` exactly, not any `soul.md` basename. Owner: the
write-guard maintainer (Hephaestus/Marvin). Cron `f606e92fc6ee`'s prompt still names the retired
`Genre-Lexicon.md`; the job prompt again lists the nonexistent skill `stylish-style-maker` (skipped).

## Notification

Skipped — Konan's active preference disables Apollo status notifications.
