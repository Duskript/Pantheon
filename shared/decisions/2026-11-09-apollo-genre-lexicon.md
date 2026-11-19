# Apollo — Genre-Lexicon cycle 49 decision (2026-11-09)

**Decision:** add three genre profiles to `knowledge/reference/genres/` — **Outlaw Americana**,
**Drill 'n' Bass** and **Cowpunk** (302 → 305 files) — closing both of the 48th cycle's ranked carries and
the long-flagged Cowpunk carry.

**Why these three.** Each has an unowned parent-promise bullet (the strongest gap signal), and the batch
deliberately varies texture (weary slow Americana · scrappy fast punk-country · high-velocity chopped
electronic breakbeat):
- **Outlaw Americana** — **doubly** bullet-promised: `alt-country-and-americana.md` ("**Outlaw Americana:**
  More tied to outlaw country lineage, baritone storytelling, barroom grit… (see `outlaw-country.md`)") and
  `outlaw-country.md` ("**Outlaw Americana:** The quieter later child — Steve Earle, Lucinda Williams and
  Jason Isbell…"). The 48th cycle's **#1 ranked carry**, taken.
- **Drill 'n' Bass** — **doubly** bullet-promised: `breakcore.md` ("**Drill 'n' Bass:** The IDM-adjacent
  cousin (Squarepusher, µ-Ziq)…") and `idm.md` ("**Drill 'n' Bass:** The high-velocity wing…"), plus
  Key-Influence prose in `breakcore.md` and Rhythmic-Foundation prose in `idm.md`. The 48th cycle's
  **#2 ranked carry**, taken.
- **Cowpunk** — a clean single bullet in `alt-country-and-americana.md` ("**Cowpunk:** Faster, scrappier,
  and more punk-adjacent…"). Held since the **44th** cycle; **taken this cycle** on the
  carried-more-than-twice rule (and a parent bullet is ownership, so the ruling is take, not drop).

**Alternatives considered / held:**
- **Ragtime** (9f/24r) — the cycle's strongest *fresh* find: a genuinely unowned root of the stride /
  early-jazz piano lineage, green-lit by a `ragtime` exclusion tag in
  `piano-rock-and-piano-driven-alternative.md`. Deferred for lane variety only; **ranked #1 next cycle**.
- Also surfaced but deferred: **Appalachian** (8f/17r), **Stride** (7f/12r), **Metallic Hardcore** (5f/5r),
  **Southern Gothic** (3f/5r), plus the clean-bullet carries Speed Garage, Easycore, Roots Rock, Rap Metal,
  Techstep, Dunedin Sound.
- **Country Blues** — held: `blues.md` already anchors the rural umbrella; its own compound bullet is the
  East Coast/Piedmont school, now filed, so a standalone profile near-duplicates the parent.
- **Metallic Hardcore / Martial Industrial / Post-Disco / Hi-NRG / Appalachian Folk / Honky Tonk /
  Stride** — held (influence prose, tag phrase, or compound-bullet ownership calls).
- **Boogie Woogie** held (tag usage only); **New Age** held (exclusion-tag only, thin).
- **Rejected as owned/compound/thin:** Jam Band (exclusion-only), Sludge (`sludge-metal.md`),
  Garage Rock (`garage-rock-and-garage-punk.md`), Emo (compound/tag-phrase flood).
- **Probe false positive of the cycle:** `Bassline` 82f/193r = the *word* "bassline" (utility-noun class).
  Gap-scan rank 1 was owned compound-slug noise again (`chicago-house`, `ambient-house`, `electric-blues`,
  `country-blues`, `indie-pop`, `chillwave`, `industrial-dance`, `screamo`).

**Evidence:** fresh corpus probe over all 302 genre files (`cache/scratch/probe-20261109.py`:
fragment-level variation-bullet gap scan + ~140-candidate word-bounded count), output
`cache/scratch/probe-20261109.txt`. **Provider:** Tavily not attempted; the Wikipedia action API via
`curl -o` + separate reader returned all four anchors — `Americana (music)` (12,965 chars; the AMA's
roots-oriented definition), `Alternative country` (4,654 chars; Uncle Tupelo's *No Depression* 1990 and
Bloodshot's "insurgent country"), `Cowpunk` (12,970 chars; term attested 1979 as "cowboy"+"punk"; Robert
Palmer NYT 1984; X, the Gun Club, Rank and File, Jason and the Scorchers), `Drill 'n' bass` (2,183 chars;
mid-1990s drum-and-bass subgenre by IDM artists; frenzied irregular beats that discouraged dancing; a
light parody of the dance styles that inspired it).

**Verification:** pre-flight checker (`cache/scratch/precheck-20261109.py`) ALL PASS — description words
**238 / 247 / 242** (first drafts measured 196 / 202 / 219 and all three were padded into the 220–250 house
cluster), 20 tags in each of the four Suno categories, 5 related bullets each, 5 sections, exactly one
top-level header per file, no `---` separator, exactly 20 moods with no duplicates, every bullet ending `.`.
Packaged `verify-genre-lexicon.py --expect "Outlaw Americana,Drill 'n' Bass,Cowpunk" --index genres/INDEX.md`
on the 20,365 B assembly (`cache/scratch/assembly-20261109.md`, 3 separators, clean EOF) → **ALL CHECKS
PASS** (incl. "parent index names every live profile"). Index rebuilt from disk (`reindex-20261109.py`) →
**305 rows, added 3 / dropped 0**, casefold order intact, exactly one `Total:` line,
`Total: 305 genre files (2903 KB)`, **measured** placements **#59 Cowpunk · #91 Drill 'n' Bass ·
#220 Outlaw Americana**; backup `genres/INDEX.md.bak-20261109070855`. Cross-file check
(`crosscheck-20261109.py`): 305 live files = 305 rows, 0 missing / 0 orphans. Parent `reference/INDEX.md`
302 → 305, date → 2026-11-09.

**Parent-side cross-links:** one-line additive appends — `alt-country-and-americana.md` (Cowpunk →
`See cowpunk.md.`; Outlaw Americana → `expanded at outlaw-americana.md`), `outlaw-country.md`
(→ `See outlaw-americana.md.`), `breakcore.md` (→ `See drill-n-bass.md.`), `idm.md`
(→ `See drill-n-bass.md.`). No blocked writes this cycle.

**Blocked (ninth consecutive cycle, unchanged):** `genres/soul.md` still refuses a `patch` under the
protected-basename guard (`SOUL.md`), so `soul.md`'s "Deep Soul / Southern Soul" bullet still does not
point at `southern-soul.md`. The guard matches the basename against `SOUL.md`; `soul-jazz.md`,
`psychedelic-soul.md` and `neo-soul-and-neon-soul.md` all write normally. Fix: match `SOUL.md` exactly,
not any `soul.md` basename. Owner: the write-guard maintainer (Hephaestus/Marvin).

**Reversibility:** High — three new files plus index rows; the only edits to existing profiles are five
one-line cross-link appends. No existing profile was rewritten.
