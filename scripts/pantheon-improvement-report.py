#!/usr/bin/env python3
"""Pantheon Improvement Report — consolidated metrics from Dojo + Forge + Retrieval.

Phase 4 of the Ichor Forge. Collects improvement data from all three
self-improvement subsystems and produces a single report.

Usage:
    python3 scripts/pantheon-improvement-report.py              # Markdown report
    python3 scripts/pantheon-improvement-report.py --json       # Raw JSON
    python3 scripts/pantheon-improvement-report.py --save /tmp  # Save to file
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("improvement-report")

HOME = os.path.expanduser("~")
# The Dojo's metrics.json moved under the profile that owns the Dojo
# (`profiles/marvin/skills/hermes-dojo/data/metrics.json`). The hardcoded legacy
# path was never updated, so this report's Dojo section had been structurally
# empty since the move — it did not fail, it just rendered nothing.
_DOJO_DATA_CANDIDATES = (
    Path(f"{HOME}/.hermes/skills/hermes-dojo/data/metrics.json"),
    Path(f"{HOME}/.hermes/profiles/marvin/skills/hermes-dojo/data/metrics.json"),
    Path(f"{HOME}/.hermes/profiles/marvin/dojo/data/metrics.json"),
    Path(f"{HOME}/.hermes/hermes-dojo/data/metrics.json"),
)


def _discover_dojo_data() -> Path:
    """First existing candidate, else the documented legacy path.

    Path discovery rather than a hardcoded location so the next move does not
    silently empty this section again.
    """
    for cand in _DOJO_DATA_CANDIDATES:
        if cand.is_file():
            return cand
    return _DOJO_DATA_CANDIDATES[0]


DOJO_DATA = _discover_dojo_data()
FORGE_LOG = Path(f"{HOME}/.hermes/ichor/forge/all.jsonl")
RETRIEVAL_LOG = Path(f"{HOME}/.hermes/pantheon/retrieval-log.jsonl")
WEIGHTS_PATH = Path(f"{HOME}/pantheon/lib/ichor_hybrid.py")


# ── Freshness gate ──────────────────────────────────────────────────────
# A metric that cannot state when it was last written is indistinguishable from a
# live reading. This report rendered the Dojo's success rate and its 7/30-day
# deltas from a 65-day-old file — a plausible number from a dead source. The
# guard (`lib/ichor/freshness.py`) was built and tested but NOTHING IMPORTED IT,
# so it caught nothing. This is the wiring.
# Import as `lib.ichor.freshness`, NOT `ichor.freshness`, with the REPO ROOT on the
# path. `lib/ichor/__init__.py` does `from lib.ichor.migrations... import ...`, so
# putting `lib/` on the path instead raises ModuleNotFoundError on `lib.ichor.migrations`.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
try:
    from lib.ichor.freshness import stamp_for_file  # noqa: E402
    _FRESHNESS_AVAILABLE = True
    _FRESHNESS_ERROR = ""
except Exception as _e:
    # An unavailable guard must NOT degrade to "assume fresh". That is the exact
    # class-4 failure this wiring exists to remove: a plausible number from an
    # unverifiable source. Say so, and let --strict fail on it.
    _FRESHNESS_AVAILABLE = False
    _FRESHNESS_ERROR = f"{type(_e).__name__}: {_e}"
    logger.warning("freshness guard UNAVAILABLE (%s) — freshness cannot be verified", _e)


def _freshness_gate(path: Path, name: str, result: Dict[str, Any]) -> bool:
    """Stamp `path`, record staleness on `result`, return "safe to report numbers".

    Returns False when the source is stale or absent. The caller must then NOT
    populate derived values — a stale number rendered as current is exactly the
    failure this guard exists to prevent.

    Never raises. A report that raises produces nothing, and "nothing" is
    indistinguishable from "no problem". Staleness is *stated* instead; `--strict`
    turns it into a non-zero exit for cron, where a hard failure is correct.
    """
    result.setdefault("stale", False)
    result.setdefault("age_days", None)
    if not _FRESHNESS_AVAILABLE:
        # Cannot verify -> not "fresh". Reporting the numbers anyway is how a
        # stale figure becomes indistinguishable from a live one.
        result["stale"] = True
        result["stale_reason"] = (
            f"{name}: freshness UNVERIFIABLE — guard failed to import ({_FRESHNESS_ERROR})"
        )
        return False
    stamp = stamp_for_file(path, name)
    result["age_days"] = round(stamp.age_s / 86400, 1)
    if not stamp.is_fresh:
        result["stale"] = True
        result["stale_reason"] = (
            f"{name}: last written {stamp.human_age()} ago, "
            f"max {stamp.max_age_s / 3600:.0f}h — {path}"
        )
        logger.warning("  STALE  %s", result["stale_reason"])
        return False
    return True


# ── Section 1: Dojo Skills ──────────────────────────────────────────────

def get_dojo_metrics() -> Dict[str, Any]:
    """Load Dojo metrics history and compute skill improvement deltas."""
    result: Dict[str, Any] = {
        "available": False,
        "snapshots": 0,
        "current_success_rate": None,
        "delta_7d": None,
        "delta_30d": None,
        "improvements_made": [],
        "weakest_tools": [],
        "trend_sparkline": "",
    }

    if not DOJO_DATA.exists():
        logger.info("  Dojo: no metrics data at %s", DOJO_DATA)
        result["stale"] = True
        result["stale_reason"] = f"dojo_metrics: file absent — {DOJO_DATA}"
        return result

    # Gate BEFORE reading: a 65-day-old file must not yield a current-looking rate.
    if not _freshness_gate(DOJO_DATA, "dojo_metrics", result):
        return result

    try:
        with open(DOJO_DATA) as f:
            history = json.load(f)

        if not history:
            return result

        result["available"] = True
        result["snapshots"] = len(history)
        latest = history[-1]
        result["current_success_rate"] = latest.get("overall_success_rate")

        # 7-day delta
        recent = [h for h in history if h.get("timestamp", 0) > time.time() - 7 * 86400]
        if len(recent) >= 2:
            result["delta_7d"] = round(
                recent[-1].get("overall_success_rate", 0) - recent[0].get("overall_success_rate", 0),
                1,
            )

        # 30-day delta
        month = [h for h in history if h.get("timestamp", 0) > time.time() - 30 * 86400]
        if len(month) >= 2:
            result["delta_30d"] = round(
                month[-1].get("overall_success_rate", 0) - month[0].get("overall_success_rate", 0),
                1,
            )

        # Improvements made
        for h in history:
            for imp in h.get("improvements_made", []):
                result["improvements_made"].append({
                    "date": h.get("date", "?"),
                    "action": imp.get("action", "?"),
                    "target": imp.get("target", "?"),
                    "description": imp.get("description", ""),
                })

        # Weakest tools from latest snapshot
        result["weakest_tools"] = latest.get("weakest_tools", [])

        # Sparkline from last 7 snapshots
        rates = [h.get("overall_success_rate", 0) for h in history[-7:]]
        if len(rates) >= 3:
            blocks = " ▁▂▃▄▅▆▇█"
            min_r, max_r = min(rates), max(rates)
            span = max_r - min_r
            if span == 0:
                result["trend_sparkline"] = "█" * len(rates)
            else:
                result["trend_sparkline"] = "".join(
                    blocks[min(8, int((r - min_r) / span * 8))] for r in rates
                )

    except Exception as exc:
        logger.warning("  Dojo read failed: %s", exc)

    return result


# ── Section 2: Forge Harness ────────────────────────────────────────────

def get_forge_metrics() -> Dict[str, Any]:
    """Analyze forge intervention logs for gate/harness improvements."""
    result: Dict[str, Any] = {
        "available": False,
        "total_interventions": 0,
        "overall_block_rate": None,
        "per_gate": {},
        "patterns_found": [],
        "adjustments_suggested": [],
    }

    if not FORGE_LOG.exists():
        logger.info("  Forge: no log at %s", FORGE_LOG)
        result["stale"] = True
        result["stale_reason"] = f"forge_improvement_report: log absent — {FORGE_LOG}"
        return result

    if not _freshness_gate(FORGE_LOG, "forge_improvement_report", result):
        return result

    # Try importing the forge analyzer directly
    try:
        # Careful with the import path — scripts/lib/ has a dir-as-module
        _lib = f"{HOME}/pantheon/lib"
        if _lib not in sys.path:
            sys.path.insert(0, _lib)
        # Don't let scripts/lib leak into path
        _scripts_lib = f"{HOME}/pantheon/scripts/lib"
        if _scripts_lib in sys.path:
            sys.path.remove(_scripts_lib)

        from ichor_forge import ForgeAnalyzer  # type: ignore

        analyzer = ForgeAnalyzer()
        findings = analyzer.analyze(days=7)

        result["available"] = True
        result["total_interventions"] = findings.total_interventions
        result["overall_block_rate"] = round(findings.overall_block_rate, 3)
        result["patterns_found"] = findings.detected_patterns
        result["adjustments_suggested"] = findings.suggested_adjustments

        for gate_name, gm in findings.per_gate.items():
            result["per_gate"][gate_name] = {
                "total": gm.total,
                "blocked": gm.blocked,
                "passed": gm.passed,
                "block_rate": round(gm.block_rate, 3),
                "top_blocks": [f"{msg}: {cnt}x" for msg, cnt in gm.top_block_messages.most_common(3)],
            }

    except Exception as exc:
        logger.warning("  Forge: analyzer import failed (%s), falling back to JSONL parse", exc)
        # Fallback: parse the JSONL directly for basic stats
        try:
            total = 0
            blocked = 0
            gates: Dict[str, Dict] = {}
            with open(FORGE_LOG) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    ts = entry.get("timestamp", 0)
                    if ts < time.time() - 7 * 86400:
                        continue
                    total += 1
                    gate = entry.get("gate", "unknown")
                    passed = entry.get("passed", False)
                    if gate not in gates:
                        gates[gate] = {"total": 0, "blocked": 0, "passed": 0}
                    gates[gate]["total"] += 1
                    if passed:
                        gates[gate]["passed"] += 1
                    else:
                        gates[gate]["blocked"] += 1
                        blocked += 1

            if total > 0:
                result["available"] = True
                result["total_interventions"] = total
                result["overall_block_rate"] = round(blocked / total, 3)
                for g, d in gates.items():
                    d["block_rate"] = round(d["blocked"] / d["total"], 3) if d["total"] > 0 else 0
                    result["per_gate"][g] = d

        except Exception as exc2:
            logger.warning("  Forge: fallback parse failed: %s", exc2)

    return result


# ── Section 3: Retrieval Weights ────────────────────────────────────────

def get_current_weights() -> Dict[str, float]:
    """Read current WEIGHTS dict from ichor_hybrid.py."""
    if not WEIGHTS_PATH.exists():
        return {}
    try:
        content = WEIGHTS_PATH.read_text()
        # Find the WEIGHTS dict
        import ast
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "WEIGHTS":
                        if isinstance(node.value, ast.Dict):
                            weights = {}
                            for k, v in zip(node.value.keys, node.value.values):
                                if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                                    weights[str(k.value)] = float(v.value)
                            return weights
    except Exception as exc:
        logger.warning("  Weights read failed: %s", exc)
    return {}


def get_retrieval_metrics() -> Dict[str, Any]:
    """Analyze retrieval query log for usage patterns."""
    result: Dict[str, Any] = {
        "available": False,
        "total_queries": 0,
        "since_days": 0,
        "current_weights": {},
        "top_queries": [],
        "avg_results_per_query": None,
    }

    result["current_weights"] = get_current_weights()

    if not RETRIEVAL_LOG.exists():
        logger.info("  Retrieval: no query log at %s", RETRIEVAL_LOG)
        return result

    try:
        queries = []
        cutoff = time.time() - 7 * 86400
        with open(RETRIEVAL_LOG) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                ts = entry.get("timestamp", 0)
                if ts < cutoff:
                    continue
                queries.append(entry)

        if not queries:
            return result

        result["available"] = True
        result["total_queries"] = len(queries)

        # Time span
        ts_min = min(q.get("timestamp", 0) for q in queries)
        ts_max = max(q.get("timestamp", 0) for q in queries)
        result["since_days"] = round((ts_max - ts_min) / 86400, 1) if ts_max > ts_min else 0

        # Top queries
        from collections import Counter
        query_counter = Counter(q.get("query", "") for q in queries)
        result["top_queries"] = [
            {"query": q, "count": c}
            for q, c in query_counter.most_common(10)
        ]

        # Avg results
        result_counts = [len(q.get("result_ids", [])) for q in queries if q.get("result_ids")]
        if result_counts:
            result["avg_results_per_query"] = round(sum(result_counts) / len(result_counts), 1)

    except Exception as exc:
        logger.warning("  Retrieval log read failed: %s", exc)

    return result


# ── Report Formatter ────────────────────────────────────────────────────

def format_improvement_report(
    dojo: Dict[str, Any],
    forge: Dict[str, Any],
    retrieval: Dict[str, Any],
) -> str:
    """Format the consolidated report as markdown."""
    lines = [
        "🏛️ Pantheon Improvement Report",
        f"_{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
    ]

    # ── Section 1: Skills (Dojo) ──
    lines.append("## 🥋 Skills (Hermes Dojo)")
    if dojo.get("available"):
        rate = dojo.get("current_success_rate")
        spark = dojo.get("trend_sparkline")
        if rate is not None:
            lines.append(f"  **Success rate:** {rate:.1f}%")
        if spark:
            lines.append(f"  **Trend:** [{spark}]")
        if dojo.get("delta_7d") is not None:
            d = dojo["delta_7d"]
            arrow = "📈" if d > 0 else "📉" if d < 0 else "➡️"
            lines.append(f"  **7-day delta:** {arrow} {'+' if d > 0 else ''}{d}%")
        if dojo.get("delta_30d") is not None:
            d = dojo["delta_30d"]
            arrow = "📈" if d > 0 else "📉" if d < 0 else "➡️"
            lines.append(f"  **30-day delta:** {arrow} {'+' if d > 0 else ''}{d}%")

        imps = dojo.get("improvements_made", [])
        if imps:
            patched = [i for i in imps if i.get("action") == "patch"]
            created = [i for i in imps if i.get("action") == "create"]
            evolved = [i for i in imps if i.get("action") == "evolve"]
            if patched:
                lines.append(f"\n  ✅ **Patched skills ({len(patched)}):**")
                for p in patched[-5:]:
                    lines.append(f"    • {p['target']}: {p.get('description', 'improved')}")
            if created:
                lines.append(f"\n  🆕 **New skills ({len(created)}):**")
                for c in created[-3:]:
                    lines.append(f"    • {c['target']}: {c.get('description', 'created')}")

        weak = dojo.get("weakest_tools", [])
        if weak:
            lines.append(f"\n  🔻 **Weakest tools:**")
            for t in weak[:3]:
                lines.append(f"    • {t.get('tool', '?')}: {t.get('success_rate', 0)}% success")
    else:
        lines.append("  _No Dojo data available yet._")
    lines.append("")

    # ── Section 2: Harnesses (Forge) ──
    lines.append("## 🔧 Harnesses (Ichor Forge)")
    if forge.get("available"):
        lines.append(f"  **Interventions (7d):** {forge['total_interventions']}")
        if forge.get("overall_block_rate") is not None:
            lines.append(f"  **Overall block rate:** {forge['overall_block_rate']:.0%}")

        for gate_name, gm in forge.get("per_gate", {}).items():
            br = gm.get("block_rate", 0)
            icon = "🔴" if br > 0.6 else "🟡" if br > 0.3 else "🟢"
            lines.append(
                f"  {icon} **{gate_name}:** {gm.get('total', 0)} calls, "
                f"{br:.0%} block rate"
            )
            top = gm.get("top_blocks", [])
            if top:
                for tb in top[:2]:
                    lines.append(f"       ↳ {tb}")

        patterns = forge.get("patterns_found", [])
        if patterns:
            lines.append(f"\n  🔍 **Patterns detected ({len(patterns)}):**")
            for p in patterns[:5]:
                lines.append(f"    • {p}")

        adjustments = forge.get("adjustments_suggested", [])
        if adjustments:
            lines.append(f"\n  💡 **Suggested adjustments ({len(adjustments)}):**")
            for a in adjustments[:5]:
                lines.append(f"    • {a}")
    else:
        lines.append("  _No forge data available yet._")
    lines.append("")

    # ── Section 3: Memory Weights ──
    lines.append("## ⚖️ Memory Weights (Retrieval)")
    weights = retrieval.get("current_weights", {})
    if weights:
        lines.append("  **Current weights:**")
        total = sum(weights.values())
        for backend, w in sorted(weights.items(), key=lambda x: -x[1]):
            pct = w / total * 100 if total > 0 else 0
            bar = "█" * int(pct / 5) + "░" * max(0, 20 - int(pct / 5))
            lines.append(f"    • **{backend}:** {w:.2f}  {bar} {pct:.0f}%")

    if retrieval.get("available"):
        lines.append(f"\n  **Queries logged (7d):** {retrieval['total_queries']}")
        if retrieval.get("avg_results_per_query") is not None:
            lines.append(f"  **Avg results/query:** {retrieval['avg_results_per_query']}")
        top_q = retrieval.get("top_queries", [])
        if top_q:
            lines.append(f"\n  **Top queries:**")
            for q in top_q[:5]:
                lines.append(f"    • \"{q['query'][:60]}\" — {q['count']}x")
    else:
        lines.append("\n  _Retrieval query log not yet active._")
    lines.append("")

    # ── Footer ──
    lines.append("---")
    lines.append(f"_Report generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_")

    return "\n".join(lines)


# ── Main ────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Pantheon Improvement Report")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--save", metavar="PATH", help="Save to file")
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit non-zero if any source is stale (use from cron)",
    )
    args = parser.parse_args()

    logger.info("Collecting Dojo metrics...")
    dojo = get_dojo_metrics()

    logger.info("Collecting Forge metrics...")
    forge = get_forge_metrics()

    logger.info("Collecting retrieval metrics...")
    retrieval = get_retrieval_metrics()

    if args.json:
        output = json.dumps({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "dojo": dojo,
            "forge": forge,
            "retrieval": retrieval,
        }, indent=2)
    else:
        output = format_improvement_report(dojo, forge, retrieval)

    print(output)

    if args.save:
        path = Path(args.save)
        if path.is_dir():
            path = path / f"pantheon-improvement-{datetime.now().strftime('%Y-%m-%d')}.md"
        path.write_text(output, encoding="utf-8")
        logger.info("Saved to %s", path)

    # --strict: staleness is a hard failure where it matters (cron). The report
    # itself never raises — it states the problem — but a scheduled run must not
    # exit 0 while reporting from a dead source.
    if args.strict:
        stale = [n for n, sec in (("dojo", dojo), ("forge", forge)) if sec.get("stale")]
        if stale:
            logger.error("stale source(s): %s", ", ".join(stale))
            sys.exit(2)
        logger.info("all sources fresh")


if __name__ == "__main__":
    main()
