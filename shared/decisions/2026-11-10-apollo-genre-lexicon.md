# Apollo — Genre-Lexicon cycle 50 decision (2026-11-10)

**Decision:** add three genre profiles to `knowledge/reference/genres/` — **Ragtime**, **Country Blues** and
**Hi-NRG** (305 → 308 files). Written directly to per-slug files, not to a staging `Genre-Lexicon.md` (absent
by design; the 03:00 `auto-split-refs` cron would consume it and truncate `genres/INDEX.md`). The cron prompt
still names `Genre-Lexicon.md` and remains stale (50th cycle).

**Why these three.** Each is unowned with a real library signal, and the batch deliberately varies era,
instrument and region (1890s–1910s American syncopated piano · pre-war rural American acoustic guitar ·
1977–1990s US/UK/European club dance):
- **Ragtime** — the 49th cycle's **#1 ranked carry**, taken. No parent carries a variation bullet for it (so it
  is unowned, not duplicated), while `jazz.md` and `bebop.md` both name it in Key Influence/Origins and
  `piano-rock-and-piano-driven-alternative.md` lists `ragtime` as an exclusion tag — influence prose + tag
  usage + exclusion, the strongest unowned signal of the last two cycles. It is the direct ancestor of stride,
  novelty piano, honky-tonk, jazz and Piedmont's "ragtime guitar".
- **Country Blues** — the umbrella root of the entire blues lane, now **triply** parent-promised: a clean
  sibling bullet in `delta-blues.md` ("**Country Blues (the regional parent):** The broader rural umbrella…")
  and in `piedmont-blues.md` ("**Country Blues (the rural umbrella):** …"), plus the `blues.md` compound
  "Country Blues / Piedmont Blues" bullet and a `memphis-soul.md` compound bullet. Held four cycles on a
  "near-duplicate of `blues.md`" call; **the hold is now discharged** because all four regional schools (Delta,
  Piedmont, Texas, Memphis) are filed and the umbrella node they sit inside has no file. It has a standalone
  Wikipedia article with three synonyms (folk / rural / downhome blues).
- **Hi-NRG** — the missing 1980s club-dance node. Unowned: the only namesake bullet is "Hi-NRG Italo" in
  `italo-disco.md`, which slugifies to `hi-nrg-italo` (a sub-variant, not the genre); its other appearances are
  Key-Influence prose in `italo-disco.md` and `new-beat.md`. Wikipedia gives it a full article — Moroder's
  sequenced octave bass on Donna Summer's "I Feel Love" (1977) as the founding record, 120–140 BPM,
  four-on-the-floor, staccato hats, machine claps, reverberated diva vocals, and an explicitly *un-funky*
  straight feel.

**Alternatives considered / rejected as owned by a parent variation bullet** (each context-dumped before
ruling): Swing Revival (`swing-and-big-band.md` bullet) · Slow Jam (`quiet-storm.md` bullet) · Rap Metal
(`nu-metal.md` bullet) · Techstep (`neurofunk.md` bullet) · Easycore (`pop-punk.md` + `skate-punk.md` bullets) ·
Bakersfield Sound (`country.md` compound "Bakersfield Sound / Honky-Tonk" bullet) · Dixieland (`jazz.md`
bullet) · Chicha (`cumbia.md` compound bullet) · Martial Industrial (`neofolk.md` + `post-industrial.md`
bullets) · Horror Punk (`psychobilly.md` bullet) · Ranchera (`mariachi.md` bullet) · Bolero
(`samba-cancao.md` bullet) · Tejano (`mariachi.md` + `norteno.md` compound bullets) · Neue Deutsche Welle
(`new-wave.md` bullet) · Roots Rock (`heartland-rock.md` bullet) · Speed Garage (`uk-garage-and-2-step.md`
bullet) · Gypsy Jazz (`chanson.md` + `swing-and-big-band.md` bullets) · Berlin School
(`krautrock-and-kosmische.md` bullet).

**Held with evidence:** **Old-Time** (5f/8r — named only in `bluegrass.md`, `dark-folk-and-gothic-americana.md`
and `western-swing.md` Key-Influence prose; no bullet → now the strongest fresh carry) · **New Age** (18f/20r
but exclusion-tag only) · **Mambo** and **Metallic Hardcore** (influence prose only) · **Honky Tonk**,
**Boogie Woogie**, **Post-Disco**, **Eurodance** (compound bullets, tag usage or exclusion-tag only) ·
**Electric Blues / Modern Blues** (compound-bullet calls).

**Probe false positives of the cycle:** `Bassline` 82f/193r, `Bounce` 29f/49r, `Ballroom` 9f/13r and
`Footwork` 5f/13r — all the *word*, not the genre. Gap-scan rank 1 was owned compound-slug noise again
(`chicago-house`, `ambient-house`, `electric-blues`, `country-blues`, `indie-pop`, `chillwave`,
`industrial-dance`, `screamo`, `gothic-americana`).

**Evidence:** fresh corpus probe over all 305 genre files (`cache/scratch/probe-20261110.py`: fragment-level
variation-bullet gap scan + ~185-candidate word-bounded count + shortlist context dump), output
`cache/scratch/probe-20261110.txt`; two further ownership dumps `cache/scratch/ctx2-20261110.py` and
`cache/scratch/ctx3-20261110.py`. **Provider:** Tavily not attempted; `web_extract` returned all three
Wikipedia articles on the first attempt — `Ragtime` (110,496 clean chars; Joplin / Scott / Lamb, the Sousa
march derivation, 2/4 oom-pah left hand, AABBACCC strain form, the "metric denial" syncopation, the Sting-era
revival), `Country blues` (20,217 chars; folk/rural/downhome synonyms, Lomax's 1941 Stovall Plantation
recording of Muddy Waters, Charters 1959, Delta/Piedmont/Hill country subgenres, 1920s first recordings) and
`Hi-NRG` (64,421 chars; Moroder's "I Feel Love" 1977, 120–140 BPM, "slamming rather than swinging", Ian
Levine's definition, Stock Aitken Waterman, the derivative list).

**Verification:** pre-flight checker (`cache/scratch/precheck-20261110.py`) ALL PASS — description words
**220 / 222 / 234** (Hi-NRG's first draft measured 211 and was padded into the 220–250 house cluster),
20 tags in each of the four Suno categories, 5 related bullets each, 5 sections, exactly one top-level header
per file, no `---` separator, exactly 20 moods with no duplicates, every bullet ending `.`. Packaged
`verify-genre-lexicon.py --expect "Ragtime,Country Blues,Hi-NRG" --index genres/INDEX.md` on the 22,198 B
assembly (`cache/scratch/assembly-20261110.md`, 3 separators, clean EOF) → **ALL CHECKS PASS** (including
"parent index names every live profile"). Index rebuilt from disk (`reindex-20261110.py`) → **308 rows, added
3 / dropped 0**, casefold order intact, exactly one `Total:` line and exactly one table-header line,
`Total: 308 genre files (2924 KB)`, **measured** placements **#59 Country Blues · #150 Hi-NRG · #252
Ragtime**; backup `genres/INDEX.md.bak-20261110070734`. Cross-file check (`crosscheck-20261110.py`):
308 live files = 308 rows, 0 missing / 0 orphans, casefold order verified. Parent `reference/INDEX.md`
305 → 308, date → 2026-11-10.

**Parent-side cross-links:** one-line additive appends closing every bullet parent that could otherwise
re-score as a gap — `delta-blues.md` and `piedmont-blues.md` (→ `See country-blues.md.`), `blues.md`
(→ `See piedmont-blues.md and country-blues.md.`), `memphis-soul.md` (→ `See country-blues.md.`),
`italo-disco.md` (Hi-NRG Italo bullet → `See hi-nrg.md.`). No link was added for Ragtime (no bullet parent —
every reference is influence prose, tag usage or a `piano-rock` exclusion tag) and none for Hi-NRG outside
`italo-disco.md` (its other mentions are influence prose only). No blocked writes this cycle.

**Blocked (tenth consecutive cycle, unchanged):** `genres/soul.md` still refuses a `patch` under the
protected-basename guard (`SOUL.md`), so `soul.md`'s "Deep Soul / Southern Soul" bullet still does not point
at `southern-soul.md`. The guard matches the basename against `SOUL.md`; `soul-jazz.md`,
`psychedelic-soul.md` and `neo-soul-and-neon-soul.md` all write normally. Fix: match `SOUL.md` exactly, not
any `soul.md` basename. Owner: the write-guard maintainer (Hephaestus/Marvin).

**Reversibility:** High — three new files plus index rows; the only edits to existing profiles are five
one-line cross-link appends. No existing profile was rewritten.
