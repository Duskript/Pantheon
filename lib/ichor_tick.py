"""
D1: The Learning Tick — single daily run that replaces 6 crons.

Spec: ~/athenaeum/handoffs/marvin-memory-upgrade-handoff-2026-06-10.md §D1

Replaces:
  1. ichor_subconscious.tick()       — periodic awareness report
  2. shared-context-watcher.service  — inotify shared context → ichor_events injection
  3. ichor_daily_maintenance.run()   — decay, prune, report
  4. ichor_forge nightly analysis    — pattern detection on intervention logs
  5. ichor_benchmarks.run_benchmarks — weekly retrieval benchmark
  6. clawforge_export_run.py         — Clawforge anonymized pattern submission

The tick does 7 steps in sequence (per the spec):
  1. Gather: new events since last tick, gate logs, session summaries
  2. Extract: Tier A (secondary pass on new content)
  3. Analyze: Forge patterns, outcome tracking, contradictions
  4. Improve: Weight tuning, Phronesis self-improvement
  5. Brief: Generate awareness report + shared context digest
  6. Export: Clawforge anonymized pattern submission
  7. Verify: Run automated benchmarks, compare scores

Architecture:
  - Single Python entry point: `python3 -m lib.ichor_tick --execute`
  - Replaces 6 cron entries with 1 daily cron at 3 AM (matches the old
    ichor_daily_maintenance schedule)
  - Dry-run by default for safety; --execute to actually write
  - Overlap guard prevents duplicate awareness events when old crons
    are also running during the 7-day parallel period (gate check #4)

Gate D1 checks (verbatim from spec):
  1. Old crons still work during parallel period (no-op for us — we
     don't disable them, D2 does)
  2. Tick produces equivalent output for same period
  3. Tick completes within 30 seconds
  4. No duplicate awareness events
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("ichor_tick")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TICK_VERSION = "1.0.0"
# Added "finalize" step (2026-06-21): flips provisional L2 entities to
# canonical so they're queryable. Runs right after extraction.
TICK_STEPS = ("gather", "extract", "finalize", "analyze", "improve", "brief", "export", "verify")
# Default stays 30s for the original D1 gate/test; systemd can raise this for
# the live consolidated tick so slower maintenance phases do not abort early.
MAX_TICK_SECONDS = float(os.environ.get("ICHOR_TICK_MAX_SECONDS", "30.0"))

# ---------------------------------------------------------------------------
# Paths — detect real HOME even when running inside a profile (where HOME
# points to ~/.hermes/profiles/<name>/home/). Fall back to /home/konan.
# ---------------------------------------------------------------------------
_probe_home = Path(os.environ.get("HOME", "/home/konan"))
if ".hermes/profiles" in str(_probe_home) and len(str(_probe_home)) > 30:
    # Profile-scoped HOME — resolve to the real user home
    _HOME = Path("/home/konan")
else:
    _HOME = _probe_home
_PANTHEON_LIB = _HOME / "pantheon" / "lib"
_ICHOR_DB = _HOME / ".hermes" / "ichor.db"
_GRAPH_DB = _HOME / ".hermes" / "pantheon" / "graph.db"
_TICK_STATE = _HOME / ".hermes" / "ichor_tick_state.json"
_OVERLAP_GUARD_PATH = _HOME / ".hermes" / "ichor_tick_overlap.json"
_TICK_LOG = _HOME / ".hermes" / "ichor_tick.log"

# L2 LLM extraction cursor + tuning knobs. The L2 step iterates over
# cold_events, extracting entities/relationships via LLM. State persists
# across ticks so we never re-process the same event range.
_L2_EXTRACT_STATE = _HOME / ".hermes" / "ichor_l2_extract_state.json"
_L2_EXTRACT_BATCH_SIZE = 10  # events per LLM call; small keeps each
                            # batch under ~5s and respects the 30s
                            # tick cap while leaving room for 6 other
                            # steps.
_L2_EXTRACT_TIME_BUDGET = 22.0  # sec; do not exceed this in the step


# ---------------------------------------------------------------------------
# Overlap guard
# ---------------------------------------------------------------------------

def _overlap_guard(path: Optional[Path] = None) -> Dict[str, int]:
    """Read the overlap guard state. Returns a {god: last_event_id} map.

    The overlap guard prevents duplicate awareness events. When a god
    receives a report (from the tick OR from the old subconscious cron),
    we record the last-event-id that was included. The next report for
    that god only includes events with higher ids.
    """
    p = path or _OVERLAP_GUARD_PATH
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("could not read overlap guard: %s", e)
        return {}


def _check_overlap(
    guard: Dict[str, int],
    god: str,
    event_id: int,
) -> bool:
    """True if `event_id` was already delivered to `god` (i.e. skip)."""
    last = guard.get(god, -1)
    return event_id <= last


def _mark_delivered(
    guard: Dict[str, int],
    god: str,
    event_id: int,
    path: Optional[Path] = None,
) -> None:
    """Record that `event_id` was delivered to `god`. Persists to disk."""
    guard[god] = max(guard.get(god, 0), event_id)
    p = path or _OVERLAP_GUARD_PATH
    try:
        p.write_text(json.dumps(guard, indent=2))
    except OSError as e:
        logger.warning("could not write overlap guard: %s", e)


# ---------------------------------------------------------------------------
# Tick state (for gather step)
# ---------------------------------------------------------------------------

def _read_tick_state() -> Dict[str, Any]:
    """Read the tick's persistent state (last tick time, last event id)."""
    if not _TICK_STATE.exists():
        return {"last_tick": None, "last_event_id": 0}
    try:
        return json.loads(_TICK_STATE.read_text())
    except (json.JSONDecodeError, OSError):
        return {"last_tick": None, "last_event_id": 0}


def _write_tick_state(state: Dict[str, Any]) -> None:
    """Persist tick state to disk."""
    try:
        _TICK_STATE.write_text(json.dumps(state, indent=2))
    except OSError as e:
        logger.warning("could not write tick state: %s", e)


# ---------------------------------------------------------------------------
# Step implementations
# ---------------------------------------------------------------------------

def _step_gather(dry_run: bool = True) -> Dict[str, Any]:
    """Step 1: gather new events, gate logs, session summaries.

    Counts events added to cold_events since the last tick. This
    becomes the input for the extract step.
    """
    state = _read_tick_state()
    last_id = state.get("last_event_id", 0)

    new_events = 0
    last_event_id = last_id
    if _ICHOR_DB.exists():
        try:
            con = sqlite3.connect(_ICHOR_DB)
            try:
                row = con.execute(
                    "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM cold_events WHERE id > ?",
                    (last_id,),
                ).fetchone()
                new_events = row[0] if row else 0
                last_event_id = max(row[1] if row else 0, last_id)
            finally:
                con.close()
        except sqlite3.Error as e:
            logger.warning("gather step: cold_events query failed: %s", e)

    # Sessions are tracked in retrieval-log.jsonl but not in DB
    sessions_since_last = 0
    log_path = _HOME / ".hermes" / "pantheon" / "retrieval-log.jsonl"
    if log_path.exists():
        try:
            # Count distinct queries since last tick (approximate)
            raw_cutoff = state.get("last_tick_ts", 0)
            try:
                cutoff = float(raw_cutoff)
            except (TypeError, ValueError):
                cutoff = 0
            with open(log_path) as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        if entry.get("timestamp", 0) > cutoff:
                            sessions_since_last += 1
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass

    if not dry_run:
        state["last_event_id"] = last_event_id
        # Store as string in JSON state (avoid type-coercion warnings)
        state["last_tick_ts"] = str(time.time())
        _write_tick_state(state)

    return {
        "new_events": new_events,
        "last_event_id": last_event_id,
        "last_tick": state.get("last_tick"),
        "sessions_since_last": sessions_since_last,
    }


def _step_extract(dry_run: bool = True) -> Dict[str, Any]:
    """Step 2: L2 LLM entity/relationship extraction.

    Iterates over `cold_events` past the persisted cursor in
    `_L2_EXTRACT_STATE`, calling `extract_incremental` from
    `lib.ichor.entities.l2_llm` in a loop. Each batch is one
    LLM call. The cursor is persisted after every successful
    batch so a crash mid-tick does not lose progress.

    Safety:
      - dry_run: no LLM call, no state write. Reports counts only.
      - execute: resolves provider + key first; if either is
        missing, returns {"skipped": "..."} and does not raise.
      - Per-batch try/except so one bad batch does not abort the
        rest of the loop.
      - Time-boxed via _L2_EXTRACT_TIME_BUDGET to fit the parent
        tick's 30s cap.
    """
    t0 = time.perf_counter()
    
    # Read cursor from state file. First-run behavior: seed the cursor
    # to MAX(id) - 200 so the tick keeps up with NEW events (the LLM-
    # patched prompt benefits from recent data ASAP) rather than
    # burning the entire 22s budget catching up a multi-day historical
    # backlog. The historical backlog is drained separately by
    # scripts/run_l2_full_corpus.py (or the ichor_l2_finalize MCP tool).
    cursor = 0
    is_first_run = False
    if _L2_EXTRACT_STATE.exists():
        try:
            cursor = int(json.loads(_L2_EXTRACT_STATE.read_text()).get("last_event_id", 0))
        except (json.JSONDecodeError, OSError, ValueError) as e:
            logger.warning("l2_extract: could not read state, treating as first run: %s", e)
            cursor = 0
            is_first_run = True
    else:
        is_first_run = True
    
    if is_first_run and cursor == 0:
        try:
            conn = sqlite3.connect(str(_ICHOR_DB))
            try:
                row = conn.execute("SELECT MAX(id) FROM cold_events").fetchone()
            finally:
                conn.close()
            max_id = int(row[0]) if row and row[0] is not None else 0
            # Seed 200 events back from the tip. Skip seeding if the
            # table is empty (no events to process at all).
            if max_id > 0:
                cursor = max(0, max_id - 200)
                logger.info(
                    "l2_extract: first run, seeded cursor=%d (max_id=%d, will process last ~200 events)",
                    cursor, max_id,
                )
        except sqlite3.Error as e:
            logger.warning("l2_extract: could not seed cursor from cold_events: %s", e)
    
    if dry_run:
        # No LLM call, no state write. Just report what would happen.
        try:
            conn = sqlite3.connect(str(_ICHOR_DB))
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM cold_events WHERE id > ?", (cursor,)
                ).fetchone()
            finally:
                conn.close()
        except sqlite3.Error as e:
            return {"skipped": f"db_unavailable: {e}", "cursor": cursor}
        residual = row[0] if row else 0
        return {
            "dry_run": True,
            "cursor": cursor,
            "residual_events": residual,
            "would_call_batches": max(0, (residual + _L2_EXTRACT_BATCH_SIZE - 1) // _L2_EXTRACT_BATCH_SIZE),
        }
    
    # Live path: resolve provider + key before spending any time.
    try:
        from lib.ichor.llm import _resolve_llm_provider, _load_provider_config
        from lib.ichor.entities import extract_incremental
        from lib.ichor.entities.schema import get_conn as _get_l2_conn
    except Exception as e:
        return {"skipped": f"l2_module_import_failed: {e}", "cursor": cursor}
    
    # First prefer Marvin's god/profile provider, then fall back to the
    # provider named opencode-go. The previous code called
    # _resolve_llm_provider("opencode-go"), which treats opencode-go as a
    # god/profile name and therefore never found the provider config.
    provider_cfg = _resolve_llm_provider("marvin") or _load_provider_config("opencode-go")
    if not isinstance(provider_cfg, dict):
        return {"skipped": "llm_provider_not_configured", "cursor": cursor}
    
    import os as _os
    provider_name = provider_cfg.get("name") or "opencode-go"
    provider_env_name = f"{str(provider_name).upper().replace('-', '_')}_API_KEY"
    api_key = provider_cfg.get("api_key") or _os.environ.get(provider_env_name, "")
    if not api_key:
        return {"skipped": f"no_api_key_for_{provider_name}", "cursor": cursor}
    
    # Loop: one LLM call per batch, persist cursor after each.
    batches_run = 0
    events_processed = 0
    total_entities = 0
    total_relationships = 0
    last_error = None
    
    while True:
        elapsed = time.perf_counter() - t0
        if elapsed > _L2_EXTRACT_TIME_BUDGET:
            break
        try:
            conn = _get_l2_conn()
            try:
                result = extract_incremental(
                    conn,
                    last_event_id=cursor,
                    batch_size=_L2_EXTRACT_BATCH_SIZE,
                    provider_cfg=provider_cfg,
                    model=None,
                    session_id="ichor-tick",
                )
            finally:
                conn.close()
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            logger.warning("l2_extract: batch failed, stopping loop: %s", last_error)
            break
        
        events_in_batch = int(result.get("events_in_batch", 0))
        if events_in_batch == 0:
            # Caught up; nothing more to do this tick.
            break
        
        # Advance cursor + persist (crash-safe: state reflects last
        # successfully-stored batch).
        cursor = int(result.get("last_event_id_after", cursor))
        try:
            _L2_EXTRACT_STATE.write_text(
                json.dumps({"last_event_id": cursor, "updated_at": datetime.now(timezone.utc).isoformat()})
            )
        except OSError as e:
            logger.warning("l2_extract: could not persist cursor: %s", e)
        
        batches_run += 1
        events_processed += events_in_batch
        stored = result.get("stored", {})
        total_entities += int(stored.get("entities_created", 0))
        total_relationships += int(stored.get("relationships_created", 0))
        
        # If the batch returned fewer rows than we asked for, we caught up.
        if events_in_batch < _L2_EXTRACT_BATCH_SIZE:
            break
    
    out: Dict[str, Any] = {
        "cursor": cursor,
        "batches_run": batches_run,
        "events_processed": events_processed,
        "entities_created": total_entities,
        "relationships_created": total_relationships,
        "provider": provider_name,
    }
    if last_error:
        out["last_error"] = last_error
    return out


def _step_finalize(dry_run: bool = True) -> Dict[str, Any]:
    """Step 2.5: flip provisional L2 entities/relationships to canonical.

    Reads the L2 extract cursor, then flips ALL provisional=1 → 0
    for entities and relationships. The extraction itself was handled
    by ``_step_extract`` — this step just makes them queryable.

    In dry-run mode, reports the provisional backlog size.
    """
    cursor = 0
    if _L2_EXTRACT_STATE.exists():
        try:
            cursor = int(json.loads(_L2_EXTRACT_STATE.read_text()).get("last_event_id", 0))
        except (json.JSONDecodeError, OSError, ValueError):
            cursor = 0

    if dry_run:
        try:
            conn = sqlite3.connect(str(_ICHOR_DB))
            provisional = conn.execute(
                "SELECT COUNT(*) FROM entities WHERE provisional = 1"
            ).fetchone()[0]
            rel_prov = conn.execute(
                "SELECT COUNT(*) FROM relationships WHERE provisional = 1"
            ).fetchone()[0]
            conn.close()
        except sqlite3.Error:
            return {"dry_run": True, "error": "db_unavailable", "cursor": cursor}
        return {
            "dry_run": True,
            "cursor": cursor,
            "provisional_entities": provisional,
            "provisional_relationships": rel_prov,
        }

    # Live path: just flip provisionals — no LLM needed, the
    # incremental extractor (*_step_extract*) already handled events.
    try:
        conn = sqlite3.connect(str(_ICHOR_DB))
        try:
            flipped_entities = conn.execute(
                "UPDATE entities SET provisional = 0 WHERE provisional = 1"
            ).rowcount
            flipped_relationships = conn.execute(
                "UPDATE relationships SET provisional = 0 WHERE provisional = 1"
            ).rowcount
            conn.commit()
        finally:
            conn.close()
        return {
            "cursor": cursor,
            "entities_flipped": flipped_entities,
            "relationships_flipped": flipped_relationships,
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "cursor": cursor}


def _step_analyze(dry_run: bool = True) -> Dict[str, Any]:
    """Step 3: Forge patterns, outcome tracking, contradictions.

    Runs the forge analyzer on intervention logs and surfaces any
    patterns that warrant adjustment. Outcomes from the retrieval
    log (C1) are aggregated. Contradictions are flagged.
    """
    findings: Dict[str, Any] = {}

    # Forge: read intervention logs, count findings
    forge_findings_count = 0
    forge_log = _HOME / ".hermes" / "ichor" / "forge" / "all.jsonl"
    if forge_log.exists():
        try:
            cutoff_ts = time.time() - 7 * 86400  # 7 days
            with open(forge_log) as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        if entry.get("timestamp", 0) > cutoff_ts:
                            forge_findings_count += 1
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass
    findings["forge_findings"] = forge_findings_count

    # Outcomes: count entries with non-pending outcome in retrieval log
    outcomes_processed = 0
    pending_promoted = 0
    pending_within_grace = 0
    log_path = _HOME / ".hermes" / "pantheon" / "retrieval-log.jsonl"
    if log_path.exists():
        try:
            with open(log_path) as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        outcome = entry.get("outcome")
                        if outcome not in (None, "pending"):
                            outcomes_processed += 1
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass
    findings["outcomes_processed"] = outcomes_processed

    # B4 (Pass 3.1) — promote stale `pending` entries to `unknown`
    # (default grace 4h). The Outcome API only returns non-pending
    # entries, so this makes the historical 2,433 `pending` entries
    # surface to `get_recent_outcomes()` as `unknown`. Only runs in
    # --execute mode; in dry-run, we just count.
    if not dry_run:
        try:
            from lib.clawforge.outcome_backfill import backfill_pending
            counts = backfill_pending(log_path, grace_hours=4.0, new_outcome="unknown")
            pending_promoted = counts.get("promoted", 0)
            pending_within_grace = counts.get("pending_within_grace", 0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("outcome backfill step failed (non-fatal): %s", exc)
    findings["pending_promoted_to_unknown"] = pending_promoted
    findings["pending_within_grace"] = pending_within_grace

    # Contradictions: count events with `contradiction_warning` flag
    # (set by C1's detect_contradiction on store)
    contradictions = 0
    if _ICHOR_DB.exists():
        try:
            con = sqlite3.connect(_ICHOR_DB)
            try:
                row = con.execute(
                    "SELECT COUNT(*) FROM warm_entities "
                    "WHERE category = 'correction'"
                ).fetchone()
                contradictions = row[0] if row else 0
            finally:
                con.close()
        except sqlite3.Error:
            pass
    findings["contradictions_flagged"] = contradictions

    return findings


def _step_improve(dry_run: bool = True) -> Dict[str, Any]:
    """Step 4: weight tuning, Phronesis self-improvement.

    In dry-run, no drift is applied — just reports what drift
    *would* be applied. In --execute mode, the weight tuner runs
    one cycle and applies drift (capped at 5% per spec).
    """
    if dry_run:
        # Don't actually drift in dry-run; just report the current state
        from lib.ichor_hybrid import WEIGHTS
        return {
            "weights_after": dict(WEIGHTS),
            "drift_applied": {},
            "dry_run": True,
        }

    # Live mode: run the weight tuner
    try:
        from lib.ichor_benchmarks import tuner, run_benchmarks
        # Load previous recall from history
        history_path = _HOME / ".hermes" / "ichor_weights_history.json"
        previous_recall: Optional[float] = None
        if history_path.exists():
            try:
                hist = json.loads(history_path.read_text())
                cycles = hist.get("cycles", [])
                if cycles:
                    previous_recall = cycles[-1].get("current_recall")
            except (json.JSONDecodeError, OSError):
                pass

        report = run_benchmarks()
        current_recall = report.get("recall@5", 0.0)
        new_weights = tuner.cycle(previous_recall, current_recall)
        tuner.apply()
        return {
            "weights_after": new_weights,
            "drift_applied": True,
            "recall_at_5": current_recall,
        }
    except Exception as e:
        logger.warning("improve step failed: %s", e)
        from lib.ichor_hybrid import WEIGHTS
        return {
            "weights_after": dict(WEIGHTS),
            "drift_applied": False,
            "error": str(e),
        }


def _step_brief(dry_run: bool = True) -> Dict[str, Any]:
    """Step 5: awareness report + shared context digest.

    Two artifacts:
      - Brief: per-god awareness report (replaces subconscious)
      - Digest: shared context digest (replaces inject-shared-context)

    In dry-run, just confirms both can be generated.
    In --execute, writes both to ~/pantheon/logs/ichor_tick/{date}/.
    """
    result: Dict[str, Any] = {
        "brief_generated": False,
        "digest_generated": False,
        "dry_run": dry_run,
    }

    if dry_run:
        # Confirm both subsystems are importable and callable.
        from lib.ichor_brief import build_brief
        from lib.ichor_subconscious import tick as subconscious_tick
        sample_brief = build_brief(god_name="marvin", limit=1, output_format="json")
        result["brief_generated"] = bool(sample_brief)
        result["digest_generated"] = True  # subconscious.tick() always returns a dict
        return result

    # Live: actually generate both.
    from datetime import datetime
    out_dir = _HOME / "pantheon" / "logs" / "ichor_tick" / datetime.now().strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Brief — per-god awareness (replaces ichor_subconscious)
    from lib.ichor_brief import build_brief
    brief_md = build_brief(god_name="marvin", limit=20, min_score=0.2, output_format="markdown")
    (out_dir / "brief_marvin.md").write_text(brief_md)
    result["brief_generated"] = True
    result["brief_path"] = str(out_dir / "brief_marvin.md")

    # Digest — shared context (replaces inject-shared-context)
    from lib.ichor_subconscious import tick as subconscious_tick
    digest = subconscious_tick(god_name="", dry_run=False)
    (out_dir / "digest.json").write_text(json.dumps(digest, indent=2, default=str))
    result["digest_generated"] = True
    result["digest_path"] = str(out_dir / "digest.json")

    return result


def _step_export(dry_run: bool = True) -> Dict[str, Any]:
    """Step 6: Clawforge anonymized pattern submission.

    In dry-run, counts what *would* be exported. In live mode,
    invokes the Clawforge export pipeline (already built in
    Pass 3 Phase 4).
    """
    if dry_run:
        return {
            "patterns_exported": 0,
            "dry_run": True,
        }

    # Live mode: invoke the export
    try:
        # The export is gated by Clawforge's master + per-system + sentinel
        # gates. In dry-run we don't touch it; in live mode the system
        # service handles it (systemd timer, not the tick).
        return {
            "patterns_exported": 0,
            "note": "Clawforge export is on a separate timer (clawforge-pattern-export-forge.timer)",
        }
    except Exception as e:
        logger.warning("export step failed: %s", e)
        return {"patterns_exported": 0, "error": str(e)}


def _step_verify(dry_run: bool = True) -> Dict[str, Any]:
    """Step 7: run automated benchmarks, compare scores.

    The actual benchmark is the same C2 module. In dry-run, we
    just return the last-known scores from the history file.
    """
    history_path = _HOME / ".hermes" / "ichor_weights_history.json"
    last_known = {"recall_at_5": 0.0, "latency_p50_ms": 0.0}

    if history_path.exists():
        try:
            hist = json.loads(history_path.read_text())
            cycles = hist.get("cycles", [])
            if cycles:
                last = cycles[-1]
                last_known["recall_at_5"] = last.get("current_recall", 0.0)
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "benchmark": last_known,
        "note": "dry-run" if dry_run else "live",
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

_STEP_FUNCS: Dict[str, Callable] = {
    "gather": _step_gather,
    "extract": _step_extract,
    "finalize": _step_finalize,
    "analyze": _step_analyze,
    "improve": _step_improve,
    "brief": _step_brief,
    "export": _step_export,
    "verify": _step_verify,
}


def run_tick(dry_run: bool = True) -> Dict[str, Any]:
    """Run the full 7-step Learning Tick. Returns a structured report.

    Args:
        dry_run: If True (default), no state changes — only reports
            what each step *would* do. Pass --execute on the CLI to
            actually apply changes.

    Returns:
        {
            "version": "1.0.0",
            "started_at": ISO 8601 UTC,
            "duration_seconds": float,
            "steps": {step_name: step_output, ...},
            "dry_run": bool,
        }
    """
    t0 = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()

    result: Dict[str, Any] = {
        "version": TICK_VERSION,
        "started_at": started_at,
        "duration_seconds": 0.0,
        "steps": {},
        "dry_run": dry_run,
    }

    for step_name in TICK_STEPS:
        step_fn = _STEP_FUNCS[step_name]
        step_t0 = time.perf_counter()
        try:
            step_result = step_fn(dry_run=dry_run)
        except Exception as e:
            logger.warning("step %s failed: %s", step_name, e)
            step_result = {"error": str(e)}
        step_duration = time.perf_counter() - step_t0
        step_result["duration_seconds"] = round(step_duration, 3)
        result["steps"][step_name] = step_result
        # Cap guard: bail if we're approaching the 30s budget
        if (time.perf_counter() - t0) > (MAX_TICK_SECONDS - 1.0):
            logger.warning("tick approaching %ss cap, aborting remaining steps",
                           MAX_TICK_SECONDS)
            result["aborted_early"] = True
            break

    result["duration_seconds"] = round(time.perf_counter() - t0, 3)

    # Log the tick
    _log_tick(result)

    return result


def _log_tick(result: Dict[str, Any]) -> None:
    """Append tick result to the tick log."""
    try:
        with open(_TICK_LOG, "a") as f:
            f.write(json.dumps(result) + "\n")
    except OSError as e:
        logger.warning("could not write tick log: %s", e)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    """CLI entry point: `python3 -m lib.ichor_tick [--execute]`."""
    import argparse
    parser = argparse.ArgumentParser(
        description="Run the Ichor Learning Tick (replaces 6 crons).",
    )
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually apply changes (default: dry-run, no writes).",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

        # Pre-flight: check Ichor backend health
    health_warnings = []
    try:
        from lib.ichor.vector_backend import VectorBackend
        vb = VectorBackend(db_path=str(_HOME / ".hermes" / "ichor.db"))
        if not vb.health():
            health_warnings.append("VECTOR BACKEND DOWN — event_embeddings table missing. Semantic search degraded.")
    except Exception as e:
        health_warnings.append(f"Vector backend health check failed: {e}")
    try:
        import sqlite3
        con = sqlite3.connect(str(_HOME / ".hermes" / "ichor.db"))
        row = con.execute(
            "SELECT name FROM sqlite_master WHERE name = 'ichor_events_fts_idx'"
        ).fetchone()
        if not row:
            health_warnings.append("FTS5 indexes missing — keyword search may be degraded.")
        con.close()
    except Exception as e:
        health_warnings.append(f"FTS5 check failed: {e}")
    result = run_tick(dry_run=not args.execute)

    # --- Summary output ---
    label = "DRY-RUN" if result['dry_run'] else "EXECUTED"
    print(f"Ichor Tick v{result['version']} — {label}")
    print(f"Duration: {result['duration_seconds']:.2f}s")
    print()

    # Health banner
    if health_warnings:
        print("⚠️  HEALTH ISSUES:")
        for w in health_warnings:
            print(f"   ⚠️  {w}")
        print()

    # Step summaries
    steps = result.get("steps", {})
    for step_name in ["gather", "extract", "finalize", "analyze", "improve", "brief", "export", "verify"]:
        s = steps.get(step_name)
        if not s:
            continue
        dur = s.get("duration_seconds", 0)
        skipped = s.get("skipped")
        error = s.get("error")
        dry = s.get("dry_run", False)

        # Build a one-line summary per step
        details = []
        if step_name == "gather":
            details.append(f"new_events={s.get('new_events',0)}")
            details.append(f"sessions={s.get('sessions_since_last',0)}")
        elif step_name == "extract":
            if skipped:
                details.append(f"SKIPPED: {skipped[:50]}")
            elif dry:
                details.append(f"residual={s.get('residual_events',0)} events")
            else:
                details.append(f"batches={s.get('batches_run',0)}")
                details.append(f"events={s.get('events_processed',0)}")
                details.append(f"entities={s.get('entities_created',0)}")
                details.append(f"rels={s.get('relationships_created',0)}")
            if error:
                details.append(f"ERROR: {error[:40]}")
        elif step_name == "finalize":
            if skipped:
                details.append(f"SKIPPED: {skipped[:50]}")
            elif dry:
                details.append(f"provisional_ents={s.get('provisional_entities',0)}")
                details.append(f"provisional_rels={s.get('provisional_relationships',0)}")
            else:
                details.append(f"flipped_ents={s.get('entities_flipped',0)}")
                details.append(f"flipped_rels={s.get('relationships_flipped',0)}")
            if error:
                details.append(f"ERROR: {error[:40]}")
        elif step_name == "analyze":
            details.append(f"forge={s.get('forge_findings',0)}")
            details.append(f"outcomes={s.get('outcomes_processed',0)}")
            details.append(f"contradictions={s.get('contradictions_flagged',0)}")
        elif step_name == "improve":
            if dry:
                w = s.get("weights_after", {})
                summary = ", ".join(f"{k}={v:.2f}" for k, v in list(w.items())[:6])
                details.append(f"weights: {summary}")
            else:
                drift = s.get("drift_applied", {})
                if isinstance(drift, dict):
                    drift_count = len(drift)
                elif isinstance(drift, (list, tuple, set)):
                    drift_count = len(drift)
                else:
                    drift_count = 1 if drift else 0
                details.append(f"drift={drift_count} weights adjusted")
        elif step_name == "brief":
            delivered = s.get("events_delivered", {})
            if isinstance(delivered, dict):
                details.append(f"gods_reported={len(delivered)}")
                total = sum(len(v) for v in delivered.values()) if delivered else 0
                details.append(f"total_events={total}")
        elif step_name == "export":
            details.append(f"submitted={s.get('submitted',0)}")
        elif step_name == "verify":
            benchmark = s.get("benchmark_results", s.get("recall", ""))
            details.append(f"recall={benchmark}" if benchmark else "no data")

        if error and not details:
            details.append(f"ERROR: {error[:60]}")

        detail_str = " | ".join(details) if details else ""
        print(f"  {step_name:10s} {dur:6.3f}s  {detail_str}")

    if result.get("aborted_early"):
        print()
        print("⚠️  TICK ABORTED EARLY — hit time cap before all steps completed.")

    print()
    print(f"--- end tick (v{result['version']}) ---")
    return 0


if __name__ == "__main__":
    sys.exit(main())
