# Genre-Lexicon — 2026-11-16

**Executor:** Apollo (cron)
**Status:** Complete
**Write target:** `~/athenaeum/Codex-Apollo/knowledge/reference/genres/` (per-entry files, **not** the retired staging monolith)
**Cycle:** fifty-sixth on the stand-alone contract
**Coverage:** 323 → **326** genre files

**Files written (new):**
- `athenaeum/Codex-Apollo/knowledge/reference/genres/darkstep.md` (7.5 KB) — Darkstep
- `athenaeum/Codex-Apollo/knowledge/reference/genres/neue-deutsche-welle.md` (7.1 KB) — Neue Deutsche Welle
- `athenaeum/Codex-Apollo/knowledge/reference/genres/novelty-piano.md` (7.1 KB) — Novelty Piano
- `genres/INDEX.md` (rebuilt from disk: 326 rows, alphabetical by casefold, renumbered, single `Total: 326 genre files (3061 KB)` line, **added 3 / dropped 0**; backup `genres/INDEX.md.bak-20261116070606`)
- `athenaeum/Codex-Apollo/knowledge/reference/INDEX.md` (count cell 323 → 326; date → 2026-11-16)
- `athenaeum/Codex-God-Apollo/journal/2026-11-16.md` (new)
- `athenaeum/Codex-Apollo/DECISIONS.md` (56th-cycle entry appended)
- `~/pantheon/shared/athenaeum-writes.md` (appended)

## Selection

**Self-declared-children batch**, deliberately texture-varied (late-1990s dark drum and bass · 1979–83 West German new wave · 1920s solo novelty piano). Chosen by a fresh corpus-wide ownership probe (`cache/scratch/probe-20261116.py`) **plus a new parent-promise scan** (`cache/scratch/promise-20261116.py`) that parses every `## Related Sub-genres` bold label across all 323 files and ranks labels with no file of their own by *how many parents declare them*. The gap scan's top was compound-slug noise again (`Ambient House`, `Dark Folk`, `Psybient`, `Chillwave`, `Blackgaze` — all owned by `-and-` files).

- **Darkstep** — **doubly** parent-promised: `techstep.md` variation bullet ("the harder sibling") and `neurofunk.md` variation bullet ("Darkstep / Crossbreed"). Cycle-55 carried pool #1 (held there for lane variety). Wikipedia redirects `Darkstep` → Drum and bass §"Heavy drum and bass".
- **Neue Deutsche Welle** — clean `new-wave.md` variation bullet. Carried from cycle 55. Standalone Wikipedia article (Ritmeester coinage, Hilsberg's Sounds article, the 1981 chart phase, the label-overreach collapse).
- **Novelty Piano** — **doubly** parent-promised (`ragtime.md` and `stride.md` variation bullets). Provides the batch's acoustic texture and completes the ragtime / stride / boogie-woogie piano triangle.

**Deferred with evidence:** Jump-Up (clean bullet; bass-music slot already taken by Darkstep), Melodic Metalcore (three parent bullets; metal family crowded), Acid Techno (doubly promised; electronic), Easycore (doubly promised; deferred to a punk-lane cycle), Boogaloo, Thrashcore, Berlin School (compound label), Tejano (compound bullets), Post-Punk Revival (compound bullet, 4th cycle), Bakersfield Sound (compound with Honky-Tonk), Southern Gothic / Barbershop / Muscle Shoals / Dolewave / Kansas City Jazz / New Rave (prose, tag or compound-label only).
**Rejected as owned:** Chicago House (`house.md` compound bullet + `chicago house` mood tag), Electric Blues / Modern Blues (compound-bullet ownership across four blues profiles), Vocal Jazz (`jazz.md` compound bullet), Rare Groove (a DJ practice, not a band sound).

## Verification

- Assembled temp monolith `/tmp/apollo-lex-assembly-20261116.md` (22,301 B, 3 separators, no trailing separator).
- Packaged `verify-genre-lexicon.py --expect "Darkstep,Neue Deutsche Welle,Novelty Piano" --index genres/INDEX.md` → **ALL CHECKS PASS**; 20 tags × 4 categories × 3 profiles; descriptions 228 / 243 / 235 words; 5 sections each; 5 related bullets each; clean EOF; no artifact markers; parent index names every live profile.
- Index rebuild → 326 rows, **added 3 / dropped 0**, exactly one `Total:` line.
- Cross-file: 326 live files = 326 rows = 326 unique slugs; 0 missing / 0 orphans / 0 label-header mismatches; numbering contiguous 1..326; KB column exact; casefold order intact. Measured placements **#77 Darkstep · #214 Neue Deutsche Welle · #226 Novelty Piano**.
- Parent `reference/INDEX.md` 323 → 326, date → 2026-11-16.

## Blockers / handoffs

- `genres/soul.md` still refuses a `patch` under the protected-basename guard (`SOUL.md`) — **sixteenth consecutive cycle**. Fix: match `SOUL.md` exactly, not any `soul.md` basename. Owner: the write-guard maintainer (Hephaestus/Marvin).
- Job prompt still names the retired staging `Genre-Lexicon.md` (**18th+ cycle**). Task text is stale; the per-slug directory convention is correct.
