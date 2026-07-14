# Dojo Crystallization Batch — 2026-07-11 14:07 UTC (10th pass)

**Scanner:** Not invoked (equilibrium — skipped per noise-pattern-catalog action map)
**Count:** N/A (pool known stable: 20 candidates, same clusters since 00:20 UTC)
**Session type:** Cron (hephaestus)
**Pass today:** 10th

## Library Improvements (3 script patches + 1 catalog heuristic)

### 1. `count_consecutive_none.py` — empty skill_name normalization
**Bug:** `count_consecutive_none.py` only matched `"__NONE__"` but not `""` (empty string).
Three recent journal entries (lines 21-23) had `skill_name=""` from prior `log_batch()` 
calls that passed empty strings. These were incorrectly treated as non-NONE breakers, 
causing consecutive_none=0 even though the pool was clearly in equilibrium.
**Fix:** Normalize empty/falsy skill_name as NONE alongside `__NONE__`, matching 
context_detect.py's logic. Both scripts now agree on consecutive NONE count.

### 2. `skill_crystallization.py` — save_crystallization normalization (root cause fix)
**Bug:** `save_crystallization()` wrote `skill_name` as-is without normalizing empty
strings to `__NONE__`. This was the root cause of the empty-string entries in the
journal. The log_batch.py script correctly writes `skill_name: __NONE__`, but direct
calls to save_crystallization (or log_batch with empty sk fields) left empty strings.
**Fix:** `skill_name or "__NONE__"` and `skill_path or "__NONE__"` ensure any falsy
input is normalized to `__NONE__` before writing.

### 3. `context_detect.py` — journal path resolution + profile_home fallback
**Bug:** context_detect.py used `$HERMES_HOME/dojo/crystallizations.jsonl` directly.
When HERMES_HOME was set to `~/.hermes/profiles/hephaestus/`, it read the PROFILE
journal (333KB, stale from July 9) instead of the SHARED journal (37KB, current).
This caused context_detect to report today_no_ops=0 and Equilibrium=NO on every
cron run — ALL prior runs today were reading a stale file.
**Fix:** Added `_resolve_hermes_home()` (same logic as skill_crystallization.py) to
walk up from profile paths to the shared `~/.hermes/` root. Also fixed the
`profile_home` fallback — when HERMES_PROFILE_HOME is unset, it now derives from
HERMES_HOME (the raw env var) or defaults to `~/.hermes/profiles/hephaestus`.

### 4. Noise-pattern-catalog.md — `today_no_ops > consecutive_none` heuristic
Added a new heuristic to the Pattern 23 equilibrium thresholds section. When
today_no_ops exceeds consecutive_none (e.g., today_no_ops=8 but consecutive_none=6),
the pool IS in sustained equilibrium — a real skill entry (python-module-invocation)
reset the consecutive counter mid-day but the candidate pool did not turn over.

## Operational Notes
- 10 passes today over the same candidate pool (all 0 skills)
- Pattern 23 (Candidate-Set Saturation) confirmed — deep sustained equilibrium
- Auto-skip recommended for next 4-6 cron cycles (expect ~20 more hours of stale pool)
- caduceus auth session `20260711_011019` is the dominant source of importance=80 entries
- Next expected turnover: when new complex sessions (>5 tool calls) appear in ichor_events
- The journal path bug (fix #3 above) affected ALL prior runs today — context_detect was
  consistently under-reporting equilibrium state, making agents run the scanner unnecessarily

## NEXT_STEP
Sustained equilibrium confirmed. Skip scanner for next 4-6 cycles unless fresh
high-importance (>70) sessions with new session IDs appear in the event stream.
