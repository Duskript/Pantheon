# 2026-09-14 — Marvin: Dojo sweep #20 decisions

**Decision 1 — treat a cohort of fragments as `SKIP_FRAGMENT_OF_EXISTING_SKILL_DOCUMENT`
when they verbatim-match an existing skill's own document.**
Rationale: all 10 candidates `2341499-2341508` are 160-170-char windows into the hub skill
`pantheon/github-tech-debt-scanner`'s `SKILL.md` (17,990 B); a whitespace-normalized
substring match scored 10/10 and a negative control found no other skill carrying the
marker `todo/no-issue-ref`. Alternatives considered: per-fragment fragment-only SKIP
(slower, ten judgments, no attribution) or creating a sibling skill from the document
(duplicates an existing umbrella). Evidence: `fragment_provenance` in the run artifact.
Reversibility: the verdict class is additive; a later sweep may reclassify.

**Decision 2 — claim coverage on a hub/symlinked skill, do not patch it.**
Rationale: `pantheon/github-tech-debt-scanner` resolves through
`~/.hermes/profiles/marvin/skills/pantheon/...` into `~/.hermes/skills/...`, i.e. the
shared hub store. Coverage is real (the file is present, not dangling) but the skill is
externally owned, and its own fragments contain no new information to patch with.
Alternatives: patch the hub skill (violates the protected-skill boundary). Reversible.

**Decision 3 — append one correction row for the missing `artifact_type` tag; do not
rewrite the sweep summary.**
Rationale: the sweep's summary carried `artifact_type: "skill_crystallization_run"`, so
`verify_frozen_pool_replay.py::tail_summary_run_ids()` could not see it and anchored its
ledger-tail checks on the 2026-09-13T192000Z correction. Both canonical validators had
passed, proving a row can satisfy one contract and fail another. The correction carries
the required tag, its own run identity, `correction_of`, `correction_of_line: 2194`, and
`correction_sequence: 1`; the original rows are preserved. Post-correction gate: 10/11,
all anchoring checks PASS. Reversible by a further correction; history is append-only.

**Decision 4 — do NOT modify `verify_frozen_pool_replay.py` this sweep; defer the
tie-order tolerance question to a foreground maintainer.**
Rationale: the cohort's ten rows share importance 80.0 *and* `created_at 11:09:55`, so the
finder's ranking key is not a total order; `derive_cohort()` returns the same IDs reversed,
so the gate reports `DISTINCT POOL` (exit 1) for an identical pool. Exit 1 is the fail-safe
branch (no false replay verdict), but it is a false negative that would authorise a
duplicate sweep. Rewriting a pinned anti-drift instrument mid-sweep was judged riskier than
documenting it. Alternatives: multiset comparison inside the gate (needs a maintainer
call), or a `--allow-tie-order` flag. Evidence:
`references/2026-09-14-fragment-pool-tie-order-and-summary-tagging.md §3b`.

**Decision 5 — pointer patch to `hermes-dojo-skill-crystallization/SKILL.md` deferred.**
Rationale: SKILL.md is 99,844 B; the pointer edit would make it 100,177, over the 100,000
character hard limit (`skill_manage` rejected the patch with exactly that message). New
learning landed as a reference file instead. Alternatives: trim canonical rules to make
room (rejected — those rules are load-bearing). Reversible by a foreground maintainer who
splits SKILL.md.
