# 2026-11-07 — Apollo Genre-Lexicon cycle 47

**Decision:** add `genres/piedmont-blues.md`, `genres/slam-death-metal.md` and
`genres/paisley-underground.md` as standalone Genre-DNA profiles (296 → 299 genre files), written directly
to per-slug files (no staging `Genre-Lexicon.md`), rebuild `genres/INDEX.md` from disk, and bump the
parent `reference/INDEX.md` count cell (296 → 299) and date.

**Rationale:** all three are three-or-more-cycle carries with a **clean parent-promise bullet**, and the
batch is deliberately lane-varied (1920s East Coast fingerpicked acoustic blues · mid-tempo breakdown
extreme metal · 1980s California neo-psych/jangle). **Piedmont Blues** resolves the recurring
"Country Blues / Piedmont Blues" compound carry by taking the Piedmont half — `blues.md`'s compound bullet
describes the East Coast fingerpicking school and `delta-blues.md` gives it a clean sibling bullet.
**Slam Death Metal** sits on a clean `brutal-death-metal.md` bullet. **Paisley Underground** sits on a
clean `jangle-pop.md` bullet. Additive and fully reversible.

**Alternatives considered:** **Country Blues** held — `delta-blues.md` treats it as the *rural umbrella*
`blues.md` already anchors, so a profile would near-duplicate the parent (it remains a genuine future
candidate, now with three parent refs). Deferred for lane variety only (clean bullets, none a 3-cycle
carry): Speed Garage, Roots Rock, Rap Metal, Techstep, Murder Ballad, Easycore, Outlaw Americana, NWOBHM,
Drill 'n' Bass. Held as tag-usage only: Boogie Woogie. Held as influence-prose / compound-bullet ownership
calls: Metallic Hardcore, Appalachian Folk, Honky Tonk, Stride, Post-Disco, Hi-NRG, Electric Blues / Modern
Blues, Martial Industrial. Held as exclusion-tag-only and thin: New Age. Probe false positives: **Bassline**
(81f/192r — the *word* "bassline"), plus the owned heads Shoegaze, Post-Rock, Hardstyle, Dark Ambient.
Noted unowned candidate: **Dunedin Sound** (a `jangle-pop.md` bullet, no file).

**Evidence:** fresh corpus probe over all 296 genre files (`cache/scratch/probe-20261107.py`: gap scan +
~110-candidate word-bounded count) with a full hit-context dump (`cache/scratch/ctx-20261107.txt`, 318
lines). Retrieval via `web_extract`: `Piedmont blues` (26,640 chars), `Slam death metal` → redirect to
`Brutal death metal` §Slam (66,525), `Paisley Underground` (54,174) — all three on the first attempt.
Gap-scan rank 1 was owned compound-slug noise again.

**Verification:** pre-flight ALL PASS (description words 224 / 220 / 216; 20 tags × 4 categories; 5 related
bullets). Packaged `verify-genre-lexicon.py --expect "Piedmont Blues,Slam Death Metal,Paisley Underground"
--index genres/INDEX.md` on the 19,625 B assembly → **ALL CHECKS PASS**. Index rebuilt → **299 rows, added
3 / dropped 0**, exactly one `Total:` line, `Total: 299 genre files (2864 KB)`, measured placements
**#217 Paisley Underground · #221 Piedmont Blues · #261 Slam Death Metal**; backup
`genres/INDEX.md.bak-20261107070616`. Cross-file 299 = 299. Parent `reference/INDEX.md` 296 → 299,
date → 2026-11-07. Parent-side cross-links appended in `blues.md`, `delta-blues.md`,
`brutal-death-metal.md`, `jangle-pop.md`.

**Blocker (seventh consecutive cycle):** `genres/soul.md` remains unwritable from an unattended run — the
protected-basename guard matches `SOUL.md`, so `soul.md`'s own "Deep Soul / Southern Soul" bullet still
does not point at `southern-soul.md`. Fix: match `SOUL.md` exactly, not any `soul.md` basename. Owner: the
write-guard maintainer (Hephaestus/Marvin).

**Reversibility:** High — three new files plus index rows; the only edits to existing profiles are four
one-line cross-link appends.

Full record: `~/athenaeum/Codex-Apollo/DECISIONS.md` (2026-11-07 entry) and
`~/athenaeum/Codex-God-Apollo/journal/2026-11-07.md`.
