# Pantheon Phase 2 — Metric Contract

**Status:** DRAFT v2 for Thoth's review. Not implemented. No evaluator built on it.
**Author:** Hermes · **Date:** 2026-09-23 · **Plan ref:** `report-part2.md` Phase 2
**Ruling applied:** outcome signal swapped off the mistake ledger; trust separation scheduled inside
Phase 2 as the T2/T3 gate.

## Revision history

**v2** corrects three errors in v1, all found by Thoth against the live tree:

1. **Rate was wrong by ~20×.** v1 said "24.7 batches/day". That divided by the *window* (7 days)
   instead of the *observed span* (8.63 h) — **a rate without its denominator, in the document about a
   missing denominator.** Measured: **21.2 batches/hour → 509/day.**
2. **Timer figure was wrong by 10×.** v1 said "the ~720/day the timer implies". `OnCalendar=*:0/20`
   is **72 ticks/day**.
3. **The capacity constraint is deleted.** It was an artifact of (1) and (2). Runs are not being
   skipped: 2.78 runs/hour against 3 ticks/hour = **92.7% of ticks run**, 7.6 batches/run. Throughput
   is healthy at ~9,928 events/day ≈ **3.5× intake**.

Consequence: **the plan is ~20× cheaper than v1 claimed.** n=200 paired is **0.39 days**, not 8.1.

---

## 0. Taxonomy: four failure classes, and the worst one is new

v1 mis-classified the Dojo as "never wired". It was wired — it ran three times in 166 seconds on
2026-07-20 and stopped. That is a distinct class:

| # | class | example | signature | guard |
|---|---|---|---|---|
| 1 | **green-but-wrong** | clawforge `SKIPPED` + exit 0 | exit code clean, work absent | assert the *effect*, not the exit |
| 2 | **silent no-op** | forge marker already present | nothing written, nothing logged | log the no-op explicitly |
| 3 | **never wired** | — | no number at all | absence is visible |
| 4 | **stale-but-plausible** | Dojo `metrics.json` | **a number that is not obviously wrong; only the timestamp gives it away** | **freshness assertion** |

**Class 4 is the worst because the report looks alive.** Classes 1–3 all present something
*detectably* wrong or absent; class 4 presents a confident number that stopped being true 65 days ago
and keeps being printed. The guard is not more instrumentation — it is a **freshness assertion on
every metric the evaluator reports**: a declared `max_age`, and **hard failure, not a warning**, when
it is exceeded. This is also how the 103-day-stale Ichor Forge report surfaced this morning.

## 1. What this contract measures

**Outcome:** L2 knowledge-graph extraction **yield per event** — `(entities + relationships)` emitted
per input event, over a batch.

**Why:** it is the only candidate with real volume, a parseable per-observation value, and a direct
causal link to a harness change (extraction prompt, batch size, provider/model, retry policy,
pre-filter).

**What it is NOT:** a measure of quality. Yield is a **proxy** and is trivially gameable — see §6.

## 2. Prerequisite: persist the denominator — **one column, not a pipeline**

**v1 overstated the fix size.** Yield-per-*batch* is already recoverable: the prose in
`extraction_log.source_text` is parseable (`'L2 pass: 5 entities, 4 relationships (provisional=True)'`)
and v1 parsed it (n=2,172). What is genuinely missing is **events consumed per batch** — the
denominator:

```
PRAGMA table_info(extraction_log)
  id, entity_id, relationship_id, fact_id, method, source_text,
  source_session_id, confidence, created_at
  has batch_size / events: False
  of 2,172 'L2 pass' rows, entity_id NOT NULL: 0        <- the FK columns are dead
```

**The prerequisite is therefore one column** (`events_in_batch`, plus a `writer` id so the
multi-writer ambiguity below is resolvable), not a new metric pipeline. That is a small change and it
should be the first work item — not a blocker to be scheduled around.

**Multi-writer ambiguity, confirmed:** 2,172 DB rows vs 183 journal batches is a **12× ratio**, so
`extraction_log` is unambiguously written by more than the drainer. The two sources also disagree on
magnitude — DB mean yield/batch **45.5** (n=2,172) vs journal **26.6** (n=183). **Any metric built on
the unqualified `extraction_log` is measuring at least two different things.** Hence the `writer`
column.

### 2.1 Two further instrument defects, found while measuring

**44 zero-yield batches — 2.0% of 2,182 parseable rows.** This is the measurable form of the #155
hazard: ~**880 events retired from the cursor with no extraction** (44 × ~20 events). Small, but it is
the concrete number behind "a zero-yield batch destroys events," and it is already identifiable, so it
costs nothing to watch. **It is a probe, not a powered test** — 44 observations cannot carry a
200-item claim and must not be written up as one.

**`provisional` is degenerate in the prose, by construction.** The log text reads
`provisional=True` in **2,181 of 2,182** rows (99.95% on one value). But the *column* carries real
information:

```
entities.provisional      : {0: 22,175, 1: 353}   ->  1.6% provisional
relationships.provisional : {0: 31,818, 1: 353}   ->  1.1% provisional
```

The prose records the state **at write time** (always `True`), and `finalize` later flips the column.
So **anything filtering on the prose field is filtering on a constant** — query the column, not the
text. 353 rows remain un-finalised, which is the number worth watching.

**A related trap in the mistake ledger:** a `recorded` event keeps its *original* `state` forever
(append-only by design), so reading `state` off the raw rows shows `open` for all 8 while the folded
`stats` correctly reports `{learned: 5, open: 3}`. **Only the fold is authoritative** — the raw field
is a historical artifact, not current state. Anything reading the raw rows reports a stale state.

**`importance` is degenerate in two lanes, and NOT in a third.** The differentiated version, which is
the defensible claim:

| table | n | distinct values | top value | share | degenerate? |
|---|---|---|---|---|---|
| `cold_events` | 77,675 | **32** | exactly `60.0` | 59.5% | **yes** |
| `warm_entities` | 192,980 | **72** | exactly `50.0` | 48.3% | **yes** |
| `ichor_cold_storage` | 2,619 | 53 | `39.505248627…` | 42.7% | partly |
| `ichor_events` | 86,230 | **288** | `62.0` | 14.2% | **no** |

So `importance` is degenerate in the **entity and cold-event lanes** — a single round number carries
48–60% of rows — but **not** in `ichor_events`, which has 288 distinct values. The top values being
exact round numbers (`50.0`, `60.0`) is what makes them read as **seeded defaults rather than measured
scores**, which is the actionable part: a metric keyed on `importance` in those two lanes is keyed on
a constant, and in `ichor_events` it is not.

**Correction to a figure used earlier in this work:** `importance` was not 88% degenerate. 88% is the
**logic-gate block rate** from `ichor-forge-improvement-report-2026-06-17.md:27` — a different finding
about a different subsystem, which was fused with the importance observation and reported as one
statistic. Nothing measured 88% importance. The table above supersedes that.

## 3. Measured baseline (corrected)

```
complete per-batch records  : 183      all dated 2026-09-23
observed span               : 8.63 h   (00:04:39 -> 08:42:33)
rate                        : 21.2 batches/hour -> 509 batches/day
peak (06-08h)               : 30.0 batches/hour
runs                        : 24  = 2.78/hour vs 3 ticks/hour -> 92.7% of ticks ran
batches per run             : 7.6
events processed            : 3,570 / 8.63 h -> 9,928 events/day = 3.5x the 2,856/day arrivals
YIELD PER EVENT             : mean 1.371  sd 0.817  median 1.300  CV 0.60
batch sizes present         : [10, 20]   (adaptive halving is live)
zero-yield batches          : 0
```

**Cross-check:** an independent derivation this morning put the drainer at 3.7× intake; this run
measures 3.5×. Consistent, from separate data.

## 4. Unit of observation and pairing

- **Unit:** one extraction batch over a fixed corpus slice.
- **Design: paired** — the same slice extracted under baseline and candidate, so slice difficulty
  cancels. Unpaired comparison across different slices confounds the candidate with corpus drift,
  which is large here (CV 0.60).
- **Buy pairing before buying n.** At CV 0.60 the metric is noisy; a same-event-set replay is the
  variance fix and it halves the MDE at fixed n (§5). Increasing n is the expensive lever.
- **Fixed slice:** drawn from the already-extracted corpus (≈77.6K `cold_events`) so slices are
  stable and re-runnable. The OOD vault is drawn from the never-extracted remainder.
- **Stratification:** by `batch_size` (10 vs 20 — the largest known driver of yield), by source lane,
  and by event class.

## 5. Power: MDE at 2σ, re-priced at the corrected rate

`MDE = 2·sd/√n` (unpaired) and `2·(0.5·sd)/√n` (paired, sd_diff ≈ half of sd):

| n | unpaired MDE | % mean | paired MDE | % mean | **days (paired)** |
|---|---|---|---|---|---|
| 50 | 0.231 | 16.9% | 0.116 | 8.4% | **0.10** |
| 100 | 0.163 | 11.9% | 0.082 | 6.0% | **0.20** |
| **200** | 0.116 | 8.4% | 0.058 | **4.2%** | **0.39** |
| 400 | 0.082 | 6.0% | 0.041 | 3.0% | **0.79** |
| 1000 | 0.052 | 3.8% | 0.026 | 1.9% | **1.96** |

**Acceptance:** a candidate must move yield/event by **≥4.2%** (n=200 paired, **0.39 days**) to clear
2σ. Below that, report **inconclusive — never "no effect."**

**The threshold is set from the decision, not from the data.** The question is not "what can we
detect" but "what yield change would change what we *do*?" If nothing below 5% would ever change an
action, 4.2% is sufficient and this is closed. If a 2% change matters, the answer is **still not
"more n"** — it is better pairing, which costs 1.96 days even at n=1000.

**This is Thoth's original point, quantified:** at the mistake ledger's **n=5** the same test detects
only a **27%** change — nothing that would ever really happen.

## 6. Goodhart guards

1. **Yield is gameable** (split entities, emit more per event). It is never a sole criterion.
2. **Precision co-criterion — as a decision rule, with BOTH conditions:**

   **Precision is PRIMARY iff the vault carries ≥200 labels from a source INDEPENDENT of the extractor
   under test.** The independence condition is the binding one, not the count:

   - **≥200 independent labels → precision is PRIMARY, yield secondary.** Precision is the objective
     that cannot be gamed.
   - **Labels from a judge sharing a backbone with the extractor → do NOT take this arm.** That
     measures self-agreement, and precision-primary is then exactly as gameable as yield.
   - **Otherwise → yield-primary is defensible only with both:**
     (a) the golden set **frozen and content-hashed before the first experiment** — without the hash,
     a yield win can be manufactured by relabelling, and "precision non-inferiority" becomes
     undetectably gameable;
     (b) a **pre-registered non-inferiority margin**, declared before the run, not chosen after.

   A procedural constraint (label volume) must not silently become the objective. Nor may a
   *shared-backbone judge* masquerade as an independent one — that is the failure mode that would make
   precision-primary look principled while measuring the extractor against itself.

   **Cost, and whose decision it is:** a judge from a **different model family** than the extractor
   reaches the independent-label bar cheaply. Human labelling of 200 items is ≈**7 hours of Konan's
   time** — bounded and real, but **his decision, not ours**. It is a cost to him, and it is not ours
   to assign.
3. **Tool-gate block rate is out of scope** (plan constraint #6) — a policy outcome, not capability.
4. **No metric without its denominator.** Every reported rate carries `n` and its strata, or prints
   `n/a — no denominator`.
5. **Freshness assertion (§0 class 4).** Every reported metric declares `max_age` and **fails hard**
   past it. A metric that cannot state when it was last written is not reported.
6. **Pre-registration.** Threshold, n, strata, golden-set hash, and decision rule are frozen before a
   candidate runs. Moving any of them after seeing the result voids the result.

## 7. OOD vault and judge

- **Vault:** write-only from the harness side; **exactly one reader — the eval cron.** The proposer has
  **no read path** to it (plan constraint #8). Drawn from the never-extracted remainder.
- **Judge:** pinned by content hash — model, version, prompt, temperature 0, `max_tokens`. Any change
  to the judge is itself a ledgered harness edit under Phase 1's rules, so drift is versioned rather
  than silent. Judge-drift audit: <2pp across two cycles on a fixed golden set.
- The judge must **not** run the live edited harness (constraint #8) — circular and self-fulfilling.

## 8. Explicitly EXCLUDED: Dojo metrics

**Not "pending" — excluded.** A pending metric is an invitation for the evaluator to start reporting
the stale number, which is precisely what happened for 65 days. Exclusion is deliberate.

**Evidence, with the exact path:** `~/.hermes/profiles/marvin/skills/hermes-dojo/data/metrics.json`
— 1,780 B, a list of **3 entries, all identical** (`sessions_analyzed: 32`, `total_tool_calls: 747`,
`overall_success_rate: 90.0`), timestamps **1784542266.5 / 1784542410.3 / 1784542432.0** — three
writes inside ~166 seconds on 2026-07-20, then 65 days of silence. Every Dojo DB is 0 bytes or
all-zero tables.

**Two defects, neither an evaluator deliverable:**
1. The writer stopped after 166 seconds. Reviving it is a writer fix, filed separately.
2. **It lives inside one god's profile** (`profiles/marvin/skills/...`), so the Dojo's report is **not
   fleet-visible at all.** Separate defect.

## 9. Falsifiers

- Precision floor fails while yield rises → metric is being gamed; suspend.
- Judge drift ≥2pp on the golden set between cycles → not comparable across time.
- Any observation missing its denominator → excluded, and the exclusion is **recorded**, not silent.
- Any reported metric exceeding its `max_age` → hard failure, no number emitted.
- Corpus drift exceeding the MDE → re-draw the replay set; a "win" that is corpus drift is not a win.

## 10. Trust separation (the T2/T3 gate — scheduled here)

A **Phase 2 deliverable and the gate on T2/T3 auto-apply.** Not implemented. Required: the agent has
**no write path** to the ledger, the version store, or guardrail config; symlinks resolved before
keying (done, `61293d4`); no per-profile sandbox gaps. **T2/T3 auto-apply stays off until this lands.**

## 11. Resolved / open

**Resolved by Thoth's review:** Q2 (capacity) was a measurement error in v1 §4 — deleted, not filed.
Q4 — Dojo excluded, not pending (§8). Q1 — replaced by the decision rule in §6.2. Q3 — threshold set
from operational significance; buy pairing, not n (§5).

**v2.1 amendment — the §6.2 arm needs LABEL INDEPENDENCE, not just ≥200.** Thoth's correction, and it
is the binding condition: labels from a judge sharing a backbone with the extractor measure
self-agreement, and precision-primary is then exactly as gameable as yield. Full rule in §6.2.

**Still open — one question, and it changes the design rather than the numbers:**

1. **Can the vault carry ≥200 labels from a source INDEPENDENT of the extractor under test?** Candidate
   volume is not the constraint (≈46K unprocessed events, ~500 batches/day). **Labelling is.** A judge
   from a *different model family* than the extractor reaches the bar cheaply. Human labelling of 200
   items is ≈**7 hours of Konan's time** — bounded, real, and **his decision, not ours to assign.**
2. Is the golden set hashable **before** the first experiment, or must labelling happen incrementally
   (which would weaken §6.2(b))?

**Filed separately, not Phase 2 deliverables:** the Dojo writer stop (§8.1) and the Dojo report's
profile-local location (§8.2).
