"""Ichor Phase 4 — The Forge: Self-Adjusting Harness.

The Forge is the meta-learning loop for the RALPH gates. Patterned after
Phronesis (formerly Hermes Dojo): analyze → identify weakness → adjust → verify → report.

The Forge reads intervention logs from `~/.hermes/ichor/forge/all.jsonl`,
detects patterns (over-blocking gates, missing keywords, underused tools,
recurring failure modes), and produces structured adjustment patches.

This is NOT model fine-tuning. This is the harness learning from its own
experience — like a blacksmith reshaping a blade after seeing how it cuts.

Three components:
  - ForgeAnalyzer — reads logs, computes metrics, finds patterns
  - ForgeSmith — proposes and applies adjustments to gate configuration
  - ForgeReport — generates human-readable summaries

Adjustments the forge can make:
  1. Intent Injection keywords — add terms users frequently mention
  2. Phase Detection keywords — add/remove phase trigram patterns
  3. Phase Tool sets — add/remove tools per phase based on usage
  4. Logic Gate checks — add new syntax patterns from observed errors
  5. Intervention caps — adjust INTERVENTION_CAP based on block rates
"""

from __future__ import annotations

import collections
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Counter, Dict, List

logger = logging.getLogger("ichor_forge")

if __package__ in (None, ""):
    _repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)


def _pending_recommendation_path() -> Path:
    return Path(os.path.expanduser("~")) / ".hermes" / "clawforge" / "pending-recommendations.json"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FORGE_LOG_DIR = os.path.expanduser("~/.hermes/ichor/forge/")
COMBINED_LOG = os.path.join(FORGE_LOG_DIR, "all.jsonl")

# How far back to analyze (default: 7 days)
DEFAULT_LOOKBACK_DAYS = 7

# Minimum data points before the forge makes any adjustment
MIN_INTERVENTIONS_FOR_ADJUSTMENT = 10

# Gate names
STATE_GATE = "state_gate"
LOGIC_GATE = "logic_gate"
INTENT_GATE = "intent_injection_gate"
PHASE_GATE = "phase_detection_gate"
HANDOFF_GATE = "handoff_gate"

# ── Recurring-pattern prompt rules ────────────────────────────────
# Maps a recurring recovery_hint issue kind to a concrete god-system-prompt
# rule that should be added when the same kind appears >=3 times.
# Shared between ForgeAnalyzer.suggest_adjustments (CLI path) and
# ForgeSmith.evaluate (MCP path) — both call _recurring_pattern_adjustments.
PROMPT_RULES: Dict[str, Dict[str, Any]] = {
    "leftover print()": {
        "rule": (
            "Before responding, scan every file you wrote or modified. If "
            "a file contains function definitions (def/async def), remove "
            "any top-level print() calls (column-0 prints outside the "
            "if __name__ == '__main__' guard). Indented prints inside "
            "functions are fine."
        ),
        "affects": ["thoth", "hermes", "marvin", "hephaestus", "apollo"],
    },
    "bare 'except:'": {
        "rule": (
            "Never use bare `except:`. Always specify an exception type "
            "(e.g., `except Exception:` or `except SpecificError:`). Bare "
            "excepts swallow KeyboardInterrupt and SystemExit."
        ),
        "affects": ["thoth", "hermes", "marvin", "hephaestus"],
    },
    "JSON syntax error": {
        "rule": (
            "When writing JSON files (.json, package.json, tsconfig.json, "
            "etc.), validate with `python3 -c \"import json; json.load("
            "open(path))\"` or `node -e \"JSON.parse(require('fs')."
            "readFileSync(path))\"` before responding. Quote all string "
            "keys with double quotes."
        ),
        "affects": ["hermes", "thoth"],
    },
    "Python syntax error": {
        "rule": (
            "After writing any .py file, re-read it with the read_file "
            "tool before responding. Confirm it parses (`python3 -c "
            "'import ast; ast.parse(open(path).read())'`). If the file "
            "is large, read the section you just wrote."
        ),
        "affects": ["thoth", "hermes", "marvin", "hephaestus"],
    },
}


def _hint_kind(hint: str) -> str:
    """Normalize a recovery_hint to its issue kind, dropping line numbers,
    file paths, and trailing punctuation so trivial variations group together."""
    kind = hint.split("\n", 1)[0].strip()
    kind = re.sub(r"^Line\s+\d+(?:,\s*\d+)*:\s*", "", kind)
    kind = re.sub(r"\(line\s+\d+(?:,\s*\d+)*\)", "", kind)
    kind = re.sub(r"\s+at\s+line\s+\d+", "", kind, flags=re.IGNORECASE)
    kind = re.sub(r"\s+", " ", kind).strip(" .,:;")
    return kind[:80]


def _recurring_pattern_adjustments(
    records: List[InterventionRecord],
) -> List[ForgeAdjustment]:
    """Build god_system_prompt adjustments for recurring recovery_hint
    patterns. Returns [] if fewer than 3 occurrences of any known pattern.
    Used by both analyzer (CLI) and smith (MCP) so they produce the same
    adjustments — fixes the bug where MCP `forge --adjust` returned empty
    because the recurring-pattern logic only existed in suggest_adjustments.
    """
    if len(records) < MIN_INTERVENTIONS_FOR_ADJUSTMENT:
        return []
    hint_counter: Counter[str] = collections.Counter()
    for r in records:
        if not r.passed:
            kind = _hint_kind(r.recovery_hint)
            if kind:
                hint_counter[kind] += 1
    out: List[ForgeAdjustment] = []
    for kind, count in hint_counter.most_common(10):
        if count < 3:
            continue
        matched_rule = None
        matched_key = None
        for key, rule in PROMPT_RULES.items():
            if key in kind:
                matched_rule = rule
                matched_key = key
                break
        if matched_rule is None:
            continue
        out.append(ForgeAdjustment(
            target="god_system_prompt",
            action="add",
            item=matched_rule["rule"],
            reason=(
                f"Recurring '{matched_key}' ({count}x). "
                f"Affects: {', '.join(matched_rule['affects'])}."
            ),
            confidence=min(0.5 + count * 0.1, 0.95),
        ))
    return out

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class InterventionRecord:
    """A single parsed intervention from the forge log."""
    timestamp: float
    gate: str
    passed: bool
    message: str
    recovery_hint: str
    model: str
    session_id: str
    user_intent: str
    god: str = ""

    @property
    def datetime(self) -> str:
        return datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat()


@dataclass
class GateMetrics:
    """Metrics for a single gate over the analysis period."""
    gate_name: str
    total: int
    passed: int
    blocked: int
    block_rate: float  # 0.0-1.0
    top_block_messages: Counter[str]
    top_recovery_hints: Counter[str]
    top_models: Counter[str]
    top_intents: Counter[str]

    @property
    def is_over_blocking(self) -> bool:
        """Gate may be too aggressive if block rate > 60%."""
        return self.block_rate > 0.6

    @property
    def is_under_blocking(self) -> bool:
        """Gate may be too lenient if block rate < 5%."""
        return self.block_rate < 0.05 and self.total > 20


@dataclass
class ForgeFindings:
    """Complete analysis results from the forge."""
    analyzed_at: float
    total_interventions: int
    timespan_days: float
    models_seen: List[str]
    gates_seen: List[str]
    per_gate: Dict[str, GateMetrics]
    overall_block_rate: float
    detected_patterns: List[str] = field(default_factory=list)
    suggested_adjustments: List[str] = field(default_factory=list)
    # Source records (private to forge; lets ForgeSmith re-derive
    # adjustments without re-reading the JSONL log). Not serialized
    # when findings are passed via MCP.
    _records: List[Any] = field(default_factory=list, repr=False)


@dataclass
class ForgeAdjustment:
    """A single adjustment the forge proposes."""
    target: str  # e.g. "intent_keywords", "phase_keywords", "phase_tools", "logic_checks"
    action: str  # "add", "remove", "modify"
    item: str
    reason: str
    confidence: float  # 0.0-1.0


# ---------------------------------------------------------------------------
# ForgeAnalyzer — reads logs, computes metrics, finds patterns
# ---------------------------------------------------------------------------


class ForgeAnalyzer:
    """Analyzes forge intervention logs and produces structured findings.

    Usage:
        analyzer = ForgeAnalyzer()
        findings = analyzer.analyze(days=7)
        print(findings.overall_block_rate)
        for gate, metrics in findings.per_gate.items():
            print(f"{gate}: {metrics.block_rate:.0%} block rate")
    """

    def __init__(self, log_dir: str = FORGE_LOG_DIR):
        self.log_dir = log_dir
        self.combined_log = os.path.join(log_dir, "all.jsonl")

    def load_records(
        self, days: int = DEFAULT_LOOKBACK_DAYS,
        god: str = "",
    ) -> List[InterventionRecord]:
        """Load all intervention records within the lookback window.

        Args:
            days: Lookback window in days.
            god: If set, only return records for this god.
        """
        if not os.path.exists(self.combined_log):
            logger.info("Forge: no log file at %s", self.combined_log)
            return []

        cutoff = time.time() - (days * 86400)
        records: List[InterventionRecord] = []

        try:
            with open(self.combined_log) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    ts = entry.get("timestamp", 0)
                    if ts < cutoff:
                        continue

                    # Filter by god if specified
                    if god and entry.get("god", "") != god:
                        continue

                    records.append(InterventionRecord(
                        timestamp=ts,
                        gate=entry.get("gate", "unknown"),
                        passed=entry.get("passed", False),
                        message=entry.get("message", ""),
                        recovery_hint=entry.get("recovery_hint", ""),
                        model=entry.get("model", "unknown"),
                        session_id=entry.get("session_id", ""),
                        user_intent=entry.get("user_intent", ""),
                        god=entry.get("god", ""),
                    ))
        except (IOError, json.JSONDecodeError) as e:
            logger.warning("Forge: error reading log: %s", e)
            return []

        return records

    def compute_metrics(
        self, records: List[InterventionRecord],
    ) -> Dict[str, GateMetrics]:
        """Compute per-gate metrics from intervention records."""
        by_gate: Dict[str, List[InterventionRecord]] = {}
        for r in records:
            by_gate.setdefault(r.gate, []).append(r)

        metrics: Dict[str, GateMetrics] = {}
        for gate_name, gate_records in by_gate.items():
            total = len(gate_records)
            passed = sum(1 for r in gate_records if r.passed)
            blocked = total - passed
            block_rate = blocked / total if total > 0 else 0.0

            top_blocks: Counter[str] = collections.Counter()
            top_hints: Counter[str] = collections.Counter()
            top_models: Counter[str] = collections.Counter()
            top_intents: Counter[str] = collections.Counter()

            for r in gate_records:
                if not r.passed:
                    top_blocks[r.message[:100]] += 1
                    top_hints[r.recovery_hint[:100]] += 1
                top_models[r.model] += 1
                if r.user_intent:
                    top_intents[r.user_intent] += 1

            metrics[gate_name] = GateMetrics(
                gate_name=gate_name,
                total=total,
                passed=passed,
                blocked=blocked,
                block_rate=block_rate,
                top_block_messages=top_blocks,
                top_recovery_hints=top_hints,
                top_models=top_models,
                top_intents=top_intents,
            )

        return metrics

    def detect_patterns(
        self, records: List[InterventionRecord],
        metrics: Dict[str, GateMetrics],
    ) -> List[str]:
        """Detect patterns and anomalies in the intervention data."""
        patterns: List[str] = []

        if not records:
            return patterns

        # ── 1. Over-blocking gates ────────────────────────────────────
        for gate_name, gm in metrics.items():
            if gm.is_over_blocking:
                patterns.append(
                    f"⚠️ {gate_name} is over-blocking ({gm.block_rate:.0%} block rate "
                    f"on {gm.total} calls). Consider relaxing thresholds."
                )
            elif gm.is_under_blocking:
                patterns.append(
                    f"ℹ️ {gate_name} is under-blocking ({gm.block_rate:.0%} — "
                    f"only {gm.blocked} blocks in {gm.total} calls). Consider tightening."
                )

        # ── 2. Repeated same-path blocks ──────────────────────────────
        path_blocks: Counter[str] = collections.Counter()
        for r in records:
            if not r.passed and r.gate == STATE_GATE:
                # Extract file path from message like "write_file 'x.py' blocked"
                m = re.search(r"'([^']+)'", r.message)
                if m:
                    path_blocks[m.group(1)] += 1

        for path, count in path_blocks.most_common(3):
            if count >= 3:
                patterns.append(
                    f"🔁 Path '{path}' was blocked {count} times by State Gate. "
                    f"The model keeps writing without reading — consider adding "
                    f"to auto-read list or investigating why."
                )

        # ── 3. Frequent recovery hints ────────────────────────────────
        for gate_name, gm in metrics.items():
            if gm.top_recovery_hints:
                most_common_hint, hint_count = (
                    gm.top_recovery_hints.most_common(1)[0]
                )
                if hint_count >= 3:
                    patterns.append(
                        f"🔄 {gate_name}: recovery hint given {hint_count}x: "
                        f"\"{most_common_hint[:80]}...\""
                    )

        # ── 3b. Global recurring recovery-hint patterns ─────────────
        # Aggregates recovery_hint ISSUE TYPE (stripping line numbers and
        # file paths) across all gates and all models. Surfaces patterns
        # that are silently repeating regardless of which god/model
        # triggered them. Fixes the "leftover print() appears 9/17 times
        # but forge says nothing about it" bug — each unique line number
        # was its own pattern, so frequency was always 1. Stripping the
        # line number lets the issue kind aggregate.
        def _hint_kind(hint: str) -> str:
            """Normalize a recovery_hint to its issue kind, dropping line
            numbers, file paths, and trailing punctuation so trivial
            variations group together."""
            kind = hint.split("\n", 1)[0].strip()
            # Strip leading "Line N:" / "Line N,N:" / "(line N)" / "at line N"
            kind = re.sub(r"^Line\s+\d+(?:,\s*\d+)*:\s*", "", kind)
            kind = re.sub(r"\(line\s+\d+(?:,\s*\d+)*\)", "", kind)
            kind = re.sub(r"\s+at\s+line\s+\d+", "", kind, flags=re.IGNORECASE)
            # Collapse whitespace
            kind = re.sub(r"\s+", " ", kind).strip(" .,:;")
            return kind[:80]

        hint_pattern: Counter[str] = collections.Counter()
        hint_gods: Dict[str, Counter[str]] = collections.defaultdict(collections.Counter)
        hint_files: Dict[str, Counter[str]] = collections.defaultdict(collections.Counter)
        hint_example: Dict[str, str] = {}
        total_blocked = sum(1 for r in records if not r.passed)
        for r in records:
            if not r.passed:
                kind = _hint_kind(r.recovery_hint)
                if not kind:
                    continue
                hint_pattern[kind] += 1
                hint_gods[kind][r.god or "unknown"] += 1
                # First occurrence becomes the human-readable example
                if kind not in hint_example:
                    hint_example[kind] = r.recovery_hint.split("\n", 1)[0].strip()
                m = re.search(r"'([^']+)'", r.message)
                if m:
                    hint_files[kind][m.group(1)] += 1
        for kind, count in hint_pattern.most_common(5):
            if count < 3:
                continue
            pct = (count / total_blocked * 100) if total_blocked else 0
            affected_gods = ", ".join(
                f"{g}({c})" for g, c in hint_gods[kind].most_common(3)
            )
            example = hint_example[kind]
            # Map recurring patterns to concrete prompt-rule suggestions
            suggestion = ""
            if "leftover print()" in kind or "leftover print()" in example:
                suggestion = (
                    " Suggestion: strengthen god system prompts to require "
                    "removal of all top-level print() calls in files "
                    "containing function defs before responding."
                )
            elif "bare 'except:'" in kind or "bare except" in kind.lower():
                suggestion = (
                    " Suggestion: add to god prompts — 'use 'except "
                    "SpecificException:' or 'except Exception:', never bare "
                    "except:'."
                )
            elif "JSON syntax error" in kind or "JSON syntax error" in example:
                suggestion = (
                    " Suggestion: when emitting JSON, validate with json.loads "
                    "before responding."
                )
            elif "Python syntax error" in kind or "Python syntax error" in example:
                suggestion = (
                    " Suggestion: re-read the file you just wrote with read_file "
                    "before declaring it complete."
                )
            elif "unresolved marker" in kind or "TODO" in example or "FIXME" in example:
                suggestion = (
                    " Suggestion: resolve all TODO/FIXME/HACK/XXX before "
                    "responding, or note them explicitly in the response."
                )
            patterns.append(
                f"🚨 Recurring failure mode ({count}x / {pct:.0f}% of blocks): "
                f"\"{example}\". Affected gods: {affected_gods}.{suggestion}"
            )

        # ── 4. Model-specific patterns ────────────────────────────────
        model_blocks: Counter[str] = collections.Counter()
        for r in records:
            if not r.passed:
                model_blocks[r.model] += 1

        for model, count in model_blocks.most_common(3):
            total_for_model = sum(1 for r in records if r.model == model)
            rate = count / total_for_model if total_for_model > 0 else 0
            if rate > 0.5 and total_for_model >= 5:
                patterns.append(
                    f"📊 Model '{model}' has {rate:.0%} block rate "
                    f"({count}/{total_for_model}). This model may need "
                    f"adjusted gate thresholds or better instructions."
                )

        # ── 5. Missing intent keywords ────────────────────────────────
        all_intents: Counter[str] = collections.Counter()
        for r in records:
            if r.user_intent:
                all_intents[r.user_intent] += 1

        # Check for common words appearing in intents but not in keyword rules
        common_words = [
            "deploy", "release", "publish", "docker", "container",
            "migrate", "backup", "restore", "monitor", "log",
            "permission", "auth", "security", "cert", "ssl",
            "pipeline", "ci", "cd", "workflow",
        ]
        intent_text = " ".join(all_intents.keys()).lower()
        for word in common_words:
            if word in intent_text:
                from lib.ichor_gates import INTENT_INJECTION_RULES  # type: ignore
                if word not in INTENT_INJECTION_RULES:
                    patterns.append(
                        f"💡 Word '{word}' appears in user intents but "
                        f"isn't in Intent Injection keyword rules. Consider adding it."
                    )

        return patterns

    def suggest_adjustments(
        self, records: List[InterventionRecord],
        patterns: List[str],
    ) -> List[ForgeAdjustment]:
        """Propose specific adjustments based on detected patterns."""
        adjustments: List[ForgeAdjustment] = []

        if len(records) < MIN_INTERVENTIONS_FOR_ADJUSTMENT:
            return adjustments

        # Check for missing intent keywords
        intent_text = " ".join(
            r.user_intent for r in records if r.user_intent
        ).lower()

        try:
            from lib.ichor_gates import INTENT_INJECTION_RULES  # type: ignore
            missing_keywords = []
            for word in ["deploy", "docker", "monitor", "backup", "migrate",
                          "permission", "pipeline", "auth", "cert"]:
                if word in intent_text and word not in INTENT_INJECTION_RULES:
                    missing_keywords.append(word)

            if missing_keywords:
                for kw in missing_keywords[:3]:  # Top 3
                    adjustments.append(ForgeAdjustment(
                        target="intent_keywords",
                        action="add",
                        item=kw,
                        reason=f"'{kw}' appears in {intent_text.count(kw)} user intents",
                        confidence=0.7,
                    ))
        except ImportError:
            pass

        # ── Recurring recovery-hint prompt rules ───────────────────
        # Delegates to the module-level helper so the same logic runs in
        # both analyzer (CLI) and smith (MCP). See _recurring_pattern_adjustments.
        try:
            adjustments.extend(_recurring_pattern_adjustments(records))
        except Exception as e:
            logger.debug("ForgeAnalyzer: recurring-pattern scan failed: %s", e)

        # Check for model-specific issues
        model_counter: Counter[str] = collections.Counter()
        model_fails: Dict[str, int] = {}
        for r in records:
            model_counter[r.model] += 1
            if not r.passed:
                model_fails[r.model] = model_fails.get(r.model, 0) + 1

        for model, total in model_counter.most_common(5):
            fails = model_fails.get(model, 0)
            fails = model_fails.get(model, 0)
            if total >= 10 and fails / total > 0.5:
                adjustments.append(ForgeAdjustment(
                    target="model_thresholds",
                    action="modify",
                    item=model,
                    reason=f"{fails}/{total} interventions blocked ({fails/total:.0%})",
                    confidence=0.6,
                ))

        return adjustments

    def analyze(
        self, days: int = DEFAULT_LOOKBACK_DAYS,
        god: str = "",
    ) -> ForgeFindings:
        """Run full analysis pipeline: load → metrics → patterns → adjustments.

        Args:
            days: Lookback window in days.
            god: If set, only analyze data for this god.
        """
        records = self.load_records(days=days, god=god)
        metrics = self.compute_metrics(records)
        patterns = self.detect_patterns(records, metrics)

        # Compute overall stats
        total = len(records)
        blocked = sum(1 for r in records if not r.passed)
        overall_block_rate = blocked / total if total > 0 else 0.0

        models_seen = sorted(set(r.model for r in records))
        gates_seen = sorted(set(r.gate for r in records))

        # Compute timespan
        if records:
            ts_min = min(r.timestamp for r in records)
            ts_max = max(r.timestamp for r in records)
            timespan_days = (ts_max - ts_min) / 86400
        else:
            timespan_days = 0.0

        adjustments = self.suggest_adjustments(records, patterns)

        return ForgeFindings(
            analyzed_at=time.time(),
            total_interventions=total,
            timespan_days=timespan_days,
            models_seen=models_seen,
            gates_seen=gates_seen,
            per_gate=metrics,
            overall_block_rate=overall_block_rate,
            detected_patterns=patterns,
            suggested_adjustments=[
                f"{adj.action} {adj.item} to {adj.target} ({adj.reason})"
                for adj in adjustments
            ],
            # Stash records so ForgeSmith (MCP path) can re-derive
            # adjustments without re-reading the JSONL log. Skipped
            # from repr/serialization to avoid bloating MCP responses.
            _records=records,
        )


# ---------------------------------------------------------------------------
# ForgeSmith — applies adjustments to gate configuration
# ---------------------------------------------------------------------------


class ForgeSmith:
    """Reads forge findings and produces actionable changes.

    The smith doesn't edit files directly — it outputs structured patches
    that can be reviewed and applied. This matches the Phronesis pattern of
    "present findings, ask before applying."
    """

    def __init__(self):
        self._pending: List[ForgeAdjustment] = []

    def evaluate(self, findings: ForgeFindings) -> List[ForgeAdjustment]:
        """Evaluate findings and produce adjustment proposals."""
        adjustments: List[ForgeAdjustment] = []

        if findings.total_interventions < MIN_INTERVENTIONS_FOR_ADJUSTMENT:
            return adjustments

        # ── Recurring recovery-hint prompt rules ─────────────────────
        # Same logic as analyzer.suggest_adjustments — uses the
        # _recurring_pattern_adjustments helper with records stashed on
        # findings by analyze(). Fixes the MCP path producing empty
        # adjustments even when CLI path produced real ones.
        records = getattr(findings, "_records", None) or []
        if records:
            try:
                adjustments.extend(_recurring_pattern_adjustments(records))
            except Exception as e:
                logger.debug("ForgeSmith: recurring-pattern scan failed: %s", e)

        # ── Intent keyword additions ──────────────────────────────────
        try:
            from lib.ichor_gates import INTENT_INJECTION_RULES

            # Build a map of what users actually talk about
            intent_freq: Counter[str] = collections.Counter()
            if hasattr(findings, 'per_gate'):
                for gate_name, gm in findings.per_gate.items():
                    for intent in gm.top_intents:
                        for word in intent.lower().split():
                            intent_freq[word] += 1

            # Known useful keywords not yet in the rules
            candidates = {
                "deploy": ["Dockerfile", "docker-compose.yml", "deploy.yaml"],
                "docker": ["Dockerfile", ".dockerignore"],
                "monitor": ["prometheus.yaml", "grafana.json", "monitoring/"],
                "backup": ["backup.sh", "restore.sh"],
                "migrate": ["migration/", "alembic.ini"],
                "permission": [".env", "config.yaml"],
                "pipeline": [".github/workflows/", ".gitlab-ci.yml"],
            }

            for word, patterns in candidates.items():
                if word in intent_freq and word not in INTENT_INJECTION_RULES:
                    adjustments.append(ForgeAdjustment(
                        target="intent_keywords",
                        action="add",
                        item=word,
                        reason=(
                            f"Mentioned {intent_freq[word]}x in user intents"
                        ),
                        confidence=min(0.5 + intent_freq[word] * 0.1, 0.9),
                    ))
        except ImportError:
            pass

        # ── Phase detection keyword adjustments ───────────────────────
        # If a phase is never detected or rarely detected, suggest keywords
        for gate_name, gm in findings.per_gate.items():
            if (
                gate_name == PHASE_GATE
                and gm.total > 5
                and gm.passed / gm.total < 0.3
            ):
                adjustments.append(ForgeAdjustment(
                    target="phase_keywords",
                    action="modify",
                    item="Phase detection accuracy",
                    reason=f"Only {gm.passed}/{gm.total} phase detections were confident",
                    confidence=0.5,
                ))

        self._pending = adjustments
        return adjustments

    def get_pending(self) -> List[ForgeAdjustment]:
        if self._pending:
            return self._pending

        pending_path = _pending_recommendation_path()
        if not pending_path.exists():
            return []

        try:
            data = json.loads(pending_path.read_text())
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(data, list):
            return []

        pending: List[ForgeAdjustment] = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            if entry.get("type") != "model_threshold":
                continue
            patch = entry.get("patch") or {}
            target_name = str(patch.get("target", "model:unknown")).split("model:", 1)[-1]
            pending.append(
                ForgeAdjustment(
                    target="model_thresholds",
                    action="modify",
                    item=target_name,
                    reason=str(entry.get("summary") or patch.get("reason") or "pending model threshold"),
                    confidence=float(entry.get("confidence", 0.5)),
                )
            )
        self._pending = pending
        return self._pending

    def clear_pending(self) -> None:
        self._pending = []
        pending_path = _pending_recommendation_path()
        try:
            pending_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.debug("ForgeSmith: unable to remove pending file %s: %s", pending_path, e)

    def apply_adjustment(
        self, adj: ForgeAdjustment, dry_run: bool = True,
    ) -> Dict[str, Any]:
        """Apply a single adjustment. Returns result dict.

        In dry_run mode, returns what WOULD be done without doing it.
        """
        from lib.ichor_gates import (
            INTENT_INJECTION_RULES,
        )

        result = {
            "target": adj.target,
            "action": adj.action,
            "item": adj.item,
            "applied": False,
            "dry_run": dry_run,
            "detail": "",
        }

        if adj.target == "intent_keywords" and adj.action == "add":
            if adj.item not in INTENT_INJECTION_RULES:
                if dry_run:
                    result["detail"] = (
                        f"Would add '{adj.item}' to INTENT_INJECTION_RULES "
                        f"with patterns {['*.yaml', '*.json']}"
                    )
                    result["applied"] = True
                else:
                    result["detail"] = (
                        f"Apply requires manual patch: add '{adj.item}' to "
                        f"INTENT_INJECTION_RULES in lib/ichor_gates.py"
                    )
                    result["applied"] = False

        elif adj.target == "phase_keywords" and adj.action == "modify":
            if dry_run:
                result["detail"] = (
                    f"Would adjust PHASE_KEYWORDS to improve detection "
                    f"accuracy for {adj.item}"
                )
                result["applied"] = True
            else:
                result["detail"] = (
                    f"Manual review needed: PHASE_KEYWORDS adjustment for {adj.item}"
                )
                result["applied"] = False

        elif adj.target == "model_thresholds" and adj.action == "modify":
            cache_dir = _pending_recommendation_path().parent
            pending_path = cache_dir / "pending-recommendations.json"
            rec = {
                "pattern_id": f"forge-model-threshold-{adj.item}",
                "type": "model_threshold",
                "patch": {
                    "gate": "logic_gate",
                    "target": f"model:{adj.item}",
                    "reason": adj.reason,
                },
                "confidence": adj.confidence,
                "instances_validated": None,
                "summary": adj.reason,
            }
            if dry_run:
                result["detail"] = (
                    f"Would stage model_threshold recommendation at {pending_path} "
                    f"for {adj.item}"
                )
                result["applied"] = True
            else:
                try:
                    entries = []
                    if pending_path.exists():
                        try:
                            data = json.loads(pending_path.read_text())
                            if isinstance(data, list):
                                entries = data
                        except (OSError, json.JSONDecodeError):
                            entries = []
                    kept = [e for e in entries if e.get("pattern_id") != rec["pattern_id"]]
                    kept.append({**rec, "received_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "staged_reason": "forge_model_threshold"})
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    pending_path.write_text(json.dumps(kept, indent=2, sort_keys=True) + "\n")
                    result["detail"] = f"Staged model_threshold recommendation at {pending_path}"
                    result["applied"] = True
                except Exception as e:
                    result["detail"] = f"Failed to stage model_threshold recommendation: {e}"
                    result["applied"] = False

        elif adj.target == "god_system_prompt" and adj.action == "add":
            # Append the rule as a "## Code Quality Discipline" section
            # to each god SOUL.md that the rule applies to. PROMPT_RULES
            # holds the per-key "affects" list; fall back to all code
            # gods if no match.
            from pathlib import Path
            hermes_home = Path(os.path.expanduser("~")) / ".hermes"
            soul_files: List[Path] = []
            # Derive affected gods from reason text (format includes 'Affects: x, y')
            affected: List[str] = []
            for part in adj.reason.split("Affects:", 1):
                if part is adj.reason.split("Affects:", 1)[0]:
                    continue
                affected = [g.strip().rstrip(".") for g in part.split(",") if g.strip()]
            if not affected:
                affected = ["thoth", "hermes", "marvin", "hephaestus"]
            section_marker = "## Code Quality Discipline"
            snippet = (
                f"\n{section_marker} (auto-applied {datetime.now(timezone.utc).date().isoformat()})\n\n"
                f"{adj.item}\n"
            )
            for god_name in affected:
                # Map "default" hermes profile (live session) to top-level SOUL.md
                if god_name == "hermes":
                    soul = hermes_home / "SOUL.md"
                else:
                    soul = hermes_home / "profiles" / god_name / "SOUL.md"
                if not soul.exists():
                    continue
                try:
                    existing = soul.read_text()
                    if section_marker in existing:
                        # Already applied; skip silently
                        soul_files.append(soul)
                        continue
                    if dry_run:
                        result["detail"] += (
                            f"\n[dry-run] would append to {soul}"
                        )
                    else:
                        with soul.open("a") as f:
                            f.write(snippet)
                        result["detail"] += f"\nappended to {soul}"
                    soul_files.append(soul)
                except Exception as e:
                    result["detail"] += f"\nERROR writing {soul}: {e}"
            result["applied"] = not dry_run and bool(soul_files)

        return result

    def generate_patch_script(self, adjustments: List[ForgeAdjustment]) -> str:
        """Generate a shell script that applies all adjustments."""
        lines = [
            "#!/usr/bin/env bash",
            "# Forge adjustment patch script",
            f"# Generated: {datetime.now(timezone.utc).isoformat()}",
            f"# Adjustments: {len(adjustments)}",
            "",
            "set -e",
            "",
        ]

        for adj in adjustments:
            if adj.target == "intent_keywords" and adj.action == "add":
                lines.append(
                    f"# {adj.reason}"
                )
                lines.append(
                    f"# Would add keyword '{adj.item}' to INTENT_INJECTION_RULES"
                )
                lines.append("")
            elif adj.target == "model_thresholds" and adj.action == "modify":
                lines.append(f"# {adj.reason}")
                lines.append(
                    f"# Would stage a model_threshold recommendation for {adj.item} "
                    f"in ~/.hermes/clawforge/pending-recommendations.json"
                )
                lines.append("")
            elif adj.target == "god_system_prompt" and adj.action == "add":
                lines.append(f"# {adj.reason}")
                lines.append(f"# Would append to god SOUL.md:\n#\n# {adj.item}")
                lines.append("")

        lines.append("echo 'Review the above and apply with: patch --mode replace ...'")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# ForgeReport — generates human-readable summaries
# ---------------------------------------------------------------------------


class ForgeReport:
    """Generate human-readable reports from forge analysis."""

    @staticmethod
    def text(findings: ForgeFindings, detailed: bool = False) -> str:
        """Generate a plain-text report from forge findings."""
        lines: List[str] = []
        lines.append("🔨 **The Forge — Harness Analysis Report**")
        lines.append("")

        # Header
        ts = datetime.fromtimestamp(
            findings.analyzed_at, tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M UTC")
        lines.append(f"Analyzed: {ts}")
        lines.append(
            f"Timespan: {findings.timespan_days:.1f} days"
            if findings.timespan_days > 0
            else "Timespan: no data"
        )
        lines.append(
            f"Interventions: {findings.total_interventions}"
        )
        lines.append(
            f"Overall block rate: {findings.overall_block_rate:.1%}"
        )
        if findings.models_seen:
            lines.append(
                f"Models: {', '.join(findings.models_seen)}"
            )
        if findings.gates_seen:
            lines.append(
                f"Gates active: {', '.join(findings.gates_seen)}"
            )
        lines.append("")

        # Per-gate breakdown
        if findings.per_gate:
            lines.append("**Per-Gate Metrics:**")
            for gate_name in sorted(findings.per_gate.keys()):
                gm = findings.per_gate[gate_name]
                bar = "█" * int(gm.block_rate * 20) + "░" * (
                    20 - int(gm.block_rate * 20)
                )
                lines.append(
                    f"  • {gate_name}: {gm.total} calls, "
                    f"{gm.blocked} blocked ({gm.block_rate:.0%}) "
                    f"{bar}"
                )
                if detailed and gm.top_block_messages:
                    lines.append("    Top blocks:")
                    for msg, count in gm.top_block_messages.most_common(3):
                        lines.append(f"      {count}x: {msg[:80]}")
            lines.append("")

        # Patterns
        if findings.detected_patterns:
            lines.append("**Detected Patterns:**")
            for p in findings.detected_patterns:
                lines.append(f"  • {p}")
            lines.append("")

        # Suggested adjustments
        if findings.suggested_adjustments:
            lines.append("**Suggested Adjustments:**")
            for s in findings.suggested_adjustments:
                lines.append(f"  • {s}")
            lines.append("")

        if findings.total_interventions == 0:
            lines.append(
                "_No intervention data yet. The forge needs at least "
                f"{MIN_INTERVENTIONS_FOR_ADJUSTMENT} interventions before "
                "making adjustments._"
            )
            lines.append("")

        lines.append(
            "`python3 lib/ichor_forge.py --adjust` to review and apply"
        )

        return "\n".join(lines)

    @staticmethod
    def short_status(findings: ForgeFindings) -> str:
        """One-line status summary."""
        if findings.total_interventions == 0:
            return "🔨 Forge: idle (no data yet)"

        gates_active = len(findings.gates_seen)
        patterns = len(findings.detected_patterns)
        adjustments = len(findings.suggested_adjustments)

        return (
            f"🔨 Forge: {findings.total_interventions} interventions "
            f"across {gates_active} gates | "
            f"{findings.overall_block_rate:.0%} block rate | "
            f"{patterns} patterns | "
            f"{adjustments} adjustments suggested"
        )


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI for running forge analysis and adjustments."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Ichor Phase 4 — The Forge: Self-Adjusting Harness"
    )
    parser.add_argument(
        "--analyze", action="store_true",
        help="Run forge analysis on intervention logs",
    )
    parser.add_argument(
        "--days", type=int, default=DEFAULT_LOOKBACK_DAYS,
        help=f"Lookback window in days (default: {DEFAULT_LOOKBACK_DAYS})",
    )
    parser.add_argument(
        "--god", type=str, default="",
        help="Filter by god name (e.g. 'hermes', 'apollo')",
    )
    parser.add_argument(
        "--adjust", action="store_true",
        help="Evaluate findings and propose adjustments",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Apply pending adjustments (requires --adjust first)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Show what would be changed without changing (default: True)",
    )
    parser.add_argument(
        "--no-dry-run", action="store_false", dest="dry_run",
        help="Actually apply changes",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output findings as JSON",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Quick status summary",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    analyzer = ForgeAnalyzer()
    smith = ForgeSmith()
    report = ForgeReport()

    # ── Status ────────────────────────────────────────────────────────
    if args.status or not any([args.analyze, args.adjust, args.apply]):
        findings = analyzer.analyze(days=args.days, god=args.god)
        print(report.short_status(findings))
        return

    # ── Analyze ────────────────────────────────────────────────────────
    if args.analyze:
        findings = analyzer.analyze(days=args.days, god=args.god)

        if args.json:
            # Manual dict conversion: dataclasses.asdict() in Py3.14 mangles
            # Counter objects into Counter({(key, val): 1}) tuples.
            def _to_dict(obj):
                if isinstance(obj, collections.Counter):
                    return dict(obj)
                if hasattr(obj, '__dataclass_fields__'):
                    result = {}
                    for f in dataclasses.fields(obj):
                        val = getattr(obj, f.name)
                        result[f.name] = _to_dict(val)
                    return result
                if isinstance(obj, dict):
                    return {k: _to_dict(v) for k, v in obj.items()}
                if isinstance(obj, (list, tuple)):
                    return [_to_dict(v) for v in obj]
                return obj
            import dataclasses
            print(json.dumps(_to_dict(findings), indent=2, default=str))
        else:
            print(report.text(findings, detailed=True))

    # ── Adjust ────────────────────────────────────────────────────────
    if args.adjust:
        findings = analyzer.analyze(days=args.days)
        adjustments = smith.evaluate(findings)

        if not adjustments:
            print("No adjustments proposed — not enough data or no issues found.")
            return

        print(f"Proposed {len(adjustments)} adjustments:\n")
        for adj in adjustments:
            confidence_bar = "●" * int(adj.confidence * 10) + "○" * (
                10 - int(adj.confidence * 10)
            )
            print(f"  [{confidence_bar}] {adj.action.upper()} {adj.item}")
            print(f"         Target: {adj.target}")
            print(f"         Reason: {adj.reason}")
            if adj.target == "model_thresholds":
                print(
                    f"         Pending file: {_pending_recommendation_path()}"
                )
            print()

        print(f"Review with '--apply --no-dry-run' to commit.")

    # ── Apply ──────────────────────────────────────────────────────────
    if args.apply:
        adjustments = smith.get_pending()
        if not adjustments:
            findings = analyzer.analyze(days=args.days)
            adjustments = smith.evaluate(findings)

        if not adjustments:
            print("No adjustments to apply.")
            return

        for adj in adjustments:
            result = smith.apply_adjustment(adj, dry_run=args.dry_run)
            status = "🔍 Would apply" if result["dry_run"] else "✅ Applied"
            print(f"{status}: {result['detail']}")
            if adj.target == "model_thresholds":
                print(
                    f"         Pending file: {_pending_recommendation_path()}"
                )

        if args.dry_run:
            print("\nRe-run with --no-dry-run to apply.")


if __name__ == "__main__":
    main()
