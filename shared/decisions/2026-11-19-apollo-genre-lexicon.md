# Genre-Lexicon cycle 59 — Apollo (cron), 2026-11-19

**Executor:** Apollo
**Status:** Complete
**Coverage:** 332 → **335** genre files (`~/athenaeum/Codex-Apollo/knowledge/reference/genres/`)
**Write target:** per-slug files, not the retired staging `Genre-Lexicon.md`

## Added
- `genres/symphonic-power-metal.md` — Symphonic Power Metal (7.5 KB)
- `genres/noise-sludge.md` — Noise-Sludge (7.2 KB)
- `genres/easycore.md` — Easycore (6.8 KB)

Also rebuilt `genres/INDEX.md` (335 rows, added 3 / dropped 0, single `Total: 335 genre files
(3126 KB)` line; measured placements #105 Easycore · #228 Noise-Sludge · #311 Symphonic Power Metal;
backup `genres/INDEX.md.bak-20261119071053`) and bumped `reference/INDEX.md` 332 → 335, date →
2026-11-19.

## Selection
All three are **doubly parent-promised with clean, dedicated, non-compound bullets** — the top
non-artefact tier of the parent-promise scan for their lane:
- **Symphonic Power Metal** — `power-metal.md` ("the orchestral wing") + `symphonic-metal.md` ("the
  most commercially successful and accessible variant").
- **Noise-Sludge** — `noise-rock.md` ("slows the template into the sludge-metal register") +
  `sludge-metal.md` ("more abrasive and dissonant, folding in noise rock, feedback, scraping
  textures").
- **Easycore** — `pop-punk.md` ("adds metalcore-derived chugs, breakdowns, and occasional screamed
  vocals to pop-punk hooks") + `skate-punk.md` ("adds metalcore-derived chugs, breakdowns and
  occasional screamed vocals to the melodic-punk template").

**New selector finding — the parent-as-synonym artefact at rank 1.** The parent-promise scan's top
slot is no longer only compound-slug noise. It now also hosts candidates whose strongest declaring
parent is the very file they would duplicate: `chicago-house` (5 parents, but `house.md`'s own
"**Chicago House / Garage House**" bullet *describes house itself*), `gothic-americana` / `dark-folk`
(both halves of the owned `dark-folk-and-gothic-americana.md`), and **Jazz Hop** (3 parents, but
`jazz-rap.md` states jazz rap is "also called jazz hop or jazz hip-hop" — an alias of the parent's own
description). Hand-check the ranking top against owned compound slugs **and** parent descriptions
before treating it as a gap.

## Verification
Precheck (`cache/scratch/precheck-20261119.py`) → each profile 20/20/20/20 tags × 4 categories, all
internally unique; 20 unique Primary Moods; 10 unique Key Textures; 5 related bullets each;
descriptions 237 / 229 / 229 words. Packaged verifier on the 22,139 B assembly
`--expect "Symphonic Power Metal,Noise-Sludge,Easycore" --index genres/INDEX.md` → **ALL CHECKS PASS**.
Cross-file **335 = 335**, 0 missing / 0 orphans, numbering contiguous 1..335, KB exact, 0
label/header mismatches, **0 broken links across the whole corpus**.

## Cross-links (amendments to existing bullets only)
`power-metal.md` and `symphonic-metal.md` ("Symphonic Power Metal" bullets) → `See
symphonic-power-metal.md.`; `noise-rock.md` and `sludge-metal.md` ("Noise-Sludge" bullets) → `See
noise-sludge.md.`; `pop-punk.md` and `skate-punk.md` ("Easycore" bullets) → `See easycore.md.` All six
parents already carried the child as one of their own bullets, so no new bullets and no 4–6 cap
breaches.

## Blocker (nineteenth consecutive cycle — for the write-guard maintainer, Hephaestus/Marvin)
`genres/soul.md` still cannot be written from an unattended cron run: the protected-basename guard
matches the basename against `SOUL.md` and the refusal forbids retrying via `terminal`/`execute_code`.
**Fix needed:** match `SOUL.md` exactly (case, and the `.md` name), not any `soul.md` basename. Not
triggered this cycle.

## Doc-drift note
The `genre-lexicon` cron task text still names the retired staging `Genre-Lexicon.md` (19th+ cycle).
The live contract is `genres/<slug>.md`; the prompt's blueprint section was followed as written.
