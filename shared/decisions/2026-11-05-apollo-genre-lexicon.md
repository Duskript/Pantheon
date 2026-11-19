# Apollo — Genre-Lexicon decisions/blockers, 2026-11-05

**Cycle:** 45th stand-alone. **Result:** 290 → **293** genre files.

**Added:** `genres/chopped-and-screwed.md` · `genres/jump-blues.md` · `genres/library-music.md` (all written
direct to per-slug files; no staging monolith). Packaged verifier on the 20,411 B temp assembly → **ALL
CHECKS PASS**. `genres/INDEX.md` rebuilt from disk → 293 rows, added 3 / dropped 0, one `Total:` line,
`Total: 293 genre files (2825 KB)`, placements #50 / #162 / #170. Parent `reference/INDEX.md` 290 → 293,
date → 2026-11-05. Precheck description words 218 / 225 / 235; 20 tags × 4 categories × 3 profiles.

**Selection, in one line:** lane-varied batch (Houston chopped-and-screwed hip-hop · 1940s R&B small-combo
dance band · 1960s–70s instrumental production music). **Chopped and Screwed** was the cycle's largest
genuine signal (12 files / 19 refs) — influence-prose parent in six profiles, tag usage in three, an
exclusion in `synthwave-and-retrowave.md`, no owned bullet. **Jump Blues** is doubly bullet-promised
(`swing-and-big-band.md`, `western-swing.md`). **Library Music** is the unowned sample-source named by the
trip-hop / vaporwave origin prose.

**Held:** Cybergrind · Country Blues / Piedmont Blues · Slam Death Metal · Paisley Underground · Cowpunk ·
Psychobilly · Future Funk · Tech House · Progressive House · Stride · Hi-NRG · Boogie Woogie · Post-Disco ·
Metallic Hardcore · Appalachian Folk · Martial Industrial · Electric Blues · Country Blues · Modern Blues ·
Roots Rock.
**Retired as ownership-adjacent this cycle:** Dark Folk (`dark-folk-and-gothic-americana.md` header is
`# Dark Folk / Gothic Americana`) · Ambient Industrial (`dark-ambient.md`'s original name) · Apocalyptic
Folk (`neofolk.md` header `# Neofolk / Apocalyptic Folk`) · Balearica (`balearic-beat.md` revival bullet) ·
Hardcore Techno (`gabber.md` umbrella).
**New probe false positives:** `Stride` (incidental "stride" prose), `Cyber Metal` (thin), `Jazz-Hop` /
`Zydeco` / `Cajun` (zero signal).

**Cross-links closed:** `swing-and-big-band.md` and `western-swing.md` → `jump-blues.md`. (Chopped and
Screwed and Library Music have no variation-bullet parent, so nothing re-scores as a gap.)

**Open (escalating, fifth cycle):** `genres/soul.md` cannot be written from an unattended run — the
protected-file guard matches the basename against `SOUL.md` and refuses without an approver. **Suggested
fix:** narrow the guard to match `SOUL.md` exactly, not any `soul.md` basename. Owner: the write-guard
maintainer (Hephaestus/Marvin).

**Also open:** cron job `f606e92fc6ee`'s prompt still names the retired `Genre-Lexicon.md` (45th cycle);
`genres/vaporwave.md` still carries the mis-merged industrial block (flagged 2026-09-29); the corpus-wide
verifier sweep (139 pass / 131 fail, 2026-10-29) is still an unmade author decision.

**Provider note:** `web_extract` returned all three Wikipedia articles on the first attempt — first clean
research cycle in ~14 runs. `Chopped and screwed` 112.6 KB; `Jump blues` 32.0 KB; `Library music` resolves
to the article title `Production music`, 15.6 KB.
