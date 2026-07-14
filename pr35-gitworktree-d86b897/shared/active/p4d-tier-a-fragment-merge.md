## 2026-06-15 — P4d: Tier-A fragment merge + reclassify (Hephaestus)

**What:** Fixed Tier-A over-fragmentation in `lib/ichor_tier_a.py`. Added two post-extraction cleanup steps:
1. `_merge_adjacent_events()` — collapses same-type overlapping fragments from one session into a single event (N-gram substring overlap detection, adaptive 8-16 char). 281 test fragments → 1 event in 1.6s.
2. `_downgrade_noisy_blockers()` — in large batches (≥10 events from one session), reclassifies low-confidence (0.50-0.65) blockers as follow_up when raw_text contains more task language (fix, implement, test) than blocking language (stuck, blocked).

**Files changed:**
- `lib/ichor_tier_a.py` — added `_merge_adjacent_events`, `_downgrade_noisy_blockers`, `_merge_two_events`, `_raw_texts_overlap` helper
- `tests/test_ichor_b5_tier_a_plus.py` — 10 new tests (5 merge, 5 reclassify)
- `athenaeum/Codex-Pantheon/DECISIONS.md` — decision logged

**Tests:** 23/26 pass (10 new, 13 existing; 3 pre-existing failures in LLM tests)

**Next:** The subconscious cron tick (next run ~03:00 UTC) will see the fix on its next cycle. No DB migration needed.
