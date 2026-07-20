# Dojo Skill Crystallization — Noise Pattern Catalog

> **Purpose:** Recurring patterns in crystallization candidates that consistently fail the "worth a skill" test. This catalog helps classification agents (both human and LLM) rapidly categorize candidates without re-analyzing the same class of noise each sweep.
>
> **Usage:** When evaluating candidates, first check known noise-pattern groups. If a candidate matches a known pattern, reject with that pattern reference. If a candidate doesn't match any pattern, treat it as novel material (a candidate for crystallization).
>
> **Evolution:** Append new patterns as they are identified. Patterns may be superseded or closed (e.g., "no longer observed after fix") — mark those with a closure date.
>
> **Canonical location:** `~/pantheon/hermes-dojo/references/noise-pattern-catalog.md`
> **Related:** `scripts/context_detect.py` (exit code 3 references this catalog's §Pattern 23)

---

## Pattern 1 — Test Data Flood

**Source:** Test suites writing to the production `~/.hermes/ichor.db`.

**Observation period:** 2026-07-09 → 2026-07-13 (mitigated by fix on 2026-07-13).

**Signal:** `god_name='default'`, `subject` begins with `test_` or `c1_test_`, event IDs are sequential and repetitive.

**Root cause:** `test_ichor_c1_outcome_and_contradiction.py` (in `pr35-gitworktree`) writes directly to the production `ichor.db` for integration testing, creating 32+ entries per day with `importance=50.0`.

**Fix applied 2026-07-13:** `EXCLUDED_SUBJECT_PREFIXES` constant and SQL `NOT (god_name='default' AND (subject LIKE 'test_%' OR subject LIKE 'c1_test_%'))` filter in `skill_crystallization.py`.

**Status:** ✅ **CLOSED** — fix is in production code. Candidates no longer surface this pattern. If test data resurfaces (e.g., new test suite with different prefix), extend the exclusion list.

**Reference:** `references/test-data-flood-filter-2026-07-13.md`

**Rapid classification:** If `god_name='default'` → likely Pattern 1; check if still filtered.

---

## Pattern 2 — Conversational Fragment

**Source:** Single-turn remarks from Thoth conversations that are observations, opinions, or preferences — not workflows.

**Observation period:** Continuous (first observed 2026-07-10).

**Signal:** Single sentence or fragment, no actionable steps, no acceptance criteria, no structural procedure. Often starts with "What", "I think", "That's", "Oh that's".

**Examples:**
- _"The syntax is just details"_ — HubSpot docs observation
- _"Having to do something the slow way when I can already see a faster path"_ — preference statement
- _"[Cybermage] Oh that's not something I would do I always test first"_ — testing culture remark
- _"What you know when to start and when you're done"_ — SOP methodology observation
- _"[Cybermage] What drains energy? ..."_ — personality interview fragment
- _"User preference: 'goal and constraints, I'll handle path'"_ — communication style note
- _"What about for me to do it myself"_ — follow-on economic question

**Root cause:** The `commitment` event type is triggered by any resolved conversational turn — not only task completions. Thoth's conversational format (reflective, opinionated) produces many false positives.

**Rapid classification:** If the raw_text is ≤80 chars and reads like a spoken remark, not a procedure → Pattern 2.

**Crystallization bar to clear:** A conversational fragment must be synthesizable into a ≥5-step workflow that generalizes beyond the specific conversation context.

---

## Pattern 3 — Already-Crystallized Cluster

**Source:** Candidates from sessions that have already been fully mined into skills in a prior sweep.

**Observation period:** Continuous.

**Signal:** The candidate's `id` or `created_at` falls within a session range that was fully dispositioned in a prior batch. Event IDs and subject text match the pattern of a known mined session.

**Common clusters (chronological):**

| Session | Skills Created | Candidates Consumed | Status |
|---------|----------------|---------------------|--------|
| 20260711_013132_bd9992c4 (career-ops + Cybermage) | `job-app-automation-pipeline`, `sop-creation-workflow`, `lead-intake-automation-pipeline`, `evidence-first-professional-history`, `lead-intake-routing-triage` | 321090–321091, 321247, 321278, 321351, 321353, 321356, 321374, 321375, 321463, 321476 | ✅ EXHAUSTED |
| 20260711_105518_ec351a26 (Idaho medical prior-auth) | — (no skill created — Thoth research methodology only) | 321487, 321496, 321497, 321494, 321504, 321545, 321546 | ✅ EXHAUSTED |
| 20260716_110951_483a1115 (comic book appraisal) | — (one-off) | 321453 | ✅ EXHAUSTED |
| 20260717_161518_a19b80 (Apify Store + phone control + honest inference) | `marketplace-listing-publish-readiness`, `honest-inference-without-perception`, `android-phone-control-setup`, `android-phone-agent-control` | 321519–321544, 321602–321607, 321625, 321635, 321659, 321684, 321685, 321711, 321731, 321734, 321736, 321975 | ✅ EXHAUSTED |
| 20260718 (Thoth HubSpot + CRM + history + consultation) | `lead-intake-routing-triage`, `evidence-first-professional-history`, `automation-pipeline-debugging` (mapped) | 323463, 323466, 323476, 323487, 323497, 323510, 323537, 323555, 323569, 323594 | ✅ EXHAUSTED |

**Rapid classification:** If the candidate `id` falls within a range already tagged as `**EXHAUSTED**` (e.g., any ID ≤323594) and the subject is recognizable from prior sweeps → Pattern 3. Check the latest batch notes for the most recent exhaustion boundary.

---

## Pattern 4 — One-Off Domain Appraisal

**Source:** Single-item valuation, pricing, or assessment requests for a specific domain (comics, collectibles, real estate).

**Signal:** Subject references a specific named item (comic book issue, property address, SKU). Raw_text contains pricing assessment or valuation logic. No multi-step workflow — a single query/response exchange.

**Example:** _Alpha Flight #1 comic book pricing assessment_ — a one-off collectible valuation with no reusable workflow pattern.

**Rapid classification:** If the candidate evaluates or prices ONE specific thing with no generalized methodology → Pattern 4.

**Crystallization bar to clear:** A valuation or assessment skill must be synthesizable from ≥3 independent instances of the same domain (e.g., 3 different comic book appraisals → might warrant a "comic book pricing" skill, but 1 instance does not).

---

## Pattern 5 — Commitment-to-Fix (Behavioral Self-Correction)

**Source:** A god (typically Thoth) committing to change their own behavior after a mistake — e.g., fabricating information, making an incorrect assumption.

**Signal:** Subject contains apology language ("I owe you", "Going forward", "I will never"). Event is `commitment` type with importance ≥80. Raw_text describes the correction, not a workflow.

**Examples:**
- _"I owe you an apology — I fabricated an Idaho National Laboratory job entry"_
- _"Going forward I will never add unverified employer names to your CV"_

**Rapid classification:** If the candidate is a god admitting a mistake and committing to a behavioral rule → Pattern 5.

**Crystallization bar:** These can be Crystallized if they suggest a generalizable discipline (e.g., `evidence-first-professional-history` skill). The bar is: does the behavioral rule apply across sessions and operators? If yes, create a skill about the discipline, not about the specific mistake.

---

## Pattern 6 — Digest / Cron Heartbeat

**Source:** System events from the hourly Pantheon digest cron (`pantheon-digest-generation`), not completed user tasks.

**Signal:** Events with `event_type=digest_entry` or subjects referencing "digest", "cron", "heartbeat", "Pantheon Digest". These are lifecycle events, not crystallizable workflows.

**Rapid classification:** If the candidate's session ID starts with a cron timestamp and subject contains "digest" → Pattern 6.

**Note:** As of 2026-07-15, `digest_entry` events were excluded from the scoring pool by script changes that filtered `event_type` to `TASK_COMPLETION_TYPES` only. This pattern should no longer surface.

**Status:** ✅ **CLOSED** — event type filtering prevents surfacing. If `digest_entry` events reappear, re-check the filter.

---

## Pattern 7 — CRM Pipeline Debug Fragment

**Source:** Debugging or diagnostic remarks about CRM lead routing, pipeline stage assignment, or notification delivery.

**Signal:** Raw_text references "pipeline stage", "contact being created", "email notification", "lead routing". Usually a single diagnostic observation, not a complete procedure.

**Examples:**
- _"Is the contact being created but assigned to the wrong pipeline stage?"_
- _"Check if contacts are being created but not assigned to the right pipeline stage"_

**Rapid classification:** If the candidate is a diagnostic question/observation about CRM routing with no procedure → Pattern 7.

**Coverage:** The CRM lead intake and routing workflow is already fully covered by:
- `lead-intake-automation-pipeline` (skill)
- `lead-intake-routing-triage` (skill)
- `automation-pipeline-debugging` (skill)

---

## Pattern 8 — Edge-Case / SOP Methodology Fragment

**Source:** Observations about how to structure SOPs, add edge cases, or define start/end conditions. These are methodological meta-commentary.

**Signal:** Raw_text references "know when to start", "when you're done", "add the edge cases", "what to do when step three fails". Usually one paragraph extracted from a larger SOP-design conversation.

**Examples:**
- _"You know when to start and when you're done. Third, I add the edge cases. What to do when step three fails..."_

**Rapid classification:** If the candidate describes HOW to write an SOP/procedure rather than being the procedure itself → Pattern 8.

**Coverage:** Fully documented in `sop-creation-workflow` skill.

---

## Pattern 9 — Cluster-of-One-Off-Infra (Borderline)

**Source:** Multiple events from a single Thoth session about setting up infrastructure for a specific task (phone control, ADB, AnyDesk, remote access).

**Signal:** Multiple consecutive candidates from the same session, all about infrastructure setup steps. Each individual event looks like a one-off; the cluster forms a coherent workflow.

**Examples:**
- Set of 6 events: `uiautomator2 venv` + `ADB app install` + `AnyDesk cross-phone control` + `Developer Options enable` + `Pushbullet question` + `ClawForge clarification` → Crystallized as `android-phone-control-setup`

**Crystallization bar:** These are the hardest to classify. Each event individually fails the "general 5-15 step workflow" test. But the cluster can form a general skill.

**Test for a cluster:**
1. Do all candidates share the same session ID (same `created_at` range of ~hours)?
2. Would the combined procedure generalize across hardware/context variations?
3. Can the events be ordered into a coherent ≥5-step workflow?
4. Is there at least one other context (different phone model, different OS) where this would apply?

**If YES to all 4:** Crystallize as a cluster (like `android-phone-control-setup`).
**If NO to any:** Reject individually → pattern reverts to Pattern 2 (conversational fragments).

**Known cluster decisions:**

| Session | Events | Verdict | Skill Created |
|---------|--------|---------|---------------|
| 20260717_161518_a19b80 (phone control) | 6 events | ✗ Individual → ✓ Cluster | `android-phone-control-setup` |
| 20260717_161518_a19b80 (phone agent) | 1 follow-on event | ✓ Extended | `android-phone-agent-control` |

---

## Pattern 10 — Pantheon Meta-Discussion

**Source:** Conversation about Pantheon itself — its architecture, value proposition, or multi-agent design.

**Signal:** Subject references "Pantheon", "multi-agent", "god system", "value proposition". Raw_text describes benefits or comparisons, not a work procedure.

**Examples:**
- _"I was spending hours on repetitive tasks — research, content drafting, data extraction — that ..."_

**Rapid classification:** If the candidate explains WHAT Pantheon is or WHY it exists (not HOW to use it for a specific task) → Pattern 10.

**Crystallization bar:** A Pantheon onboarding/overview skill could be created if the meta-discussion suggests a reusable pattern for describing Pantheon to new operators. As of 2026-07-19, no such synthesis has been attempted.

---

## Pattern 11 — Thoth Deep Research Application

**Source:** A candidate that looks like Thoth applying Pattern A (Exploratory Deep Dive) or Pattern B (Implementation Architecture) from `thoth-deep-research` to a specific domain.

**Signal:** Candidate is a `commitment` or `follow_up` entry from a known deep-research session. The raw_text shows research findings (TAM, pricing, market size, competitor analysis) for a specific domain.

**Examples:**
- Idaho medical prior-authorization research (session 20260711_105518_ec351a26)
- Apify Store competitive pricing snapshot (session 20260708_054708_eedd27)

**Rapid classification:** If the candidate is a domain-specific research output (not a new research methodology) → Pattern 11.

**Coverage:** `thoth-deep-research` skill already documents Patterns A, B, and C. To create a new skill from a research-applied candidate, you must show the candidate introduces a **new research methodology** not covered by Patterns A–C.

---

## Pattern 12 — Job App Automation Substep

**Source:** Individual events from the career-ops/job-application pipeline that reference a specific dashboard tab, button, or feature.

**Signal:** Subject references "Dashboard", "Evaluations", "CV", "cover letter", "Job Listings", "View Details". These are feature mentions within the larger `job-app-automation-pipeline` workflow.

**Examples:**
- _"Dashboard tabs: Job Listings + Evaluations"_
- _"'View Details' secondary link on job cards"_
- _"Dashboard Evaluations tab w/ CV+cover letter downloads"_

**Rapid classification:** If the candidate is a single feature mention within the job-app pipeline → Pattern 12.

**Coverage:** Full pipeline documented in `job-app-automation-pipeline` skill.

---

## Pattern 13 — Commitment on a Non-Skill Topic

**Source:** A god committing to produce a specific deliverable (document, artifact, task completion) that is an isolated output, not a repeatable process.

**Signal:** The raw_text describes a specific deliverable and a commitment to complete it. The deliverable is a one-off artifact for a specific context.

**Examples:**
- _"Here's the summary: ## Social Sparrow — Systems & Automation Assistant ..."_ (a job application summary entry)

**Rapid classification:** If the commitment is "I will produce document X" and X is context-specific (not a template/methodology/named workflow) → Pattern 13.

**Crystallization bar:** A skill for "produce document X" could be justified if X is a reusable template (e.g., "job cover letter template"), but a specific filled-in document is not a pattern.

---

## Library Improvement History

| Date | Improvement | Pattern(s) Affected |
|------|-------------|---------------------|
| 2026-07-11 | `context_detect.py` divergence heuristic (Pattern 23) | Equilibrium detection |
| 2026-07-13 | `skill_crystallization.py` test-data filter (EXCLUDED_SUBJECT_PREFIXES) | Pattern 1 |
| 2026-07-19 | This catalog created | All patterns (reference) |

## Future Work

- **Pattern 14 (if observed):** Real estate property valuation — if a second domain-appraisal session with a different property type surfaces, it may warrant a "domain appraisal" catch-all pattern or its own skill.
- **Cluster detection automation:** Consider a script that groups candidates by session ID and proposes cluster crystallizations (Pattern 9), reducing manual cluster-vs-fragment judgment calls.
- **Session exhaustion tagging:** Add a machine-readable tag (`session_status: exhausted`) to batch notes so automated tooling can skip Pattern 3 candidates without reading individual batch files.
