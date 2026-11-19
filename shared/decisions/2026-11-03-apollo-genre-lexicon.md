# Apollo — Genre-Lexicon decisions/blockers, 2026-11-03

**Cycle:** 43rd stand-alone. **Result:** 284 → **287** genre files.

**Added:** `genres/memphis-soul.md` · `genres/miami-bass.md` · `genres/dark-electro.md` (all written direct to
per-slug files; no staging monolith). Packaged verifier on the 20,915 B temp assembly → **ALL CHECKS PASS**.
`genres/INDEX.md` rebuilt from disk → 287 rows, added 3 / dropped 0, one `Total:` line,
`Total: 287 genre files (2786 KB)`, placements #177 / #180 / #68. Parent `reference/INDEX.md` 284 → 287,
date → 2026-11-03. Precheck description words 228 / 241 / 235; 20 tags × 4 categories × 3 profiles.

**Selection, in one line:** **Memphis Soul** is **triply** parent-promised (`philly-soul.md`, `soul.md`,
`motown.md`) and closes the 42nd cycle's held item; **Miami Bass** was held three cycles and is taken on the
carried-more-than-twice rule (`crunk.md`: "**Miami Bass:** The direct parent", plus five prose parents);
**Dark Electro** is doubly bullet-promised (`electro-industrial.md`, `ebm.md`) and listed in
`post-industrial.md`'s offshoot taxonomy. Lane-varied on purpose: Stax gospel-soul · Florida 808 electro-rap ·
European gothic machine club.

**Held:** Northern Soul (doubly promised — the next cycle's carried #1; held only for lane variety) ·
Cybergrind · Country Blues / Piedmont Blues · Slam Death Metal · Western Swing · Jump Blues · Paisley
Underground · Cowpunk · Psychobilly · Mallsoft · Future Funk · Aggrotech · Tech House · Progressive House ·
Chopped and Screwed · Atmospheric Black Metal · Industrial Dance (self-claimed umbrella in `ebm.md`).
**Retired as owned:** Roots Reggae, Ragga (4th cycle), Boom Bap, Americana, Hair Metal, Country Pop, New Age,
Blue-Eyed Soul, Exotica / Space-Age Pop, Tejano, Post-Punk Revival.
**New probe false positives:** `crossover` (78 files / 119 mentions — the plain word) and `Rave` (26/104 — a
scene term, not a genre).

**Cross-links closed:** `philly-soul.md`, `motown.md` → `memphis-soul.md`; `crunk.md` → `miami-bass.md`;
`electro-industrial.md`, `ebm.md` → `dark-electro.md`.

**Open (escalating, third cycle):** `genres/soul.md` cannot be written from an unattended run — the
protected-file guard matches the basename against `SOUL.md` and refuses without an approver. This cycle it
blocked the Memphis Soul cross-link; it also holds Northern Soul and Memphis Soul out of reach as candidates,
and the older `soul.md` → `philly-soul.md` link is still missing. **Suggested fix:** narrow the guard to match
`SOUL.md` exactly, not any `soul.md` basename. Owner: the write-guard maintainer (Hephaestus/Marvin).

**Also open:** cron job `f606e92fc6ee`'s prompt still names the retired `Genre-Lexicon.md` (43rd cycle);
`genres/vaporwave.md` still carries the mis-merged industrial block (flagged 2026-09-29); the corpus-wide
verifier sweep (139 pass / 131 fail, 2026-10-29) is still an unmade author decision.

**Provider note:** Tavily `web_search` reachable; retrieval ran via `curl` → Wikipedia action API (one title
per request, `-o` to file, read back separately). `Dark electro` redirects to `Electro-industrial` §Dark
electro — the real detail lives in the parent article's Derivatives section.
