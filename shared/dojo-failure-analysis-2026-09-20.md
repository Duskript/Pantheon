# Hermes Dojo — Failure Analysis (2026-09-20)

**Job:** weekly failure analyst · **Profile:** hephaestus · **DB:** `~/.hermes/ichor.db`
**Window:** 2026-09-13 → 2026-09-20 (7d) · **Corpus:** 7,126 blocker+correction rows / 16 distinct sessions / 4 days

## Method
Ran `failed_trajectory_mining.py` (raw: timeout 64, failed 46, traceback 12, error: 11, retry 7), then
**reclassified + de-duplicated** by distinct session, distinct subject, and distinct calendar day.
Raw keyword counts are unreliable — the literal string `timeout` appears inside shell commands, and
the single session `20260713_141051_40b91b0e` (a re-ingested July run) dominates several signatures.

## Ranked patterns (post-dedup)

| signature | live rows | subj | sessions | days | verdict |
|---|---|---|---|---|---|
| timeout_error | 80 | 45 | 9 | 4 | covered → **patched** |
| no_such_file | 46 | 27 | 7 | 3 | covered → **patched** |
| wikiguard_block | 37 | 13 | 7 | 4 | covered → **patched** (description budget) |
| command_not_found | 13 | 8 | 5 | 3 | uncovered → **created** |
| module_not_found_sys_path | 11 | 6 | 3 | 3 | uncovered → **created** |
| path_containment_valueerror | 18 | 5 | **1** | 2 | **excluded** — single-session burst |
| same_tool_failure_warning | 6 | 2 | 2 | 2 | excluded — already covered, below bar |

## Changes made (active hephaestus library)

1. **CREATED** `hermes-dojo-prevention/runtime-environment-preflight` — new umbrella owning
   `command not found` + `ModuleNotFoundError` as one class: *the running environment lacks a
   prerequisite*. Trigger / check (`command -v`, `import`, `VIRTUAL_ENV`) / resolution
   (pin `PATH`/`PYTHONPATH`/venv in the same command). 24 rows / 7 sessions.
2. **PATCHED** `bounded-operation-timeout-recovery` — new section for the `execute_code`/notebook-cell
   timeout variant, which **kills the kernel and loses in-memory state**. Prevention: checkpoint to disk
   inside the cell, move long work to `terminal(background=True)`.
3. **PATCHED** `path-existence-preflight` — new discriminator: *missing path* vs *missing dependency*
   (shared library / systemd unit), plus a note that deliberate probe-misses inflate the raw count.
4. **PATCHED** `wikiguard-patch-quality-gate` — description was 150+ chars; shortened to fit the
   routing budget. Class was otherwise already covered.

No duplicate skills created: three of the five qualifying patterns were already owned by a class-level
umbrella, so they were patched rather than re-created (anti-sprawl rule in `dojo-failure-analysis`).

## Artifacts
- `~/pantheon/hermes-dojo/outputs/dojo_failure_analysis_20260920.json`
- `~/pantheon/hermes-dojo/logs/failure_patterns.jsonl` (7 rows appended)
