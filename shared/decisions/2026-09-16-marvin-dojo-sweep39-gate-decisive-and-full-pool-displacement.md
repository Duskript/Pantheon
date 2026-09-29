# 2026-09-16 — Marvin: Dojo sweep #39 decisions

Run: `skill-crystallization-20260916T070200Z-zero-create-whole-session-skill-document-reingest-fragment-pool`
(marvin profile, 07:02:19Z). Zero-create: 10 evaluated, 10 SKIP, 0 created, 0 patched.

**Decision 1 — classify a whole pool as `SKIP_FRAGMENT_OF_EXISTING_SKILL_DOCUMENT` when the
*entire source session* is a re-ingest of one document.**
Rationale: all ten candidates come from ONE session, `cron_cfb065b056ac_20260916_000043` (304 rows,
33 s), and **302/304** of that session's rows are whitespace-normalized verbatim substrings of one
file — `pantheon/pantheon-operations/SKILL.md` (99,992 chars, hub-owned, reached via a symlink). The
remaining 2 rows are verbatim from a **second** document (a Hades-nightly pantheon-operations report
in `~/pantheon/shared/decisions/konan/`), so **304/304 rows are fragments of a document** and the
session is a re-ingest of documents, not a task. All ten candidates share one class rather than
needing ten classifications. Alternatives considered: per-candidate classification
(correct but wasteful — 10 coverage probes instead of 1) or promoting the document's own guidance
lines (e.g. its "double-convert before speaking" time rule) into a new skill (duplicates a live
umbrella). Evidence: `fragment_provenance.session_verbatim_ratio` in the run artifact.
Reversibility: the class is additive; a later sweep may reclassify. Landed as
`references/2026-09-14-triple-class-fragment-cohort-markers.md` §7.

**Decision 2 — claim coverage on the hub-owned document; do not patch it.**
Rationale: the profile path is a symlink into the shared hub store, so there is no profile-local copy
to edit, and the document's content is correct — nothing needs changing. Same boundary as the
2026-09-14 sweep-#20 decision 2. Reversible.

**Decision 3 — record the forecast wording correction: "can take the tenth slot" was wrong; at a
full pool a same-band arrival takes EVERY slot.**
Rationale: the cap term recorded at #37/#38 said an arrival at `importance >= 60` from any job "can
take the tenth slot". It went untested for eleven sweeps, then the whole 10-slot pool was replaced by
one foreign delayed-ingest batch (`cron_cfb065b056ac`, ~6 h lag). The arrival sat in the cohort's own
top band (80.0), so `importance DESC` collapsed onto `created_at DESC` and the newest batch took all
ten. The displaced rows are still present and `active` with future expiries, so this is displacement,
not expiry. A tenth-slot forecast is valid only while the arrival's band is BELOW the pool's top
band. Evidence: `pool_classification.displacement_mode` + `forecast_result`. Reversible.

**Decision 4 — do NOT touch `verify_frozen_pool_replay.py`, even though the fourteen-sweep
exit-code/verdict divergence just ended.**
Rationale: the divergence ended because this cohort is single-band `[80.0]`, so the structurally
unreachable band check passes and exit 1 is decisive again. The check is unchanged and will diverge
again on the next multi-band cohort. Patching a pinned anti-drift instrument in a run that depends on
its verdict is self-serving; the tolerance decision stays OPEN for a foreground maintainer (standing
deferral since sweep #24). Evidence: `replay_gate` + `divergence_streak` in the artifact.

**Decision 5 — run the pinned roll-off in the same pass, with `--date 2026-09-16b`.**
Rationale: the #39 head sync left the run-state skill at 91,374 chars — 8,626 headroom, under one
more sync — so the next curator patch would have been refused. `rolloff_state.py` correctly REFUSED
(exit 3) with the default date stamp because roll-off 3 already owns
`references/run-state-archive-2026-09-16.md`; re-running with `--date 2026-09-16b` removed the
sweep-#28/#27 sections (12,307 chars) to 79,067 chars / 20,933 headroom, archiving them byte-exact
first. Alternatives: skip the roll-off and let #40 fail (rejected — the doc pins this recipe).
Reversible; archive preserved.
