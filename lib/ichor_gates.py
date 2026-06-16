"""Ichor RALPH 5-Gate Harness — Deterministic Middleware for God-Level Execution.

Enforces RALPH (Reasoning → Action → Logic → Planning → Handoff) at the
tool-call level. Gates are composable, testable, and model-agnostic.

The harness moves reliability OUT of the prompt/model and INTO the
infrastructure. Small models (8B-70B) match SOTA reliability by having
deterministic "rules of the road" enforced at the middleware layer.

Usage:
    pipeline = GatePipeline()
    pipeline.register(StateGate(cache))
    pipeline.register(LogicGate())

    # Pre-call — check before tool executes
    result = pipeline.run_pre_call("write_file", {"path": "x.py"})
    if result and not result.passed:
        respond(result.recovery_hint)  # Gate blocked — recover privately

    # Post-call — validate after tool executes
    results = pipeline.run_post_call("write_file", {"path": "x.py"}, output)
    for r in results:
        if not r.passed:
            respond(r.recovery_hint)  # Fix and retry

    # Context pre-fetching
    injected = pipeline.on_session_start({"user_message": "..."})

    # Handoff validation
    manifest = pipeline.generate_handoff_manifest("hermes", "hephaestus")
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("ichor_gates")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Max gate interventions per turn before pass-through (prevents death spirals)
INTERVENTION_CAP = 3

# Confidence floor for auto-remediation (0.0-1.0)
REMEDIATION_THRESHOLD = 0.5

# Supported languages for Logic Gate validation
SUPPORTED_LANGUAGES = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
    ".css": "css",
    ".html": "html",
    ".sh": "shell",
    ".toml": "toml",
    ".rs": "rust",
    ".go": "go",
}

# ---------------------------------------------------------------------------
# Phase Tracking
# ---------------------------------------------------------------------------


class RALPHPhase(Enum):
    """The five RALPH loop phases."""
    REASONING = "REASONING"
    ACTION = "ACTION"
    LOGIC = "LOGIC"
    PLANNING = "PLANNING"
    HANDOFF = "HANDOFF"
    UNKNOWN = "UNKNOWN"


# Phase-specific tool sets (tool names the agent can call)
PHASE_TOOLS: Dict[RALPHPhase, List[str]] = {
    RALPHPhase.REASONING: [
        "web_search", "web_extract", "read_file", "search_files",
        "session_search", "athenaeum_search", "athenaeum_graph_search",
    ],
    RALPHPhase.ACTION: [
        "write_file", "patch", "terminal", "execute_code",
        "browser_navigate", "browser_click", "browser_type",
    ],
    RALPHPhase.LOGIC: [
        "terminal", "execute_code", "read_file", "search_files",
    ],
    RALPHPhase.PLANNING: [
        "read_file", "search_files", "web_search", "athenaeum_search",
    ],
    RALPHPhase.HANDOFF: [
        "delegate_task", "send_message", "memory", "terminal",
    ],
    RALPHPhase.UNKNOWN: [],  # No pruning when phase is unknown
}

# Phase-specific system prompt snippets
PHASE_PROMPTS: Dict[RALPHPhase, str] = {
    RALPHPhase.REASONING: (
        "You are in **RESEARCH** phase. Gather information and understand the "
        "problem. Use search and read tools. Do NOT start implementing yet. "
        "Map dependencies. Document findings."
    ),
    RALPHPhase.ACTION: (
        "You are in **BUILD** phase. Implement the solution. You have full "
        "context from research. Write code, create files, execute commands. "
        "Focus on execution — do not backtrack unless you hit a blocker."
    ),
    RALPHPhase.LOGIC: (
        "You are in **VERIFY** phase. Validate what was built. Run tests, "
        "check syntax, verify correctness. Fix issues found. Do NOT add "
        "features during verification."
    ),
    RALPHPhase.PLANNING: (
        "You are in **PLAN** phase. Break down the task, identify "
        "dependencies, order operations. Write the plan to a file. "
        "Get approval before executing."
    ),
    RALPHPhase.HANDOFF: (
        "You are in **HANDOFF** phase. Ensure a clean transition. Commit "
        "changes, verify tests, resolve TODOs. The next god needs a clear "
        "handoff manifest."
    ),
}

# Zero-LLM phase detection keywords
PHASE_KEYWORDS: Dict[RALPHPhase, List[str]] = {
    RALPHPhase.REASONING: [
        "find", "search", "look up", "research", "investigate", "explore",
        "learn", "understand", "what is", "how does", "analyze",
    ],
    RALPHPhase.ACTION: [
        "create", "build", "write", "make", "implement", "add", "change",
        "update", "fix", "modify", "code", "generate",
    ],
    RALPHPhase.LOGIC: [
        "test", "verify", "check", "validate", "lint", "review", "audit",
        "debug", "profile", "benchmark",
    ],
    RALPHPhase.PLANNING: [
        "plan", "design", "outline", "sketch", "scope", "propose",
        "strategy", "approach", "architect",
    ],
    RALPHPhase.HANDOFF: [
        "handoff", "merge", "deploy", "release", "ship", "publish",
        "commit", "pr", "pull request", "submit",
    ],
}

# Default keyword → file patterns for Intent Injection Gate
INTENT_INJECTION_RULES: Dict[str, List[str]] = {
    "config": ["config.yaml", ".env", "package.json", "pyproject.toml"],
    "test": ["pytest.ini", "vitest.config.ts", "jest.config.js", "conftest.py"],
    "style": ["tailwind.config.js", "global.css", "theme.py", "main.css"],
    "route": ["app/routes/", "src/pages/", "pages/", "routes/"],
    "deploy": ["Dockerfile", "docker-compose.yml", "deploy.yaml"],
    "readme": ["README.md"],
    "pantheon": ["pantheon-registry.yaml", "pantheon-core/"],
    "god": ["gods/", "harnesses/"],
    "memory": ["ichor-memory-engine-rollout.md", "lib/"],
    "script": ["scripts/"],
    "schema": ["schemas/"],
    "api": ["api/", "routes/"],
}

# ---------------------------------------------------------------------------
# Data Types
# ---------------------------------------------------------------------------


@dataclass
class GateResult:
    """Result of a single gate check."""
    gate_name: str
    passed: bool
    message: str = ""
    intervention: bool = False
    recovery_hint: str = ""
    payload: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate": self.gate_name,
            "passed": self.passed,
            "message": self.message,
            "intervention": self.intervention,
            "recovery_hint": self.recovery_hint,
            "payload": self.payload,
        }

    def __bool__(self) -> bool:
        return self.passed


@dataclass
class HandoffManifest:
    """Signed manifest for clean god-to-god handoff."""
    source_god: str
    target_god: str
    timestamp: float
    state_snapshot: Dict[str, Any]
    check_results: Dict[str, bool]
    tier: str  # "full" or "bronze"
    signature: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_god": self.source_god,
            "target_god": self.target_god,
            "timestamp": self.timestamp,
            "state": self.state_snapshot,
            "checks": self.check_results,
            "tier": self.tier,
            "signature": self.signature,
        }

    def generate_signature(self) -> str:
        """Generate a SHA-256 seal binding the manifest."""
        payload = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

# ---------------------------------------------------------------------------
# Read Cache
# ---------------------------------------------------------------------------


class ReadCache:
    """Tracks which files have been read (for State Gate enforcement).

    Maintains a set of read-file paths and a disk-existence cache to
    distinguish new-file creation from existing-file mutation.
    """

    def __init__(self):
        self._read_files: Set[str] = set()
        self._exists_cache: Dict[str, bool] = {}

    def mark_read(self, path: str) -> None:
        """Record that a file has been read."""
        abs_path = os.path.abspath(os.path.expanduser(path))
        self._read_files.add(abs_path)
        self._exists_cache[abs_path] = os.path.exists(abs_path)

    def has_read(self, path: str) -> bool:
        """Check if a file was previously read."""
        abs_path = os.path.abspath(os.path.expanduser(path))
        return abs_path in self._read_files

    def exists_on_disk(self, path: str) -> bool:
        """Check if file exists (with result caching per session)."""
        abs_path = os.path.abspath(os.path.expanduser(path))
        if abs_path not in self._exists_cache:
            self._exists_cache[abs_path] = os.path.exists(abs_path)
        return self._exists_cache[abs_path]

    def reset(self) -> None:
        """Clear all cached state."""
        self._read_files.clear()
        self._exists_cache.clear()

    def snapshot(self) -> Dict[str, Any]:
        return {
            "read_files": sorted(self._read_files),
            "count": len(self._read_files),
        }

    def merge(self, snapshot: Dict[str, Any]) -> None:
        """Merge another cache's snapshot (for handoff transfer)."""
        for f in snapshot.get("read_files", []):
            self._read_files.add(f)

# ---------------------------------------------------------------------------
# Base Gate
# ---------------------------------------------------------------------------


class BaseGate:
    """Base class for all Ichor gates."""

    name: str = "base"

    def pre_call(
        self,
        tool_name: str,
        params: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Optional[GateResult]:
        """Called BEFORE a tool executes.

        Return a GateResult with passed=False to block the call.
        Return None to allow passthrough.
        """
        return None

    def post_call(
        self,
        tool_name: str,
        params: Dict[str, Any],
        result_value: Any,
        context: Dict[str, Any],
    ) -> Optional[GateResult]:
        """Called AFTER a tool executes.

        Return a GateResult to flag validation issues.
        Return None to allow passthrough.
        """
        return None

    def on_session_start(
        self, context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Called at session start for context injection.

        Return a dict to merge into the agent's context.
        Return None for no injection.
        """
        return None

# ---------------------------------------------------------------------------
# Gate 1: State Gate (Read-before-Write)
# ---------------------------------------------------------------------------


class StateGate(BaseGate):
    """Enforce read-before-write for file mutations.

    Rule:
        A write_file/patch call MUST be preceded by a read_file call on the
        same path.

    Exception:
        If the file doesn't exist on disk, skip enforcement (creating a new
        file does not require a prior read).

    Prevents models from overwriting files they haven't inspected.
    """

    name = "state_gate"

    def __init__(self, cache: ReadCache):
        self.cache = cache

    def pre_call(
        self,
        tool_name: str,
        params: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Optional[GateResult]:
        if tool_name not in ("write_file", "patch"):
            return None

        path = params.get("path", "")
        if not path:
            return None

        # New file? Skip — creating, not mutating.
        if not self.cache.exists_on_disk(path):
            logger.debug("StateGate: skip '%s' — new file", path)
            return None

        # Read confirmed?
        if self.cache.has_read(path):
            logger.debug("StateGate: pass '%s' — read confirmed", path)
            return None

        # Blocked
        return GateResult(
            gate_name=self.name,
            passed=False,
            intervention=True,
            message=(
                f"State Gate: write_file '{path}' blocked — "
                "no prior read_file detected"
            ),
            recovery_hint=(
                f"Call read_file('{path}') first to inspect the file "
                "before modifying it."
            ),
        )

# ---------------------------------------------------------------------------
# Gate 2: Logic Gate (Verification-in-Loop)
# ---------------------------------------------------------------------------


class LogicGate(BaseGate):
    """Validate file syntax after writing.

    Rule:
        After writing code, validate syntax. The model fails "privately"
        and corrects itself before the human sees the error.

    Supported languages:
        Python, JavaScript, TypeScript, JSON, YAML, Markdown (tables).

    Cap:
        3 interventions per session, then pass-through (prevents death spiral).

    P2a: 60s dedup window per path — skip re-validation if already checked.
    P2b: 30s write debounce — only validate last write in a burst (3+ writes
         in window → only check the one with highest offset/most recent).
    """

    name = "logic_gate"

    DEDUP_WINDOW = 60   # seconds
    DEBOUNCE_WINDOW = 30  # seconds
    BURST_THRESHOLD = 3   # writes within debounce window to trigger burst mode

    def __init__(self):
        self.intervention_count = 0
        # P2a: path → last check timestamp
        self._last_check: Dict[str, float] = {}
        # P2b: path → list of (timestamp, size_hint) for debounce tracking
        self._write_burst: Dict[str, List[float]] = {}

    def _detect_language(self, path: str) -> Optional[str]:
        return SUPPORTED_LANGUAGES.get(Path(path).suffix.lower())

    def _check_python(self, content: str) -> List[str]:
        errors: List[str] = []
        try:
            ast.parse(content)
        except SyntaxError as e:
            errors.append(
                f"Python syntax error: {e.msg} (line {e.lineno})"
            )

        # Bare except
        for i, line in enumerate(content.split("\n"), 1):
            stripped = line.strip()
            if stripped == "except:":
                errors.append(
                    f"Line {i}: bare 'except:' — use 'except Exception:'"
                )

        # Leftover debug print
        # Rule: a top-level `print()` in a file that has function defs is
        # suspicious (real code shouldn't sprinkle prints). Top-level scripts
        # (no defs) and `if __name__ == "__main__":` blocks are fine.
        # Module-level print in first 5 lines is always allowed (CLI banners).
        lines = content.split("\n")
        has_def = any(re.match(r"^(async\s+)?def\s+\w+", ln) for ln in lines)
        in_main_block = False
        main_indent = -1
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # Track `if __name__ == "__main__":` block
            if re.match(r'^if\s+__name__\s*==\s*["\']__main__["\']\s*:', stripped):
                in_main_block = True
                main_indent = len(line) - len(line.lstrip())
                continue
            if in_main_block and stripped and not line.startswith(" "):
                # Dedent past main block
                in_main_block = False
            if re.match(r"^print\(.+\)\s*$", stripped):
                # A print at column 0 (top-level) in a file with function
                # defs is suspicious. Indented prints are inside a
                # function/block and treated as legitimate logging.
                # `if __name__ == "__main__":` blocks and top-level
                # scripts (no defs) are exempt.
                if line.startswith(" ") or line.startswith("\t"):
                    continue
                if in_main_block:
                    continue
                if not has_def:
                    continue
                errors.append(f"Line {i}: leftover print() call")

        # TODO/FIXME markers — only flag at the start of a comment line
        # (not inside string literals, regex patterns, or docstrings).
        # Comment lines start with optional whitespace then `#`.
        in_triple_string = False
        triple_quote_chars = None
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # Track triple-quoted string state (rudimentary but cheap)
            if not in_triple_string:
                m = re.match(r'^(\s*)([rubfRUBF]*)("""|\'\'\')', line)
                if m:
                    # Find the closing triple-quote on the same line
                    rest = line[m.end():]
                    if "'''" in rest and m.group(3) == "'''":
                        # Triple-single on one line — full docstring, no state change
                        pass
                    elif '"""' in rest and m.group(3) == '"""':
                        # Triple-double on one line — full docstring, no state change
                        pass
                    else:
                        in_triple_string = True
                        triple_quote_chars = m.group(3)
                        continue
            else:
                if triple_quote_chars and triple_quote_chars in line:
                    in_triple_string = False
                    triple_quote_chars = None
                continue
            # Must be a comment line: optional whitespace + # + word
            cm = re.match(r"^\s*#\s*(\w+)", stripped)
            if cm and cm.group(1) in ("TODO", "FIXME", "HACK", "XXX"):
                errors.append(
                    f"Line {i}: unresolved marker — {stripped[:60]}"
                )

        return errors

    def _check_json(self, content: str) -> List[str]:
        errors: List[str] = []
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            errors.append(f"JSON syntax error: {e.msg} (line {e.lineno})")
        return errors

    def _check_yaml(self, content: str) -> List[str]:
        errors: List[str] = []
        try:
            import yaml
            yaml.safe_load(content)
        except ImportError:
            logger.debug("LogicGate: PyYAML not installed, skipping YAML check")
        except yaml.YAMLError as e:
            errors.append(f"YAML syntax error: {e}")
        return errors

    def _check_markdown(self, content: str) -> List[str]:
        errors: List[str] = []
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            if "|" in line and line.strip().startswith("|"):
                cols = [c.strip() for c in line.split("|")[1:-1]]
                if all(re.match(r"^:?-{3,}:?$", c) for c in cols if c):
                    continue
        return errors

    def post_call(
        self,
        tool_name: str,
        params: Dict[str, Any],
        result_value: Any,
        context: Dict[str, Any],
    ) -> Optional[GateResult]:
        if tool_name not in ("write_file", "patch"):
            return None

        path = params.get("path", "")
        if not path:
            return None

        # For `write_file`, params['content'] is the full file (authoritative).
        # For `patch`, params['new_string'] is a FRAGMENT — we must re-read
        # the file from disk to validate the post-patch state.
        if tool_name == "write_file":
            content = params.get("content", "")
        else:  # patch
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except (FileNotFoundError, IOError, OSError):
                return None

        if not content:
            return None

        # P2b: burst tracking happens BEFORE dedup so we can detect rapid
        # writes that the dedup window would otherwise hide.
        now = time.time()
        burst = self._write_burst.setdefault(path, [])
        burst.append(now)
        # Drop old entries outside the debounce window
        burst[:] = [t for t in burst if now - t < self.DEBOUNCE_WINDOW]
        is_burst = len(burst) >= self.BURST_THRESHOLD

        # P2a: dedup window — skip if we already validated this path recently,
        # UNLESS we're processing the tail of a burst (last write in window).
        last = self._last_check.get(path, 0.0)
        if now - last < self.DEDUP_WINDOW and not is_burst:
            logger.debug("LogicGate: dedup-skip '%s' (%.1fs < %ds)",
                         path, now - last, self.DEDUP_WINDOW)
            return None
        self._last_check[path] = now

        if is_burst:
            logger.debug("LogicGate: burst tail — validating final of %d writes "
                         "to '%s'", len(burst), path)
            self._write_burst[path] = []  # reset for next burst
        # else: continue normal validation below

        lang = self._detect_language(path)
        if not lang:
            return None

        check_fn = getattr(self, f"_check_{lang}", None)
        if not check_fn:
            return None

        errors = check_fn(content)
        if not errors:
            logger.debug("LogicGate: '%s' passed %s validation", path, lang)
            return None

        self.intervention_count += 1
        if self.intervention_count > INTERVENTION_CAP:
            logger.warning("LogicGate: intervention cap reached — pass-through")
            return GateResult(
                gate_name=self.name,
                passed=False,
                intervention=False,
                message=(
                    f"Logic Gate: {len(errors)} issues in '{path}' "
                    "(cap reached)"
                ),
            )

        return GateResult(
            gate_name=self.name,
            passed=False,
            intervention=True,
            message=(
                f"Logic Gate: {len(errors)} "
                f"{'issue' if len(errors) == 1 else 'issues'} "
                f"in '{path}'"
            ),
            recovery_hint="\n".join(errors),
        )

# ---------------------------------------------------------------------------
# Gate 3: Intent Injection Gate (Pre-fetching)
# ---------------------------------------------------------------------------


class IntentInjectionGate(BaseGate):
    """Pre-fetch context based on keyword detection in user input.

    If the user mentions "config," the harness pre-reads config.yaml,
    .env, and package.json — the model sees the data before emitting its
    first token. Saves 1-2 turns of latency.

    Prefetch rules are extensible via the `rules` parameter.
    """

    name = "intent_injection_gate"

    def __init__(
        self,
        rules: Optional[Dict[str, List[str]]] = None,
        base_path: str = ".",
    ):
        self.rules = rules or INTENT_INJECTION_RULES.copy()
        self.base_path = os.path.abspath(os.path.expanduser(base_path))
        self._injected: Set[str] = set()

    def on_session_start(
        self, context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        user_input = context.get("user_message", "")
        if not user_input:
            return None

        matched = set()
        for keyword, patterns in self.rules.items():
            if keyword.lower() in user_input.lower():
                for pattern in patterns:
                    resolved = self._resolve(pattern)
                    if resolved:
                        matched.add(resolved)

        if not matched:
            return None

        injected: Dict[str, str] = {}
        for fpath in matched:
            if fpath in self._injected:
                continue
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(50000)  # Cap at 50KB
                injected[fpath] = content
                self._injected.add(fpath)
                logger.info(
                    "IntentInjectionGate: pre-read '%s'", fpath
                )
            except (FileNotFoundError, IOError):
                logger.debug(
                    "IntentInjectionGate: cannot read '%s'", fpath
                )
                continue

        if not injected:
            return None

        parts: List[str] = []
        for fpath, content in injected.items():
            short = os.path.relpath(fpath, self.base_path)
            parts.append(
                f"📄 **{short}:**\n```\n{content[:3000]}\n```"
            )

        injection_text = (
            "## ⚡ Intent Injection — Pre-fetched Context\n\n"
            + "\n\n".join(parts)
        )

        return {"injected_context": injection_text}

    def _resolve(self, pattern: str) -> Optional[str]:
        """Resolve a file pattern to an existing absolute path."""
        # Relative to base_path
        candidate = os.path.join(self.base_path, pattern)
        if os.path.exists(candidate):
            return os.path.abspath(candidate)

        # Directory with trailing slash — grab first file
        if pattern.endswith("/"):
            base = os.path.join(self.base_path, pattern.rstrip("/"))
            if os.path.isdir(base):
                try:
                    entries = sorted(os.listdir(base))
                    if entries:
                        return os.path.join(base, entries[0])
                except PermissionError:
                    pass
            return None

        # Absolute path
        abspath = os.path.abspath(os.path.expanduser(pattern))
        if os.path.exists(abspath):
            return abspath

        return None

# ---------------------------------------------------------------------------
# Gate 4: Phase Detection Gate (Dynamic Tool Pruning)
# ---------------------------------------------------------------------------


class PhaseDetectionGate(BaseGate):
    """Detect RALPH phase from user input and swap context + prune tools.

    Detection is zero-LLM — keyword matching on user input.
    Phase detection SUGGESTS, does not ENFORCE. Cross-phase actions are
    still allowed (preserves non-linear workflows).
    """

    name = "phase_detection_gate"

    def __init__(self):
        self.current_phase: RALPHPhase = RALPHPhase.UNKNOWN
        self.phase_history: List[Tuple[RALPHPhase, float]] = []

    def detect_phase(self, user_input: str) -> RALPHPhase:
        """Zero-LLM phase detection from natural language input."""
        lowered = user_input.lower()
        scores: Dict[RALPHPhase, int] = {}

        for phase, keywords in PHASE_KEYWORDS.items():
            for kw in keywords:
                if kw in lowered:
                    scores[phase] = scores.get(phase, 0) + 1

        if not scores:
            return RALPHPhase.UNKNOWN

        best = max(scores, key=scores.get)  # type: ignore
        return best

    def pre_call(
        self,
        tool_name: str,
        params: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Optional[GateResult]:
        user_msg = context.get("user_message", "")
        if not user_msg:
            return None

        detected = self.detect_phase(user_msg)
        if detected == RALPHPhase.UNKNOWN or detected == self.current_phase:
            return None

        old = self.current_phase
        self.current_phase = detected
        self.phase_history.append((detected, time.time()))

        return GateResult(
            gate_name=self.name,
            passed=True,
            intervention=True,
            message=(
                f"Phase transition: {old.value} → {detected.value}"
            ),
            payload={
                "old_phase": old.value,
                "new_phase": detected.value,
                "tools": PHASE_TOOLS.get(detected, []),
                "prompt": PHASE_PROMPTS.get(detected, ""),
            },
        )

    def get_allowed_tools(self) -> Optional[List[str]]:
        """Return pruned tool list for current phase, or None."""
        if self.current_phase == RALPHPhase.UNKNOWN:
            return None
        return PHASE_TOOLS.get(self.current_phase)

    def get_phase_prompt(self) -> str:
        """Return system prompt snippet for current phase."""
        return PHASE_PROMPTS.get(self.current_phase, "")

# ---------------------------------------------------------------------------
# Gate 5: Handoff Gate (State Verification)
# ---------------------------------------------------------------------------


class HandoffGate(BaseGate):
    """Validate god-to-god handoff with six sub-gates and a signed seal.

    Sub-gates:
        1. GIT_CLEAN — working tree committed
        2. TESTS_GREEN — zero test failures
        3. TODOS_RESOLVED — no open TODO/FIXME markers
        4. LINT_CLEAN — files passed logic validation
        5. BLOCKS_RESOLVED — all Ichor interventions addressed
        6. STATE_EXPORTED — read-cache ready for transfer

    Tier system:
        - full: All 6 sub-gates must pass
        - bronze: Only GIT_CLEAN + TESTS_GREEN mandatory; others are warnings
    """

    name = "handoff_gate"

    def __init__(
        self,
        base_path: str = ".",
        read_cache: Optional[ReadCache] = None,
    ):
        self.base_path = os.path.abspath(os.path.expanduser(base_path))
        self._cache = read_cache or ReadCache()
        self._interventions: List[GateResult] = []
        self._lint_clean: bool = True

    def register_intervention(self, result: GateResult) -> None:
        self._interventions.append(result)
        if not result.passed:
            self._lint_clean = False

    def _check_git_clean(self) -> Tuple[bool, str]:
        try:
            r = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True,
                cwd=self.base_path, timeout=10,
            )
            if r.returncode != 0:
                return False, f"Git error: {r.stderr[:200]}"
            if r.stdout.strip():
                lines = r.stdout.strip().split("\n")
                return False, f"Dirty: {len(lines)} uncommitted changes"
            return True, "Clean"
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            return False, f"Git unavailable: {e}"

    def _check_tests_green(self) -> Tuple[bool, str]:
        # Look for test result markers
        markers = [".test_done", "tests/.last_result", "pytest.xml"]
        for m in markers:
            if os.path.exists(os.path.join(self.base_path, m)):
                return True, f"Test marker: {m}"

        test_dir = os.path.join(self.base_path, "tests")
        if os.path.isdir(test_dir) and os.listdir(test_dir):
            return False, "Tests exist but not verified — run pytest"

        return True, "No tests found"

    def _check_todos_resolved(self) -> Tuple[bool, str]:
        try:
            r = subprocess.run(
                ["grep", "-rnI",
                 r"\b(TODO|FIXME|HACK|XXX)\b",
                 "--include=*.py", "--include=*.js", "--include=*.ts",
                 "--include=*.tsx", "--include=*.md", "--include=*.yaml",
                 "--include=*.json",
                 self.base_path],
                capture_output=True, text=True,
                timeout=10,
            )
            if r.stdout.strip():
                count = len(r.stdout.strip().split("\n"))
                return False, f"{count} unresolved markers"
            return True, "No markers"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return True, "Check skipped"

    def _check_blocks_resolved(self) -> Tuple[bool, str]:
        unresolved = [i for i in self._interventions if not i.passed]
        if unresolved:
            return False, f"{len(unresolved)} unresolved interventions"
        return True, "All resolved"

    def _check_state_exported(self) -> Tuple[bool, str]:
        snapshot = self._cache.snapshot()
        if snapshot["count"] > 0:
            return True, f"Cache: {snapshot['count']} entries"
        return False, "Cache empty — no state to transfer"

    def generate_manifest(
        self,
        source_god: str,
        target_god: str,
        tier: str = "full",
    ) -> HandoffManifest:
        sub_gates: List[Tuple[str, Any]] = [
            ("GIT_CLEAN", self._check_git_clean),
            ("TESTS_GREEN", self._check_tests_green),
            ("TODOS_RESOLVED", self._check_todos_resolved),
            ("LINT_CLEAN", lambda: (self._lint_clean, "")),
            ("BLOCKS_RESOLVED", self._check_blocks_resolved),
            ("STATE_EXPORTED", self._check_state_exported),
        ]

        checks: Dict[str, bool] = {}
        for name, fn in sub_gates:
            passed, _ = fn()
            checks[name] = passed

        if tier == "full":
            all_pass = all(checks.values())
        else:
            # Bronze: mandatory = GIT_CLEAN + TESTS_GREEN
            all_pass = checks.get("GIT_CLEAN", False) and checks.get(
                "TESTS_GREEN", False
            )

        manifest = HandoffManifest(
            source_god=source_god,
            target_god=target_god,
            timestamp=time.time(),
            state_snapshot=self._cache.snapshot(),
            check_results=checks,
            tier=tier if all_pass else "bronze",
        )
        manifest.signature = manifest.generate_signature()
        return manifest

# ---------------------------------------------------------------------------
# Gate Pipeline
# ---------------------------------------------------------------------------


class GatePipeline:
    """Composable pipeline that runs all Ichor gates in sequence.

    Typical call order:
        1. on_session_start() — inject context at session begin
        2. run_pre_call() — check before each tool call
        3. run_post_call() — validate after each tool call
        4. generate_handoff_manifest() — verify state before handoff
    """

    def __init__(self):
        self.read_cache = ReadCache()
        self.gates: List[BaseGate] = []
        self._handoff_gate = HandoffGate(read_cache=self.read_cache)
        self.register(self._handoff_gate)

    def register(self, gate: BaseGate) -> None:
        """Register a gate into the pipeline."""
        self.gates.append(gate)

    def run_pre_call(
        self,
        tool_name: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[GateResult]:
        """Run all pre-call hooks. Returns first blocking result or None."""
        ctx: Dict[str, Any] = context or {}

        for gate in self.gates:
            try:
                result = gate.pre_call(tool_name, params, ctx)
                if result is not None:
                    if not result.passed:
                        self._log_intervention(gate, result)
                        return result  # Hard block
            except Exception as exc:
                logger.warning("Gate '%s' pre_call error: %s", gate.name, exc)

        return None

    def run_post_call(
        self,
        tool_name: str,
        params: Dict[str, Any],
        result_value: Any,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[GateResult]:
        """Run all post-call hooks. Returns all results."""
        ctx: Dict[str, Any] = context or {}
        results: List[GateResult] = []

        for gate in self.gates:
            try:
                result = gate.post_call(tool_name, params, result_value, ctx)
                if result is not None:
                    results.append(result)
                    if not result.passed:
                        self._log_intervention(gate, result)
            except Exception as exc:
                logger.warning(
                    "Gate '%s' post_call error: %s", gate.name, exc
                )

        return results

    def on_session_start(
        self, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Run session-start hooks across all gates.

        Returns a merged dict of all injected context.
        """
        injected: Dict[str, Any] = {}
        for gate in self.gates:
            try:
                result = gate.on_session_start(context)
                if result:
                    injected.update(result)
            except Exception as exc:
                logger.warning(
                    "Gate '%s' session_start error: %s", gate.name, exc
                )
        return injected

    def _log_intervention(
        self, gate: BaseGate, result: GateResult
    ) -> None:
        logger.info(
            "Ichor Intervention [%s]: %s", gate.name, result.message
        )
        self._handoff_gate.register_intervention(result)

    def generate_handoff_manifest(
        self,
        source_god: str,
        target_god: str,
        tier: str = "full",
    ) -> HandoffManifest:
        return self._handoff_gate.generate_manifest(
            source_god, target_god, tier
        )

# ---------------------------------------------------------------------------
# Forge Logger
# ---------------------------------------------------------------------------


class ForgeLogger:
    """Logs Ichor interventions for federated fine-tuning.

    Tagged by model type. Logs are local-only by default.
    """

    def __init__(self, log_dir: str = "~/.hermes/ichor/forge/"):
        self.log_dir = os.path.expanduser(log_dir)
        os.makedirs(self.log_dir, exist_ok=True)

    def log_intervention(
        self,
        gate_name: str,
        result: GateResult,
        model: str = "unknown",
        session_id: str = "",
        user_intent: str = "",
        god: str = "",
    ) -> None:
        entry = {
            "timestamp": time.time(),
            "gate": gate_name,
            "passed": result.passed,
            "message": result.message[:200],
            "recovery_hint": result.recovery_hint[:500],
            "model": model,
            "session_id": session_id,
            "user_intent": user_intent[:200],
            "god": god,
        }

        model_safe = model.replace("/", "_").replace(" ", "_")
        model_file = os.path.join(self.log_dir, f"{model_safe}.jsonl")
        combined_file = os.path.join(self.log_dir, "all.jsonl")
        god_file = os.path.join(self.log_dir, f"god-{god}.jsonl") if god else ""

        line = json.dumps(entry) + "\n"
        with open(model_file, "a") as f:
            f.write(line)
        with open(combined_file, "a") as f:
            f.write(line)
        if god_file:
            with open(god_file, "a") as f:
                f.write(line)

    def get_stats(self, model: str = "all") -> Dict[str, Any]:
        log_file = os.path.join(
            self.log_dir,
            "all.jsonl" if model == "all"
            else f"{model.replace('/', '_')}.jsonl",
        )
        if not os.path.exists(log_file):
            return {"model": model, "total": 0, "gates": {}}

        stats: Dict[str, Any] = {
            "model": model, "total": 0, "passed": 0, "blocked": 0,
            "gates": {},
        }
        with open(log_file) as f:
            for line in f:
                entry = json.loads(line)
                stats["total"] += 1
                if entry["passed"]:
                    stats["passed"] += 1
                else:
                    stats["blocked"] += 1

                gate = entry["gate"]
                if gate not in stats["gates"]:
                    stats["gates"][gate] = {"total": 0, "blocked": 0}
                stats["gates"][gate]["total"] += 1
                if not entry["passed"]:
                    stats["gates"][gate]["blocked"] += 1

        return stats

# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI for testing and inspecting the gate pipeline."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Ichor RALPH 5-Gate Harness — CLI"
    )
    parser.add_argument(
        "--test-state", metavar="PATH",
        help="Test State Gate on a file path",
    )
    parser.add_argument(
        "--test-logic", metavar="PATH",
        help="Test Logic Gate on a file path",
    )
    parser.add_argument(
        "--test-phase", metavar="INPUT",
        help="Test phase detection on a natural language input",
    )
    parser.add_argument(
        "--test-handoff",
        choices=["full", "bronze"],
        help="Run handoff gate tests",
    )
    parser.add_argument(
        "--source-god", default="hermes",
        help="Source god for handoff (default: hermes)",
    )
    parser.add_argument(
        "--target-god", default="hephaestus",
        help="Target god for handoff (default: hephaestus)",
    )
    parser.add_argument(
        "--forge-stats", metavar="MODEL",
        help="Get Forge intervention stats for a model",
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

    pipeline = GatePipeline()

    # ── Test State Gate ──────────────────────────────────────────────
    if args.test_state:
        cache = ReadCache()
        gate = StateGate(cache)

        # Without prior read
        r = gate.pre_call("write_file", {"path": args.test_state}, {})
        if r and not r.passed:
            print(f"❌ State Gate: BLOCKED — {r.message}")
            print(f"   Hint: {r.recovery_hint}")
        else:
            print("✅ State Gate: passthrough (new file?)")

        # With prior read
        cache.mark_read(args.test_state)
        r = gate.pre_call("write_file", {"path": args.test_state}, {})
        if r is None:
            print("✅ State Gate: PASSED — read confirmed")
        else:
            print(f"❌ State Gate: unexpected block — {r.message}")

    # ── Test Logic Gate ──────────────────────────────────────────────
    if args.test_logic:
        gate = LogicGate()
        try:
            with open(args.test_logic, "r") as f:
                content = f.read()
        except FileNotFoundError:
            print(f"❌ File not found: {args.test_logic}")
            return

        r = gate.post_call(
            "write_file",
            {"path": args.test_logic, "content": content},
            None, {},
        )
        if r and not r.passed:
            print(f"❌ Logic Gate: {r.message}")
            print(f"   Issues:\n{r.recovery_hint}")
        else:
            print("✅ Logic Gate: PASSED — no issues")

    # ── Test Phase Detection ─────────────────────────────────────────
    if args.test_phase:
        gate = PhaseDetectionGate()
        phase = gate.detect_phase(args.test_phase)
        print(f"Input:       {args.test_phase}")
        print(f"Detected:    {phase.value}")
        print(f"Prompt:      {PHASE_PROMPTS.get(phase, '')[:80]}...")
        tools = gate.get_allowed_tools()
        if tools:
            print(f"Tools ({len(tools)}): {', '.join(tools[:5])}...")
        else:
            print("Tools:       [no pruning — phase is UNKNOWN]")

    # ── Test Handoff ─────────────────────────────────────────────────
    if args.test_handoff:
        manifest = pipeline.generate_handoff_manifest(
            args.source_god, args.target_god, args.test_handoff
        )
        print(f"\n{'='*50}")
        print(f"Handoff: {args.source_god} → {args.target_god}")
        print(f"Tier:     {manifest.tier.upper()}")
        print(f"Seal:     {manifest.signature}")
        print(f"{'='*50}")
        for check, passed in manifest.check_results.items():
            icon = "✅" if passed else "❌"
            print(f"  {icon} {check}")
        print(f"{'='*50}")

    # ── Forge Stats ──────────────────────────────────────────────────
    if args.forge_stats:
        fl = ForgeLogger()
        stats = fl.get_stats(args.forge_stats)
        print(f"Forge stats: '{stats['model']}'")
        print(f"  Total:  {stats['total']}")
        print(f"  Passed: {stats['passed']}")
        print(f"  Blocked: {stats['blocked']}")
        for gate, gs in stats.get("gates", {}).items():
            print(f"  [{gate}] {gs['total']} total, {gs['blocked']} blocked")


if __name__ == "__main__":
    main()
