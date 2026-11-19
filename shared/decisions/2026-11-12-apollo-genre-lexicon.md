# Genre-Lexicon cycle 52 — Mambo · Boogie-Woogie · Dunedin Sound (311 → 314)

**Executor:** Apollo (cron) · **Status:** Complete · **Date:** 2026-11-12
**Write target:** `~/athenaeum/Codex-Apollo/knowledge/reference/genres/` (per-entry files — **not** the
retired staging `Genre-Lexicon.md`, which the 03:00 `auto-split-refs` cron would consume and which
truncates `genres/INDEX.md` when it fires)

**Files written (new):**
- `athenaeum/Codex-Apollo/knowledge/reference/genres/mambo.md` (6.6 KB) — Mambo
- `athenaeum/Codex-Apollo/knowledge/reference/genres/boogie-woogie.md` (6.7 KB) — Boogie-Woogie
- `athenaeum/Codex-Apollo/knowledge/reference/genres/dunedin-sound.md` (6.5 KB) — Dunedin Sound
- `genres/INDEX.md` (rebuilt from disk: 314 rows, casefold order, renumbered 1..N, single `Total: 314 genre files (2965 KB)` line, **added 3 / dropped 0**)
- `athenaeum/Codex-Apollo/knowledge/reference/INDEX.md` (count cell 311 → 314; date → 2026-11-12)
- `athenaeum/Codex-God-Apollo/journal/2026-11-12.md` (new)
- `athenaeum/Codex-Apollo/DECISIONS.md` (52nd-cycle entry appended)
- `~/pantheon/shared/active/genre-lexicon.md` (block appended)
- `~/pantheon/shared/athenaeum-writes.md` (appended)

## Selection

Fresh corpus probe over all 311 files: variation-bullet gap scan + an 18-candidate word-bounded count,
every hit context-read (`cache/scratch/probe-20261112.txt`, `ctx-20261112.txt`). Gap-scan rank 1 was
owned compound-slug noise again (`post` 37, `pop` 25, `nu` 23, `punk` 23, `rock` 17, `neo` 16, `hop` 15 —
the `/`-fragment split shreds every hyphenated label), so the batch was decided by the candidate probe
plus hand-read parent evidence.

- **Mambo** — the unowned root of the Latin dance lane; named as a parent idiom in `salsa.md`'s Key
  Influence/Origins (prose-parenthood — the Ska/Samba pattern). Afro-Cuban big-band dance, 1940s–50s.
- **Boogie-Woogie** — the unowned blues-piano root; **bullet-promised by `stride.md`** ("the
  blues-shuffle cousin", written the previous cycle) and **green-lit by `piano-rock-and-piano-driven-alternative.md`'s
  exclusion tags** (`boogie woogie`), with tag usage in `blues.md` / `chicago-blues.md` / `jump-blues.md` /
  `rockabilly.md`.
- **Dunedin Sound** — a **clean single bullet in `jangle-pop.md`** with no file of its own; the early-1980s
  Dunedin, Otago scene that helped found indie rock (Flying Nun, the Dunedin Double EP).

**Rejected as owned by a parent variation bullet:** Eurodance (`hi-nrg.md` compound "Eurobeat /
Eurodance") · Post-Disco (`mutant-disco.md` compound "Dub-Funk / Post-Disco") · Baião (`forro.md` own
bullet) · Appalachian Folk (`old-time.md` own bullet; the tradition *is* old-time).
**Held on evidence:** Metallic Hardcore (influence prose only in `metalcore.md`, no bullet — carried since
the 44th cycle, now past the carried-twice line: take or drop next cycle) · Southern Gothic (a mood tag in
`sludge-metal.md`/`southern-rock.md`, not a sonic profile) · Rare Groove (`acid-jazz.md` bullet calls it a
DJ practice) · Choro (prose only, no bullet) · Muscle Shoals (a studio/scene) · New Age (exclusion-tag only).

## Verification

Pre-flight **ALL PASS** (description words 236 / 236 / 236; 20 tags × 4 categories × 3 profiles; 5 related
bullets each; exactly 20 unique moods each; no `---`). Packaged verifier on the 20,448 B assembly (3
separators, clean EOF) `--expect "Boogie-Woogie,Dunedin Sound,Mambo" --index genres/INDEX.md` → **ALL
CHECKS PASS** (incl. "parent index names every live profile"). Index rebuilt → **314 rows, added 3 /
dropped 0**, casefold order intact, `Total: 314 genre files (2965 KB)`, measured placements **#33
Boogie-Woogie · #99 Dunedin Sound · #183 Mambo** (backup `genres/INDEX.md.bak-20261112070412`). Cross-file
314 = 314, 0 missing / 0 orphans / 0 label mismatches. Parent `reference/INDEX.md` 311 → 314, date →
2026-11-12.

## Cross-links

`stride.md` (Boogie-Woogie Related bullet → `See boogie-woogie.md.`), `jump-blues.md` (Key
Influence/Origins → `(see \`boogie-woogie.md\`)`), `jangle-pop.md` (Dunedin Sound bullet → `See
dunedin-sound.md.`), `salsa.md` (Key Influence/Origins `mambo` → `mambo (\`mambo.md\`)`). No blocked writes
this cycle.

## Blockers / handoffs

`genres/soul.md` remains unwritable from an unattended run (protected-basename guard matches `SOUL.md`) —
**twelfth cycle**; fix is to match `SOUL.md` exactly, not any `soul.md` basename. Owner: the write-guard
maintainer (Hephaestus/Marvin). Cron `f606e92fc6ee`'s prompt still names the retired `Genre-Lexicon.md`;
the job prompt again lists a nonexistent skill `stylish-style-maker` (skipped).

## Notification

Skipped — Konan's active preference disables Apollo status notifications.
