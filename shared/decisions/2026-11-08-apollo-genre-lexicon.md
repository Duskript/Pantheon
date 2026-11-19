# Apollo — Genre-Lexicon cycle 48 decision (2026-11-08)

**Decision:** add three genre profiles to `knowledge/reference/genres/` — **Psychobilly**,
**Murder Ballad** and **NWOBHM** (299 → 302 files) — and close the standing Psychobilly carry.

**Why these three.** Each has an unowned parent-promise bullet (the strongest gap signal) and none is
covered by a close neighbour:
- **Psychobilly** — clean bullet in `rockabilly.md` ("**Psychobilly:** The 1980s British and American
  mutation — rockabilly's slap bass and train beat played at punk velocity…"). Held with a live bullet
  since the 44th cycle, i.e. a chronic selection-slot tax; **taken this cycle** to resolve it.
- **Murder Ballad** — clean bullet in `dark-folk-and-gothic-americana.md` ("**Murder Ballad:** The
  narrative-focused branch centered on crime, guilt, death, betrayal, and consequence."). Tag usage only
  elsewhere (`murder ballad` in that file's Mood tags) = not ownership.
- **NWOBHM** — explicit parent bullet in `speed-metal.md` ("**NWOBHM (the direct parent)**") plus origin
  prose in `metal.md`, `power-metal.md`, `thrash-metal.md`, `melodic-death-metal.md`, `glam-metal.md`.
  The unowned root of the library's entire speed / thrash / power / melodic-death-metal branch.

**Alternatives considered / held:**
- **Outlaw Americana** — doubly bullet-promised (`alt-country-and-americana.md` + `outlaw-country.md`);
  **ranked #1 next cycle**, deferred only for lane variety.
- **Drill 'n' Bass** — doubly bullet-promised (`breakcore.md` + `idm.md`); ranked #2 next cycle.
- **Cowpunk**, **Easycore**, **Speed Garage**, **Roots Rock**, **Rap Metal**, **Techstep**,
  **Dunedin Sound** — clean bullets, deferred for lane variety. Cowpunk held since the 44th cycle —
  flagged to take or drop next cycle.
- **Country Blues** — held: `blues.md` already anchors the rural umbrella; its own compound bullet is the
  East Coast/Piedmont school, now filed, so a standalone profile near-duplicates the parent.
- **Metallic Hardcore / Martial Industrial / Post-Disco / Hi-NRG / Appalachian Folk / Honky Tonk /
  Stride** — held (influence prose, tag phrase, or compound-bullet ownership calls).
- **Boogie Woogie** held (tag usage only); **New Age** held (exclusion-tag only, thin).
- **Probe false positive of the cycle:** `Bassline` 81f/192r = the *word* "bassline" (utility-noun class).
  Gap-scan rank 1 was owned compound-slug noise again (`Electric Blues / Modern Blues`, etc.).

**Evidence:** fresh corpus probe over all 299 genre files (`cache/scratch/probe-20261108.py`:
variation-bullet gap scan + ~185-candidate word-bounded count) with a full hit-context dump
(`cache/scratch/ctx-20261108.txt`) classifying every mention as a Related bullet, tag usage, exclusion tag
or influence prose. **Provider:** Tavily not attempted; the Wikipedia action API via `curl -o` +
separate reader returned all three articles — `Psychobilly` (29,758 chars; Cramps coining from Johnny
Cash's "One Piece at a Time"; the Meteors; Klub Foot; upright slap bass + hollowbody trio; apolitical
horror lyrics), `Murder ballad` (8,820 chars; the event-song definition; Malin/Child ballads;
"Knoxville Girl" ← "The Wexford Girl" ← "The Oxford Girl"; 1950s–60s pop revivals), `New wave of British
heavy metal` (39,813 chars; Geoff Barton / Sounds May 1979; DIY self-produced indies; punk intensity;
Iron Maiden / Def Leppard / Motörhead / Saxon / Diamond Head / Venom / Raven; escapist lyrics).

**Verification:** pre-flight checker (`cache/scratch/precheck-20261108.py`) ALL PASS — description words
**237 / 223 / 243** (first drafts measured 207 / 223 / 215 and two were padded into the house cluster),
20 tags in each of the four Suno categories, 5 related bullets each, 5 sections, exactly one top-level
header per file, no `---` separator, no duplicate moods, every bullet ending `.`. Packaged
`verify-genre-lexicon.py --expect "Psychobilly,Murder Ballad,NWOBHM" --index genres/INDEX.md` on the
19,700 B assembly (`cache/scratch/assembly-20261108.md`, 3 separators) → **ALL CHECKS PASS**. Index
rebuilt from disk (`reindex-20261108.py`) → **302 rows, added 3 / dropped 0**, casefold order intact,
exactly one `Total:` line, `Total: 302 genre files (2883 KB)`, **measured** placements
**#193 Murder Ballad · #217 NWOBHM · #243 Psychobilly**; backup `genres/INDEX.md.bak-20261108070733`.
Cross-file check (`xcheck-20261107.py`): 302 live files = 302 rows, 0 missing / 0 orphans / 0
label-header mismatches. Parent `reference/INDEX.md` 299 → 302, date → 2026-11-08.

**Parent-side cross-links:** one-line additive appends — `rockabilly.md` (→ `See psychobilly.md.`),
`dark-folk-and-gothic-americana.md` (→ `See murder-ballad.md.`), `speed-metal.md` (→ `See nwobhm.md.`).
No blocked writes this cycle.

**Blocked (eighth consecutive cycle, unchanged):** `genres/soul.md` still refuses a `patch` under the
protected-basename guard (`SOUL.md`), so `soul.md`'s "Deep Soul / Southern Soul" bullet still does not
point at `southern-soul.md`. The guard matches the basename against `SOUL.md`; `soul-jazz.md`,
`psychedelic-soul.md` and `neo-soul-and-neon-soul.md` all write normally. Fix: match `SOUL.md` exactly,
not any `soul.md` basename. Owner: the write-guard maintainer (Hephaestus/Marvin).

**Reversibility:** High — three new files plus index rows; the only edits to existing profiles are three
one-line cross-link appends. No existing profile was rewritten.
