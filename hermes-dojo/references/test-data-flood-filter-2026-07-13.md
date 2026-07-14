# Test Data Flood Fix — 2026-07-13 09:09 UTC

## What Happened

The crystallization scanner continuously surfaced 3 test entries (`test_contradiction`, `c1_test_decision_1`, `c1_test_decision_2`) from `god_name='default'` as candidates every hour. These entries are injected by:

```
/home/konan/pantheon/pr35-gitworktree-d86b897/tests/test_ichor_c1_outcome_and_contradiction.py
```

This test suite writes directly to the production `~/.hermes/ichor.db` for integration testing, creating 32+ entries per day with `importance=50.0` and `god_name='default'`.

## Impact

- **3 test entries** surfaced every crystallization run (100% of candidates)
- **Zero real completion-type events** visible in the 24h window
- 3 consecutive runs (05:08, 06:14, 09:09) logged the same "sustained equilibrium / test data" finding with no forward progress
- Hidden real candidates at imp=80 existed with a 2-day lookback but were crowded out

## Fix Applied

**File:** `hermes-dojo/scripts/skill_crystallization.py`

Added:
1. `EXCLUDED_SUBJECT_PREFIXES = ("test_", "c1_test_")` constant
2. SQL WHERE clause: `AND NOT (god_name = 'default' AND (subject LIKE 'test_%' OR subject LIKE 'c1_test_%'))`

The filter targets `god_name='default'` specifically to avoid accidentally excluding legitimate events from other gods that might happen to use similar subject patterns.

## Verification

| Query | Before Fix | After Fix |
|-------|-----------|-----------|
| `--days 1` | 3 test candidates | 0 candidates (cold pool) |
| `--days 2` | 3 test candidates + 10 real | 10 real candidates (test data filtered) |
| Test entries still in DB | 32 visible | 32 excluded by filter |

## Long-term Fix Recommendation

The root cause is that `test_ichor_c1_outcome_and_contradiction.py` writes to the **production** ichor.db. The correct fix is to:
1. Configure the test to use a separate test DB (`ICHOR_DB_TEST` environment variable)
2. Or mock the store() call to avoid writing to the real DB

This filter is a stopgap — the scanner should not be responsible for cleaning up test data pollution.
