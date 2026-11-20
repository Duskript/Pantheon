# 2026-11-20 — Apollo — Genre-Lexicon cycle 60 (335 → 338)

**Decision:** Expand the curated genre layer with three profiles, written straight into `genres/<slug>.md` (never a staging `Genre-Lexicon.md` — the 03:00 `auto-split-refs` cron consumes any monolith and re-truncates `genres/INDEX.md`).

**Added:** `genres/drone-metal.md` (Drone Metal) · `genres/death-industrial.md` (Death Industrial) · `genres/digicore.md` (Digicore).

**Rationale:** all three are parent-promised with clean, dedicated `## Related Sub-genres` bullets and owned no file — Drone Metal **triply** (`atmospheric-metal-and-post-metal.md`, `drone-music.md`, `noise-sludge.md`), Death Industrial **doubly** (`power-electronics.md`, `martial-industrial.md`), Digicore **doubly** (`emo-rap.md`, `hyperpop.md`). Selected by the parent-promise scan (`cache/scratch/promise-20261120.py`) plus a context-dumped word-bounded probe; the scan's rank-1 top was again the standing artefact pair (compound-slug + parent-as-synonym). Lane- and texture-varied: the stillest extreme of the heavy lane, the ritual dark-noise pole of the post-industrial family, and the DIY internet-pop microgenre.

**Alternatives considered / held:** Pop Soul (held — parent-as-synonym: declarers read "Motown / Pop Soul" and `motown.md` states the Motown sound *is* pop soul) · Jazz Hop (alias of jazz rap) · Hardcore Techno (gabber umbrella) · Industrial Dance (ebm umbrella) · Apocalyptic Folk (neofolk header) · Electric Blues / Modern Blues (compound bullet) · Outrun (owned). Deferred for lane variety with real cases: Crossbreed, Cyber Metal, Atmospheric Prog-Metal, Digital Hardcore, Chillhop, Dreamwave.

**Evidence:** precheck ALL PASS (descriptions 240 / 235 / 222 words; 20 tags × 4 × 3; 20 unique Primary Moods; 10 unique Key Textures; 5 related bullets each). Packaged verifier on the 22,271 B assembly → ALL CHECKS PASS. Index rebuilt → 338 rows, added 3 / dropped 0, `Total: 338 genre files (3147 KB)`, placements #82 Death Industrial · #91 Digicore · #100 Drone Metal. Cross-file 338 = 338, 0 missing / 0 orphans / 0 label mismatches, 0 broken `.md` links. Parent `reference/INDEX.md` 335 → 338, date → 2026-11-20.

**Reversibility:** fully reversible — delete the three new files, restore `genres/INDEX.md.bak-20261120070537`, and revert the seven one-line parent cross-link amendments and the parent-index count.

**Blocker (twentieth consecutive cycle, unchanged):** `genres/soul.md` refuses a `patch` under the protected-basename guard (`SOUL.md`). Fix: match `SOUL.md` exactly, not any `soul.md` basename. Owner: the write-guard maintainer (Hephaestus/Marvin).
