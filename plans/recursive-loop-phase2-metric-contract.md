# Pantheon Phase 2 — Metric Contract

**Status:** DRAFT for Thoth's review. Not implemented. No evaluator built on it yet.
**Author:** Hermes · **Date:** 2026-09-23 · **Plan ref:** `report-part2.md` Phase 2
**Ruling applied:** outcome signal swapped off the mistake ledger; trust separation scheduled inside
Phase 2 as the T2/T3 gate.

---

## 0. The headline finding: neither proposed signal can power a test today

Thoth proposed **L2 drainer extraction yield** and **Dojo per-tool success rates**. I measured both
against the live tree before writing anything. Both fail — for different reasons.

| candidate signal | volume | denominator | verdict |
|---|---|---|---|
| L2 drainer extraction yield | **173 batches / 7d ≈ 24.7/day** | ❌ **not persisted** | usable **after** a 1-line instrumentation fix |
| Dojo per-tool success rate | ❌ **0 live observations** | n/a | **dead** — series frozen 2026-07-20 |
| mistake ledger (original proposal) | 5 events | n/a | **cannot power McNemar** — quantified in §5 |
| retrieval `recall_log` | 30 rows | ❌ no outcome label | needs a labelled replay set first |

**Dojo, specifically.** `profiles/marvin/skills/hermes-dojo/data/metrics.json` is 1,780 B and
contains **three entries, all timestamped 2026-07-20 04:11–04:13**, with identical values
(`sessions_analyzed: 32`, `total_tool_calls: 747`, `overall_success_rate: 90.0`). Every Dojo DB on
the host is either 0 bytes or has all-zero tables:

```
0 B        /home/konan/.hermes/hermes_dojo.db
0 B        /home/konan/.hermes/dojo/hermes_dojo.db
0 B        /home/konan/pantheon/hermes-dojo/hermes_dojo.db
36,864 B   /home/konan/.hermes/hermes-dojo/hermes_dojo.db  -> candidates: 0, sessions: 0, messages: 0
```

So the Dojo rate is not thin, it is **absent** — a stale snapshot from two months ago. This is the
*third* class of failure we have hit on this thread: not "green but wrong" (clawforge) and not
"silent no-op" (forge marker), but **"the instrument was never wired."** No evaluator can be built on
it, and reviving the writer is a separate task, not a Phase 2 deliverable.

---

## 1. What this contract measures

**Outcome:** L2 knowledge-graph extraction **yield per event** — `(entities + relationships)` emitted
per input event, over a batch.

**Why this and not something else:** it is the only candidate with real volume, a parseable
per-observation value, and a *direct* causal link to a harness change (the extraction prompt, the
batch size, the provider/model, the retry policy, the pre-filter). A change to any of those should
move yield, and nothing else in the system should.

**What it explicitly is NOT:** a measure of quality. See §6 — yield is a **proxy** and is trivially
gameable.

## 2. ⚠️ Prerequisite: the denominator is not persisted (blocking)

The yield is written to `extraction_log.source_text` as prose:

```
'L2 pass: 49 entities, 18 relationships (provisional=True)'   -- source_text
   entity_id: None   relationship_id: None   fact_id: None    -- all NULL
```

**Batch size is not a column, and is not recorded anywhere durable.** So `yield` has no denominator
in the DB — a rate without its denominator, which is the metric-integrity defect this codebase
already has a skill for. The denominator *exists* but only in journald, which rotates:

```
08:29:14 | batch 10 | batch_size 20 | events 20 | new_id 386534 | + 28 entities +  8 rels | total 200 events processed | 0.4 ev/s | 546.0s
```

**Required before any evaluation runs:** persist per-batch `{batch_id, batch_size, events_in_batch,
entities, relationships, provider, model, prompt_hash, duration_s, status}` as structured columns (or
a dedicated `l2_yield_obs` table). This is skill step 2 — *log the evaluation, not just the
outcome* — and it is the same fix already applied to the forge's gate denominators.

**Note the two sources already disagree**, which is itself a reason to persist one of them properly:

```
DB  extraction_log 'L2 pass' rows : mean yield/batch 45.5, sd 42.1, n 2,172
journal per-batch records         : mean yield/batch 26.6, sd 16.4, n 173
```

The DB includes non-drainer writers and backfills; the journal covers only the drainer. **Any metric
built on the unqualified `extraction_log` is measuring at least two different things.**

## 3. Unit of observation and pairing

- **Unit:** one extraction batch over a fixed corpus slice.
- **Design:** **paired** — the same slice extracted under baseline and candidate, so the comparison
  is within-slice and the slice's difficulty cancels. Unpaired comparison across different slices
  would confound the candidate with corpus drift, which is large here (CV 0.60).
- **Fixed slice:** the replay set is drawn from the **already-extracted** corpus (≈77.6K
  `cold_events`) so slices are stable and re-runnable, and the OOD vault is drawn from the remainder
  and is never seen by the proposer.
- **Stratification:** by `batch_size` (10 vs 20 — adaptive halving is live and visible in the data:
  `distinct batch_sizes: [10, 20]`), by source lane, and by event class. Stratifying on batch size is
  mandatory: it is currently the largest single known driver of yield.

## 4. Measured baseline (7 days, real data)

```
complete per-batch records parsed : 173
observed rate                     : 24.7 batches/day
batch sizes present               : [10, 20]
YIELD PER EVENT                   : mean 1.371   sd 0.817   median 1.300   CV 0.60
zero-yield batches                : 0
```

**24.7 batches/day, not the ~720/day the timer implies** (10 batches × 3 runs/hour). Batches take
161–546 s, so runs overrun the 20-minute interval and the `flock` skips them. Capacity is a real
constraint on how fast this instrument can reach power — recorded here because it sets the calendar
in §5, and it is a separate finding worth its own issue.

## 5. Power: MDE at 2σ, from the measured sd

`MDE = 2·sd/√n` (unpaired, worst case) and `2·(0.5·sd)/√n` (paired, sd_diff ≈ half of sd):

| n batches | unpaired MDE | as % of mean | days @ 24.7/day | paired MDE (0.5·sd) | as % |
|---|---|---|---|---|---|
| 50 | 0.231 | 16.9% | 2.0 | 0.116 | 8.4% |
| 100 | 0.163 | 11.9% | 4.0 | 0.082 | 5.9% |
| 200 | 0.116 | 8.4% | 8.1 | 0.058 | **4.2%** |
| 400 | 0.082 | 6.0% | 16.2 | 0.041 | 3.0% |
| 1000 | 0.052 | 3.8% | 40.5 | 0.026 | 1.9% |

**Acceptance criterion:** a candidate must move yield/event by **≥4.2%** (n=200 paired, ≈8 days) to
clear 2σ. Effects below that are **not detectable** and must be reported as *inconclusive*, never as
"no effect" — absence of evidence at this n is not evidence of absence.

**This is Thoth's point, quantified.** At the mistake ledger's n=5, the same test detects only a
**27%** change — i.e. nothing that would ever really happen. That is why the signal had to move.

## 6. Goodhart guards — what must NOT be optimized

1. **Yield alone is gameable.** An extractor that emits more, junkier entities scores higher.
   Yield is therefore **never a sole acceptance criterion**: a candidate must clear the yield
   threshold **and** hold a **precision floor** measured on the OOD vault (§7). A yield win that
   breaks precision is a **reject**.
2. **Tool-gate block rate is out of scope** (plan constraint #6). It is a policy outcome, not
   capability, and optimising it is a trap.
3. **No metric may be reported without its denominator.** Every reported rate carries `n` and the
   batch sizes it spans, or it prints `n/a — no denominator` (skill steps 4–5).
4. **Pre-registration.** The threshold, n, strata, and decision rule are frozen **before** a
   candidate is run. Moving a threshold after seeing the result voids the result.

## 7. OOD vault and judge

- **OOD vault:** write-only from the harness side; **exactly one reader — the eval cron.** The
  proposer must have **no read path** to it (plan constraint #8). Contents drawn from the
  never-extracted remainder so no candidate can be tuned against it.
- **Judge:** pinned by content hash — model, version, prompt, temperature 0, `max_tokens`. Any change
  to the judge is itself a ledgered harness edit under Phase 1's rules, so judge drift is versioned
  rather than silent. Judge-drift audit: <2pp across two cycles on a fixed golden set.
- **The judge must not run the live edited harness** (plan constraint #8) — circular and
  self-fulfilling.

## 8. Falsifiers — what would invalidate this instrument

- **Precision floor fails while yield rises** → the metric is being gamed; suspend.
- **Judge drift ≥2pp** between cycles on the golden set → metric is not comparable across time.
- **Denominator absent for any observation** → that observation is excluded, and the exclusion is
  **recorded**, not silent. (Same lesson as the forge marker no-op and the store's backup skip.)
- **Corpus drift exceeds the MDE** → the replay set must be re-drawn; a "win" that is corpus drift is
  not a win.

## 9. Trust separation (the T2/T3 gate — scheduled here, per ruling)

Trust separation is a **Phase 2 deliverable and the gate on T2/T3 auto-apply**. It is not yet
implemented. Required: the agent must have **no write path** to the ledger, the version store, or
guardrail config; symlinks resolved before keying (done in `61293d4`); and no per-profile sandbox
gaps. **T2/T3 auto-apply stays off until this lands.**

## 10. Open questions for Thoth

1. **Is yield/event the right proxy at all**, or should the primary be precision on a fixed golden
   set with yield as the secondary? I chose yield-primary because it has volume and precision does
   not yet — but that inverts the usual ordering and I want your read.
2. **Is 4.2% a meaningful effect size** for extraction, or is it below the level that matters
   operationally? If real effects are ~2%, this instrument needs n≈1000 (≈40 days) and the design
   should change rather than the threshold.
3. **Should the Dojo writer be revived as a Phase 2 dependency** or dropped and revisited later? I
   lean: drop from Phase 2, file it, because reviving a writer is not an evaluator deliverable.
4. **Is the capacity problem (24.7 batches/day vs 720 designed) in scope?** It sets the calendar for
   every experiment and it looks like an independent defect.
