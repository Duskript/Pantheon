# Apollo — Genre-Lexicon decisions/blockers, 2026-11-04

**Cycle:** 44th stand-alone. **Result:** 287 → **290** genre files.

**Added:** `genres/northern-soul.md` · `genres/western-swing.md` · `genres/mallsoft.md` (all written direct to
per-slug files; no staging monolith). Packaged verifier on the 20,906 B temp assembly → **ALL CHECKS PASS**.
`genres/INDEX.md` rebuilt from disk → 290 rows, added 3 / dropped 0, one `Total:` line,
`Total: 290 genre files (2807 KB)`, placements #171 / #204 / #287. Parent `reference/INDEX.md` 287 → 290,
date → 2026-11-04. Precheck description words 238 / 227 / 227; 20 tags × 4 categories × 3 profiles.

**Selection, in one line:** lane-varied batch (British rare-soul dancefloor · 1930s–40s Texas/Oklahoma
country-jazz dance band · 2010s internet mall ambient). **Northern Soul** closes the 43rd cycle's carried #1
— doubly bullet-promised (`motown.md`, `soul.md`). **Western Swing** is bullet-promised by
`swing-and-big-band.md` and named in `outlaw-country.md` origins. **Mallsoft** is bullet-promised by
`vaporwave.md` and green-lit by a `progressive-rock.md` exclusion tag.

**Held:** Cybergrind · Country Blues / Piedmont Blues · Slam Death Metal · Jump Blues · Paisley Underground ·
Cowpunk · Psychobilly · Future Funk · Aggrotech · Tech House · Progressive House · Chopped and Screwed ·
Atmospheric Black Metal · Industrial Dance · Stride · Hi-NRG · Boogie Woogie · Post-Disco · Library Music ·
Metallic Hardcore · Appalachian Folk · Martial Industrial.
**Retired as ownership-adjacent:** Industrial Dance (`ebm.md` self-claims the umbrella) · Aggrotech
(covered by `dark-electro.md`) · Atmospheric Black Metal (`blackgaze-and-post-black-metal.md` +
`atmospheric-metal-and-post-metal.md`) · Beatdown (`beatdown-hardcore.md`).
**New probe false positives:** `Lounge` (43/59 — the "lounge-y" utility adjective) and `Americana` (18/45 —
owned by `alt-country-and-americana.md`).

**Cross-links closed:** `motown.md`, `swing-and-big-band.md`, `vaporwave.md` → the three new files.

**Open (escalating, fourth cycle):** `genres/soul.md` cannot be written from an unattended run — the
protected-file guard matches the basename against `SOUL.md` and refuses without an approver. This cycle it
blocked the Northern Soul cross-link (`soul.md`'s own "Northern Soul" bullet still does not point at
`northern-soul.md`); it also holds `soul.md`-named candidates out of reach. **Suggested fix:** narrow the
guard to match `SOUL.md` exactly, not any `soul.md` basename. Owner: the write-guard maintainer
(Hephaestus/Marvin).

**Also open:** cron job `f606e92fc6ee`'s prompt still names the retired `Genre-Lexicon.md` (44th cycle);
`genres/vaporwave.md` still carries the mis-merged industrial block (flagged 2026-09-29); the corpus-wide
verifier sweep (139 pass / 131 fail, 2026-10-29) is still an unmade author decision.

**Provider note:** Tavily `web_search` reachable; retrieval ran via `curl` → Wikipedia action API, one title
per request, `-o` to file, read back separately. `Mallsoft` has a standalone (concise) article; `Northern
soul` and `Western swing` both returned full-length extracts.
