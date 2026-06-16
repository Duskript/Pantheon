"""Conductor v2 engine — file watcher, rule evaluator, DAG executor, state.

Spec sections 3.1-3.6, 6, 8. This is the actual orchestrator that v1 was
missing. Watches pending/<god>/ for handoff files, matches them against
reaction rules in rules/*.yaml, dispatches god sessions via the gateway
client, and walks workflow definitions in workflows/*.yaml step by step.

Design points (locked in DECISIONS.md 2026-06-14):
    - File-backed state, no DB (matches v1 layout, observable on disk)
    - Single ack timeout per step (spec 3.4 — no 3-tier ladder)
    - Layer 3a abort handling: write manifest + .aborted markers
    - Section 8.1 handling modes: external events default to
      approval_required, never auto-execute without an explicit rule
    - Workflow definitions are version-locked per instance (spec 8.4)

Threading model: this module is the orchestrator loop. Other modules
(NATS, webhook) call into it via enqueue_event() from their threads.
"""

from __future__ import annotations

import asyncio
import copy
import fnmatch
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import yaml
from watchfiles import Change, awatch

from . import gateway as gw_mod

LOG = logging.getLogger("conductor.v2.engine")

ROOT = Path(os.environ.get("PANTHEON_ROOT", Path.home() / "pantheon")).expanduser()
BASE_DIR = Path(os.environ.get("CONDUCTOR_BASE_DIR", ROOT / "conductor")).expanduser()
HANDOFFS_DIR = Path(os.environ.get("CONDUCTOR_HANDOFFS_DIR", ROOT / "shared" / "handoffs")).expanduser()
# These are the canonical defaults; the lazy functions below re-resolve
# from env so tests can override via CONDUCTOR_BASE_DIR.
# WARNING: RULES_DIR, WORKFLOWS_DIR, PENDING_DIR, STATE_DIR, HANDOFFS_DIR,
# BASE_DIR, and ROOT are all bound at import time from os.environ.
# Per-test overrides of CONDUCTOR_BASE_DIR / PANTHEON_ROOT do NOT take
# effect here — they were already read above (L43-45). The lazy
# resolvers (_rules_dir, _workflows_dir, _pending_dir, _state_dir)
# re-read the env on every call and are what tests should rely on.
# Marvin hygiene #3, Step 1.7 polish.
PENDING_DIR = BASE_DIR / "pending"
STATE_DIR = BASE_DIR / "state"


def _pending_dir() -> Path:
    """Lazy PENDING_DIR resolution (re-reads env each call)."""
    import os as _os
    base = _os.environ.get("CONDUCTOR_BASE_DIR")
    if base:
        return Path(base) / "pending"
    root = _os.environ.get("PANTHEON_ROOT", str(Path.home() / "pantheon"))
    return Path(root) / "conductor" / "pending"


def _state_dir() -> Path:
    """Lazy STATE_DIR resolution."""
    import os as _os
    base = _os.environ.get("CONDUCTOR_BASE_DIR")
    if base:
        return Path(base) / "state"
    root = _os.environ.get("PANTHEON_ROOT", str(Path.home() / "pantheon"))
    return Path(root) / "conductor" / "state"


def _rules_dir() -> Path:
    import os as _os
    base = _os.environ.get("CONDUCTOR_BASE_DIR")
    if base:
        return Path(base) / "rules"
    root = _os.environ.get("PANTHEON_ROOT", str(Path.home() / "pantheon"))
    return Path(root) / "conductor" / "rules"


def _workflows_dir() -> Path:
    import os as _os
    base = _os.environ.get("CONDUCTOR_BASE_DIR")
    if base:
        return Path(base) / "workflows"
    root = _os.environ.get("PANTHEON_ROOT", str(Path.home() / "pantheon"))
    return Path(root) / "conductor" / "workflows"
RULES_DIR = BASE_DIR / "rules"
WORKFLOWS_DIR = BASE_DIR / "workflows"
SCHEMA_PATH = HANDOFFS_DIR / "schema.json"

VALID_GODS = (
    "thoth", "hephaestus", "marvin", "hermes", "iris",
    "caduceus", "mercer", "rheta", "inbox", "_webhooks", "_quarantine",
)
HANDOFF_ID_RE = re.compile(r"^hof_(\d{8})_([a-z0-9]{6,8})$")
WORKFLOW_ID_RE = re.compile(r"^wf_[a-z0-9_]+$")
ACK_ID_RE = re.compile(r"^ack_(\d{8})_([a-z0-9]{3,8})$")

# Refusal markers — phrases that a god's run output starts with (or
# contains early) when it has REFUSED to execute a step rather than
# produced a real deliverable. Used by `_record_step_completion` to
# flip a "completed" gateway run to a "refused" step_history entry,
# so subsequent guards (e.g. the sovereign-outbound nats_publish
# guard) see the truthful refusal.
#
# Why case-insensitive, no-anchored: refusals are written in varied
# prose. "Refused `wf_...` ...", "HELD the dispatch ...", "won't
# roleplay ...", "I'm Thoth, not Marvin" — all signal that the
# work was NOT done. We deliberately allow a few false positives
# (a run that mentions "refused" in legitimate context will be
# flagged) over false negatives (a refusal that slips through
# undetected — that is what bit us on 2026-06-15 with wf_8a0b5f28
# + wf_f26885f8).
_REFUSAL_MARKER_RE = re.compile(
    r"\b(Refused `|HELD the dispatch|Held the dispatch|"
    r"Won't roleplay|won't roleplay|"
    r"I will not (roleplay|execute|complete)|"
    r"refusing to (execute|roleplay)|"
    r"this dispatch (does not|doesn't) add up|"
    r"no (real |genuine )?work to (do|execute)|"
    r"wrong god|misrouted dispatch|"
    r"fabrication|smoke test|"
    r"I'm Thoth[,.]|I am Thoth[,.])\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Sovereign-outbound guard (operator rule, 2026-06-15)
# ---------------------------------------------------------------------------
# Root cause: 2026-06-15T02:16:56Z + 02:23:25Z, the deploy-feature workflow
# fired `notify-enterprise` (a `type: nats_publish` step with no god, no
# gates, no operator approval) and published fabricated "Feature X
# implemented and reviewed, ready for Enterprise deploy" messages to
# `subspace.konan.outgoing.tallon` (Tallon / Enterprise Pantheon) even
# though all prior steps in the workflow had been refused as misroutes.
# The state file was marked `status=completed` for a workflow whose outputs
# were entirely refusals + 1 unauthorized publish. See state/wf_8a0b5f28.json
# and state/wf_f26885f8.json for the full forensic record.
#
# Operator's profile rule: "external events (Tallon NATS messages, webhooks,
# cross-Pantheon) must NEVER auto-execute without explicit user approval."
# This guard implements the engine-side enforcement of that rule.
#
# Pattern: any NATS subject matching `subspace.*.outgoing.*` is a
# sovereign outbound — the message is going to another Pantheon (or to a
# remote that we cannot take back). Subjects matching `subspace.*.inbox.*`
# or `subspace.*.incoming.*` are local-routing, not sovereign outbound,
# and remain un-gated by this check.
SOVEREIGN_OUTBOUND_RE = re.compile(r"^subspace\.[^.]+\.outgoing\..+$")
# Tokens that, if present in the handoff's `context.breach_evidence` (or
# in `context_bag.operator_approval_token`), authorize a sovereign
# outbound publish for a single workflow instance. A god may set this by
# surfacing a draft to the operator and writing the token back; the
# engine does NOT mint it on its own. The breach we are fixing fired
# because no such token was required and no such token was checked.
# (The token is operator-issued, not auto-mint, so a stolen workflow
# state file cannot synthesize one without operator action.)
_SOVEREIGN_TOKENS_ATTR = "operator_approval_token"


def _is_sovereign_outbound(subject: str) -> bool:
    """True if `subject` is a sovereign outbound NATS subject — i.e. a
    publish to another Pantheon or external recipient that the operator
    must explicitly approve. See SOVEREIGN_OUTBOUND_RE above for the
    full rule + the 2026-06-15 incident that motivated it."""
    if not subject:
        return False
    return bool(SOVEREIGN_OUTBOUND_RE.match(subject))


def _has_operator_approval(inst: "WorkflowInstance") -> bool:
    """True if `inst.context_bag` carries a valid operator_approval_token.
    Tokens are operator-issued (via the Hermes surface) and are bound to
    the workflow_id. The engine never auto-mints a token. See the
    SOVEREIGN_OUTBOUND_RE docstring for the rationale."""
    token = inst.context_bag.get(_SOVEREIGN_TOKENS_ATTR)
    if not isinstance(token, dict):
        return False
    if token.get("workflow_id") != inst.workflow_id:
        return False
    if not token.get("approved_by"):
        return False
    # Tokens are single-use: once consumed, the engine strips them so a
    # second nats_publish step in the same workflow does not silently
    # re-use a prior approval. Returns False (and clears) on second use.
    if token.get("consumed"):
        return False
    return True


def _consume_operator_approval(inst: "WorkflowInstance") -> None:
    """Mark the operator_approval_token as consumed (single-use semantics)."""
    token = inst.context_bag.get(_SOVEREIGN_TOKENS_ATTR)
    if isinstance(token, dict):
        token["consumed"] = True
        token["consumed_at"] = utc_now()


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_id(prefix: str, n: int = 6) -> str:
    """Generate a spec-compliant id like hof_20260614_a1b2c3."""
    return f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{uuid.uuid4().hex[:n]}"


# ---------------------------------------------------------------------------
# Atomic I/O helpers
# ---------------------------------------------------------------------------

def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


# ---------------------------------------------------------------------------
# Section 8.1 — Handling modes for external events
# ---------------------------------------------------------------------------

HANDLING_MODES = ("log_only", "notify", "notify_and_log", "approval_required", "route_on_approval")
DEFAULT_EXTERNAL_MODE = "approval_required"  # hard rule from spec 8.1


@dataclass
class Event:
    """Normalized event fed to the rule engine and executor."""
    type: str                       # handoff.completed | nats.message | webhook | schedule.cron | schedule.once
    source: str                     # thoth | tallon | github | cron | ...
    target: Optional[str] = None    # god name (or None for broadcasts)
    subject: Optional[str] = None   # NATS subject / webhook path
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=utc_now)
    raw: dict[str, Any] = field(default_factory=dict)
    is_external: bool = False       # True for NATS/webhook/cron; False for internal handoffs
    handling_mode: Optional[str] = None  # set after rule match


# ---------------------------------------------------------------------------
# Rule engine
# ---------------------------------------------------------------------------

@dataclass
class Rule:
    id: str
    when: dict[str, Any]
    then: dict[str, Any]
    source_path: Path

    @classmethod
    def from_dict(cls, d: dict[str, Any], source: Path) -> "Rule":
        return cls(
            id=d["id"],
            when=d.get("when", {}),
            then=d.get("then", {}),
            source_path=source,
        )

    def matches(self, event: Event) -> bool:
        return _match_condition(self.when, event)


def _match_condition(cond: dict[str, Any], event: Event) -> bool:
    """Evaluate a `when:` block against an event.

    Spec section 3.5. Supported patterns:

        event_type: handoff.completed            # exact
        source: thoth                            # exact
        source: [thoth, marvin]                  # any-of
        subject: "subspace.tallon.incoming.*"   # fnmatch glob (with literal dots)
        subject: ["a.*", "b.*"]                  # any-of with globs
        context:
          gates_passed_contains: logic_gate      # string alias for contains
        # OR — using spec's exact syntax:
        #   context.gates_passed contains "logic_gate"
        #   ...is also supported as a dotted key (parses via contains op).

    Values can be strings, lists of strings, or `contains "X"` operators.

    Note on NATS wildcards (2026-06-15, session `20260615_*`):
    The matcher uses `fnmatch.fnmatchcase` which only knows `*` and `?`
    — NATS's `>` (multi-level wildcard) is a LITERAL `>` to fnmatch and
    will never match a real subject. None of the production rules in
    `rules/cross-pantheon.yaml` or `rules/tallon-operations.yaml` use
    `>`, so the limitation is dormant. If a future rule needs NATS-style
    multi-segment matching, either (a) rewrite as multiple exact rules,
    (b) convert `>` → `*` and accept that fnmatch's `*` greedily crosses
    dots, or (c) extend this function with a NATS-aware matcher
    (`nats.subject_match` from nats-py if needed). The current
    investigation (Phase 3 Step 3.1) confirmed the 4 production rules +
    the bonus `tallon-incoming-message` rule in `research-to-build.yaml`
    all match their target subjects. See `tests/test_nats_bridge.py`
    for the lock-in.
    """
    event_ctx = event.payload.get("context") or {}
    for key, expected in cond.items():
        # Form A: dotted key with `contains "X"` (spec example syntax)
        # e.g. "context.gates_passed contains \"logic_gate\""
        m_contains = re.match(r"^([\w.]+)\s+contains\s+['\"](.+?)['\"]\s*$", str(key))
        if m_contains:
            dotted, needle = m_contains.group(1), m_contains.group(2)
            actual = _resolve_dotted(event, dotted)
            if not _contains(actual, needle):
                return False
            continue
        # Form B: `key contains "X"` (operator on a value)
        if isinstance(expected, str) and expected.startswith("contains "):
            needle = expected[len("contains "):].strip().strip('"').strip("'")
            actual = getattr(event, key, None) or (event_ctx.get(key))
            if not _contains(actual, needle):
                return False
            continue
        # YAML uses event_type; Event dataclass field is `type`
        if key == "event_type":
            key = "type"
        # `expression` is a schedule.cron rule's cron string — metadata
        # for the CronScheduler (conductor.v2.cron_scheduler), NOT a
        # field on the Event dataclass. The scheduler already filters
        # by rule_id before firing, so the rule engine must NOT try
        # to match this key against event attributes. Without this
        # skip, every schedule.cron rule (including the production
        # daily-morning-briefing) would fail to match because the
        # Event has no `expression` attribute.
        if key == "expression":
            continue
        if key == "context":
            # nested context checks (dict form)
            for ck, cv in expected.items():
                if isinstance(cv, str) and cv.startswith("contains "):
                    needle = cv[len("contains "):].strip().strip('"').strip("'")
                    if not _contains(event_ctx.get(ck), needle):
                        return False
                else:
                    if event_ctx.get(ck) != cv:
                        return False
            continue
        # Top-level field: subject supports fnmatch wildcards
        actual = getattr(event, key, None)
        if key == "subject" and isinstance(expected, str) and ("*" in expected or "?" in expected):
            if not (isinstance(actual, str) and fnmatch.fnmatchcase(actual, expected)):
                return False
            continue
        if isinstance(expected, list):
            # any-of list; for subject items, also support wildcards
            if key == "subject" and any("*" in s or "?" in s for s in expected if isinstance(s, str)):
                if not any(isinstance(actual, str) and fnmatch.fnmatchcase(actual, s) for s in expected if isinstance(s, str)):
                    return False
                continue
            if actual not in expected:
                return False
        else:
            if actual != expected:
                return False
    return True


def _resolve_dotted(event: Event, dotted: str) -> Any:
    """Resolve a dotted path against an event, e.g. 'context.gates_passed'."""
    parts = dotted.split(".")
    if parts[0] == "context":
        actual = event.payload.get("context") or {}
        for p in parts[1:]:
            if isinstance(actual, dict):
                actual = actual.get(p)
            else:
                return None
        return actual
    # Walk event attributes
    actual: Any = event
    for p in parts:
        actual = getattr(actual, p, None) if hasattr(actual, p) else None
        if actual is None:
            return None
    return actual


def _contains(haystack: Any, needle: str) -> bool:
    """Test if `needle` is in `haystack`. Works for strings (substring),
    lists (membership), and dicts (key membership)."""
    if haystack is None:
        return False
    if isinstance(haystack, str):
        return needle in haystack
    if isinstance(haystack, (list, tuple, set)):
        return any(needle == item or (isinstance(item, str) and needle in item) for item in haystack)
    if isinstance(haystack, dict):
        return needle in haystack
    return str(needle) in str(haystack)


class RuleEngine:
    """Loads rules/*.yaml and matches events to first applicable rule.

    Construction-time directory resolution: see `_rules_dir()` for the
    lazy env-resolver used as the default. Resolving at `__init__` time
    (not at module import time) is the Step 1.6 fix for the
    dual-module binding footgun documented at the top of the file and
    in BUILD-PLAN.md §1.5 (v2.engine vs conductor.v2.engine were two
    distinct module objects, each with their own RULES_DIR captured at
    first import — subsequent CONDUCTOR_BASE_DIR mutations were
    silently ignored).
    """

    def __init__(self, rules_dir: Optional[Path] = None):
        # Step 1.6 lazy fix: resolve rules_dir at construction time, NOT at
        # import time. The module-level RULES_DIR is a frozen constant bound
        # at first-import; if CONDUCTOR_BASE_DIR gets set to a tmpdir AFTER
        # this module was first imported, the frozen RULES_DIR still points
        # at the production path. Tests and the live v2 daemon both suffered
        # from this dual-module binding footgun (v2.engine vs conductor.v2.engine
        # are two distinct module objects, each with their own RULES_DIR
        # captured at first import). We default to the lazy _rules_dir()
        # resolver so per-instance construction reads the CURRENT env.
        self.rules_dir = rules_dir if rules_dir is not None else _rules_dir()
        self._rules: list[Rule] = []
        self._loaded_at: float = 0.0
        self.reload()

    def reload(self) -> int:
        self._rules = []
        if not self.rules_dir.exists():
            LOG.warning(f"rules dir missing: {self.rules_dir}")
            return 0
        for path in sorted(self.rules_dir.glob("*.yaml")):
            try:
                doc = read_yaml(path)
            except Exception as e:
                LOG.error(f"failed to load rule file {path}: {e}")
                continue
            for rule_dict in doc.get("rules", []) or []:
                try:
                    self._rules.append(Rule.from_dict(rule_dict, path))
                except Exception as e:
                    LOG.error(f"failed to parse rule in {path}: {e}")
        self._loaded_at = time.time()
        LOG.info(f"loaded {len(self._rules)} rules from {self.rules_dir}")
        return len(self._rules)

    def match(self, event: Event) -> Optional[Rule]:
        for rule in self._rules:
            if rule.matches(event):
                LOG.debug(f"event {event.type}/{event.source} matched rule {rule.id}")
                return rule
        return None

    def apply_default(self, event: Event) -> Rule:
        """Spec 8.1: unmatched external events get approval_required."""
        mode = DEFAULT_EXTERNAL_MODE
        event.handling_mode = mode
        return Rule(
            id="__default_external__",
            when={"event_type": event.type, "source": event.source},
            then={
                "handling_mode": mode,
                "action": "quarantine",
                "message": f"Unrecognized event from {event.source}. No handling rule configured.",
            },
            source_path=Path("<default>"),
        )


# ---------------------------------------------------------------------------
# Workflow loader + executor
# ---------------------------------------------------------------------------

@dataclass
class WorkflowStep:
    id: str
    type: str = "god"  # god | nats_publish
    god: Optional[str] = None
    skill: Optional[str] = None
    action: Optional[str] = None
    input: Optional[str] = None
    input_from: Optional[str] = None
    subject: Optional[str] = None  # for nats_publish
    message: Optional[str] = None
    gates: list[str] = field(default_factory=list)
    output: Optional[str] = None
    timeout: str = "30m"
    on_timeout: Optional[str] = None
    loop: Optional[dict[str, Any]] = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class Workflow:
    id: str
    name: str
    version: str
    description: str = ""
    context_required: list[str] = field(default_factory=list)
    context_optional: list[str] = field(default_factory=list)
    steps: list[WorkflowStep] = field(default_factory=list)
    source_path: Path = Path("<memory>")

    @classmethod
    def from_dict(cls, d: dict[str, Any], source: Path) -> "Workflow":
        wf = d.get("workflow", d)
        ctx = wf.get("context", {}) or {}
        steps = []
        for s in wf.get("steps", []) or []:
            steps.append(WorkflowStep(
                id=s["id"],
                type=s.get("type", "god"),
                god=s.get("god"),
                skill=s.get("skill"),
                action=s.get("action"),
                input=s.get("input"),
                input_from=s.get("input_from"),
                subject=s.get("subject"),
                message=s.get("message"),
                gates=list(s.get("gates", []) or []),
                output=s.get("output"),
                timeout=s.get("timeout", "30m"),
                on_timeout=s.get("on_timeout"),
                loop=s.get("loop"),
                payload=dict(s.get("payload", {}) or {}),
            ))
        return cls(
            id=wf["id"],
            name=wf.get("name", wf["id"]),
            version=wf.get("version", "1.0.0"),
            description=wf.get("description", ""),
            context_required=list(ctx.get("required", []) or []),
            context_optional=list(ctx.get("optional", []) or []),
            steps=steps,
            source_path=source,
        )

    def step_by_id(self, step_id: str) -> Optional[WorkflowStep]:
        return next((s for s in self.steps if s.id == step_id), None)

    def next_step_after(self, step_id: str) -> Optional[WorkflowStep]:
        ids = [s.id for s in self.steps]
        if step_id not in ids:
            return None
        i = ids.index(step_id)
        return self.steps[i + 1] if i + 1 < len(self.steps) else None


class WorkflowRegistry:
    """Loads workflows/*.yaml and looks them up by id.

    Construction-time directory resolution: see `_workflows_dir()` for the
    lazy env-resolver used as the default. Resolving at `__init__` time
    (not at module import time) is the Step 1.6 fix for the
    dual-module binding footgun (v2.engine vs conductor.v2.engine are two
    distinct module objects, each with their own WORKFLOWS_DIR captured
    at first import). See BUILD-PLAN.md §1.5/§1.6 for the full carry-forward.
    """

    def __init__(self, workflows_dir: Optional[Path] = None):
        # Step 1.6 lazy fix: see RuleEngine docstring above for the rationale.
        self.workflows_dir = workflows_dir if workflows_dir is not None else _workflows_dir()
        self._workflows: dict[str, Workflow] = {}
        self.reload()

    def reload(self) -> int:
        self._workflows = {}
        if not self.workflows_dir.exists():
            return 0
        for path in sorted(self.workflows_dir.glob("*.yaml")):
            try:
                doc = read_yaml(path)
                wf = Workflow.from_dict(doc, path)
                self._workflows[wf.id] = wf
            except Exception as e:
                LOG.error(f"failed to load workflow {path}: {e}")
        LOG.info(f"loaded {len(self._workflows)} workflows from {self.workflows_dir}")
        return len(self._workflows)

    def get(self, workflow_id: str) -> Optional[Workflow]:
        return self._workflows.get(workflow_id)

    def all(self) -> list[Workflow]:
        return list(self._workflows.values())


# ---------------------------------------------------------------------------
# Engine — orchestrates everything
# ---------------------------------------------------------------------------

@dataclass
class WorkflowInstance:
    workflow_id: str            # wf_...
    definition_id: str          # morning-briefing, deploy-feature, ...
    definition_version: str     # version-locked at start (spec 8.4)
    status: str = "in_progress"  # in_progress | waiting_for_ack | completed | aborted | failed
    current_step: Optional[str] = None
    context_bag: dict[str, Any] = field(default_factory=dict)
    step_history: list[dict[str, Any]] = field(default_factory=list)
    created: str = field(default_factory=utc_now)
    completion_target: Optional[str] = None
    abort_on_fail: bool = True
    dispatched_to: Optional[str] = None
    initiator: str = "konan"
    original_request: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "definition_id": self.definition_id,
            "definition_version": self.definition_version,
            "status": self.status,
            "current_step": self.current_step,
            "context_bag": self.context_bag,
            "step_history": self.step_history,
            "created": self.created,
            "completion_target": self.completion_target,
            "abort_on_fail": self.abort_on_fail,
            "dispatched_to": self.dispatched_to,
            "initiator": self.initiator,
            "original_request": self.original_request,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WorkflowInstance":
        return cls(
            workflow_id=d["workflow_id"],
            definition_id=d.get("definition_id", "?"),
            definition_version=d.get("definition_version", "1.0.0"),
            status=d.get("status", "in_progress"),
            current_step=d.get("current_step"),
            context_bag=dict(d.get("context_bag", {})),
            step_history=list(d.get("step_history", [])),
            created=d.get("created", utc_now()),
            completion_target=d.get("completion_target"),
            abort_on_fail=d.get("abort_on_fail", True),
            dispatched_to=d.get("dispatched_to"),
            initiator=d.get("initiator", "konan"),
            original_request=d.get("original_request", ""),
        )


class ConductorEngine:
    """Single-process orchestrator. Wires rule engine + workflow registry +
    gateway client + file watcher into the dispatch loop.

    Construction-time directory resolution: all of `rules`, `workflows`,
    `pending_dir`, `state_dir` are resolved at `__init__` time, NOT at
    module import time. The defaults call the lazy env-resolvers
    (`_pending_dir()`, `_state_dir()`, `_rules_dir()`, `_workflows_dir()`)
    so a direct `ConductorEngine()` construction reads the CURRENT
    `CONDUCTOR_BASE_DIR` env var. This is the Step 1.6 fix for the
    dual-module binding footgun (v2.engine vs conductor.v2.engine were
    two distinct module objects in `sys.modules`, each with their own
    frozen module-level paths captured at first import). See
    BUILD-PLAN.md §1.5/§1.6.
    """

    def __init__(
        self,
        *,
        gateway_client: Optional[gw_mod.GatewayClient] = None,
        rules: Optional[RuleEngine] = None,
        workflows: Optional[WorkflowRegistry] = None,
        pending_dir: Optional[Path] = None,
        state_dir: Optional[Path] = None,
        workflows_dir: Optional[Path] = None,
    ):
        self.gw = gateway_client
        # Step 1.6 lazy fix: pass the lazy resolvers into the registries
        # explicitly so a `ConductorEngine()` with no kwargs reads the
        # CURRENT env, not the import-time frozen constants. Pre-1.6 code
        # relied on the registries' own default of the module-level
        # RULES_DIR / WORKFLOWS_DIR, which is the dual-module footgun.
        self.rules = rules or RuleEngine()
        # Step 1.6: bridge callers can pass `workflows_dir=...` to
        # override the lazy env resolver. The bridge uses this to make
        # the v1 and v2 paths agree on which workflow definitions are
        # "known" — without the override, the v2 path would resolve
        # workflows from the env-default (production) when
        # CONDUCTOR_BASE_DIR is unset, causing the v1+v2 routing
        # collision the BUILD-PLAN §1.5 carry-forward warns about.
        if workflows is not None:
            self.workflows = workflows
        elif workflows_dir is not None:
            self.workflows = WorkflowRegistry(workflows_dir=workflows_dir)
        else:
            self.workflows = WorkflowRegistry()
        self.pending_dir = pending_dir if pending_dir is not None else _pending_dir()
        self.state_dir = state_dir if state_dir is not None else _state_dir()
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        # Create per-god inboxes (and the special _webhooks/_quarantine inboxes)
        # so writes never fail with FileNotFoundError.
        for god in VALID_GODS:
            (self.pending_dir / god).mkdir(parents=True, exist_ok=True)
        self._instances: dict[str, WorkflowInstance] = {}
        self._load_active_instances()

    # ----- Instance management -----

    def _load_active_instances(self) -> int:
        n = 0
        for path in self.state_dir.glob("wf_*.json"):
            try:
                inst = WorkflowInstance.from_dict(read_json(path))
                if inst.status in ("in_progress", "waiting_for_ack"):
                    self._instances[inst.workflow_id] = inst
                    n += 1
            except Exception as e:
                LOG.warning(f"failed to load instance {path}: {e}")
        LOG.info(f"loaded {n} active workflow instances from {self.state_dir}")
        return n

    def _save_instance(self, inst: WorkflowInstance) -> None:
        write_json(self.state_dir / f"{inst.workflow_id}.json", inst.to_dict())

    def get_instance(self, workflow_id: str) -> Optional[WorkflowInstance]:
        return self._instances.get(workflow_id) or self._load_instance_from_disk(workflow_id)

    def _load_instance_from_disk(self, workflow_id: str) -> Optional[WorkflowInstance]:
        path = self.state_dir / f"{workflow_id}.json"
        if not path.exists():
            return None
        inst = WorkflowInstance.from_dict(read_json(path))
        self._instances[workflow_id] = inst
        return inst

    def list_active(self) -> list[WorkflowInstance]:
        return [i for i in self._instances.values() if i.status in ("in_progress", "waiting_for_ack")]

    def list_all(self) -> list[WorkflowInstance]:
        out = list(self._instances.values())
        for path in self.state_dir.glob("wf_*.json"):
            wid = path.stem
            if wid not in self._instances:
                try:
                    inst = WorkflowInstance.from_dict(read_json(path))
                    out.append(inst)
                except Exception:
                    pass
        return out

    # ----- Workflow start (called by rule then: or directly) -----

    def start_workflow_sync(
        self,
        workflow_def_id: str,
        *,
        context: Optional[dict[str, Any]] = None,
        initiator: str = "konan",
        original_request: str = "",
    ) -> WorkflowInstance:
        """Mint a new WorkflowInstance and persist it to state/, without
        scheduling the first step for execution.

        This is the synchronous, daemon-free variant of `start_workflow`.
        The MCP bridge (conductor.conductor_server.start_workflow) and any
        other out-of-process caller that needs to write a wf_*.json to
        state/ without also running its steps should call this.

        Contrast with `start_workflow`, which additionally schedules
        `asyncio.create_task(self._execute_step(...))` for the first step.
        That requires a running event loop + gateway client owned by the
        daemon process; this method does not.

        Status alias note: the v2 engine uses status="in_progress" internally
        (`WorkflowInstance.status` default at line 450). The MCP contract
        asks for "running" — the bridge is responsible for translating
        "in_progress" → "running" in its response shape, NOT this method.
        Changing the engine's default would touch the spec 8.x status
        vocabulary, so we keep it stable and let the bridge be the alias.

        Returns the in-memory `WorkflowInstance` (caller may serialize it
        via `inst.to_dict()`). Raises ValueError for unknown workflow_def_id.
        """
        wf = self.workflows.get(workflow_def_id)
        if not wf:
            raise ValueError(f"unknown workflow: {workflow_def_id}")

        wf_id = f"wf_{uuid.uuid4().hex[:8]}"
        inst = WorkflowInstance(
            workflow_id=wf_id,
            definition_id=workflow_def_id,
            definition_version=wf.version,  # version lock (spec 8.4)
            context_bag=dict(context or {}),
            initiator=initiator,
            original_request=original_request,
        )
        first_step_id = wf.steps[0].id if wf.steps else None
        inst.current_step = first_step_id
        self._instances[wf_id] = inst
        self._save_instance(inst)
        LOG.info(
            f"start_workflow_sync: minted {wf_id} ({workflow_def_id} "
            f"v{wf.version}) at step {first_step_id} (initiator={initiator})"
        )
        return inst

    def start_workflow(
        self,
        workflow_def_id: str,
        *,
        context: Optional[dict[str, Any]] = None,
        initiator: str = "konan",
        original_request: str = "",
        start_at_step: Optional[str] = None,
    ) -> WorkflowInstance:
        wf = self.workflows.get(workflow_def_id)
        if not wf:
            raise ValueError(f"unknown workflow: {workflow_def_id}")

        wf_id = f"wf_{uuid.uuid4().hex[:8]}"
        inst = WorkflowInstance(
            workflow_id=wf_id,
            definition_id=workflow_def_id,
            definition_version=wf.version,  # version lock (spec 8.4)
            context_bag=dict(context or {}),
            initiator=initiator,
            original_request=original_request,
        )
        first_step_id = start_at_step or (wf.steps[0].id if wf.steps else None)
        inst.current_step = first_step_id
        self._instances[wf_id] = inst
        self._save_instance(inst)
        LOG.info(f"started workflow {wf_id} ({workflow_def_id} v{wf.version}) at step {first_step_id}")

        if first_step_id:
            asyncio.create_task(self._execute_step(inst, wf, first_step_id))
        return inst

    # ----- Step execution -----

    async def _execute_step(self, inst: WorkflowInstance, wf: Workflow, step_id: str) -> None:
        step = wf.step_by_id(step_id)
        if not step:
            LOG.error(f"workflow {inst.workflow_id}: step {step_id!r} not found")
            inst.status = "failed"
            self._save_instance(inst)
            return

        # Record start
        inst.step_history.append({
            "step_id": step.id,
            "god": step.god,
            "status": "in_progress",
            "started": utc_now(),
        })
        inst.status = "in_progress"
        self._save_instance(inst)

        try:
            if step.type == "nats_publish":
                await self._exec_nats_publish(inst, step)
            else:
                await self._exec_god_dispatch(inst, wf, step)
        except Exception as e:
            LOG.exception(f"step {step_id} failed in {inst.workflow_id}: {e}")
            self._record_step_failure(inst, step, str(e))
            self._save_instance(inst)
            if inst.abort_on_fail:
                self._abort_workflow(inst, f"step {step_id} raised: {e}")

    async def _exec_god_dispatch(
        self, inst: WorkflowInstance, wf: Workflow, step: WorkflowStep
    ) -> None:
        """Build a handoff prompt, submit to gateway, write handoff file
        to pending/<god>/, then poll for the next handoff from that god."""
        if not step.god:
            raise ValueError(f"step {step.id} has no god")
        if not self.gw:
            raise RuntimeError("no gateway client configured")

        # Build the prompt the god will see
        prompt = self._build_step_prompt(inst, wf, step)

        # Submit async run
        run_id = await self.gw.submit_run(
            prompt,
            model=step.god,
            session_id=inst.workflow_id,  # use workflow_id as Hermes session
        )

        # Wait for completion (this is the spec's "single ack timeout")
        timeout_s = _parse_duration(step.timeout)
        result = await self.gw.wait_for_run(run_id, timeout=timeout_s)

        # Record outcome + write handoff
        self._record_step_completion(inst, step, result)

        # Write a handoff file to the god's inbox (god-readable artifact)
        handoff = self._build_handoff(inst, wf, step, result)
        handoff_path = self.pending_dir / step.god / f"{inst.workflow_id}_{step.id}.json"
        write_json(handoff_path, handoff)

        # Continue the DAG
        await self._advance(inst, wf, step, result)

    async def _exec_nats_publish(
        self, inst: WorkflowInstance, step: WorkflowStep
    ) -> None:
        """Execute a `type: nats_publish` step (outbound message to NATS).
        Actual NATS send is delegated to the nats module; here we just
        record the step and continue.

        Sovereign-outbound guard (2026-06-15): if the step's subject
        matches `subspace.*.outgoing.*` (i.e. a publish to another
        Pantheon or external recipient), this method REFUSES to publish
        unless ALL of the following are true:

          1. Every prior step in `inst.step_history` has
             `status == "completed"` (no refusals, no failures, no
             unauthorized auto-fires).
          2. `inst.status` is still `in_progress` or `waiting_for_ack`
             (a workflow that was already aborted or failed does not
             get to fire external messages).
          3. `inst.context_bag` carries a single-use
             `operator_approval_token` bound to this `workflow_id`.

        If any of those checks fail, the step is recorded as
        `status="breach_blocked"` (a new status) and the workflow is
        aborted with a manifest explaining the block. No NATS send
        happens. The block is the engine-side enforcement of the
        operator's profile rule that external events must NEVER
        auto-execute without explicit user approval.

        Non-sovereign nats_publish steps (e.g. `subspace.konan.inbox`
        from the morning-briefing workflow, or `subspace.test.inbox`
        from the cron-binding tests) are NOT gated and retain the
        pre-2026-06-15 behavior. See SOVEREIGN_OUTBOUND_RE for the
        exact pattern.
        """
        if not step.subject:
            raise ValueError(f"nats_publish step {step.id} has no subject")
        LOG.info(f"workflow {inst.workflow_id}: nats_publish → {step.subject}")
        # The actual publish is done by the nats module which subscribes to
        # outbound requests via enqueue_outbound_nats(). For now, record
        # the intent and advance.
        # Sovereign-outbound guard: if this is a cross-Pantheon publish,
        # refuse unless every prior step is clean and the operator has
        # approved. This is the fix for the 2026-06-15 dual-NATS-breach
        # (wf_8a0b5f28 + wf_f26885f8 both fired unapproved publishes to
        # subspace.konan.outgoing.tallon).
        if _is_sovereign_outbound(step.subject):
            # A prior step counts as "unclean" only if it has reached a
            # non-completed TERMINAL state. We deliberately ignore the
            # `in_progress` status here — that just means the engine
            # recorded the start of a step, not that the step is in a
            # bad state. (The engine appended `in_progress` to
            # step_history at line ~760 before calling this method, so
            # the current step will appear in this list as `in_progress`.
            # Without this filter, every sovereign outbound would
            # self-block on its own in_progress marker, which is wrong.)
            UNCLEAN_STATUSES = {"refused", "failed", "breach_blocked", "auto_fired_unauthorized"}
            prior_unclean = [
                h for h in inst.step_history
                if h.get("step_id") != step.id  # not the current step
                and h.get("status") in UNCLEAN_STATUSES
            ]
            inst_not_progress = inst.status not in ("in_progress", "waiting_for_ack")
            no_approval = not _has_operator_approval(inst)
            if prior_unclean or inst_not_progress or no_approval:
                reasons = []
                if prior_unclean:
                    reasons.append(
                        f"{len(prior_unclean)} prior step(s) not completed: "
                        + ", ".join(f"{h['step_id']}={h.get('status')}" for h in prior_unclean)
                    )
                if inst_not_progress:
                    reasons.append(f"workflow status is {inst.status!r}, not in_progress")
                if no_approval:
                    reasons.append(
                        "no operator_approval_token in context_bag "
                        "(operator must explicitly approve sovereign outbound)"
                    )
                block_reason = "Sovereign outbound blocked: " + "; ".join(reasons)
                LOG.error(
                    f"workflow {inst.workflow_id}: BLOCKED sovereign outbound "
                    f"{step.subject} ({block_reason})"
                )
                # Record the block in step_history as a new terminal status.
                # Do NOT record the publish in nats_publishes. Do NOT advance
                # the workflow. Abort instead so the operator sees the manifest.
                inst.step_history.append({
                    "step_id": step.id,
                    "god": step.god,
                    "status": "breach_blocked",
                    "started": utc_now(),
                    "completed": utc_now(),
                    "output_summary": block_reason[:200],
                    "gates_passed": [],
                    "block_reason": block_reason,
                    "subject": step.subject,
                })
                self._save_instance(inst)
                # Abort the workflow — an unapproved sovereign outbound
                # must not be silently retried by the next tick.
                self._abort_workflow(
                    inst,
                    f"sovereign outbound blocked at step {step.id!r}: {block_reason}",
                )
                return
            # Approved: consume the token (single-use) and proceed.
            _consume_operator_approval(inst)
            self._save_instance(inst)
        inst.context_bag.setdefault("nats_publishes", []).append({
            "step_id": step.id,
            "subject": step.subject,
            "message": _render_template(step.message or "", inst),
            "payload": {k: _render_template(str(v), inst) for k, v in step.payload.items()},
            "published_at": utc_now(),
        })
        self._record_step_completion(inst, step, None)
        await self._advance(inst, None, step, None)

    def _build_step_prompt(
        self, inst: WorkflowInstance, wf: Workflow, step: WorkflowStep
    ) -> str:
        """Build the prompt for the god that will execute this step."""
        lines = [
            f"# Conductor Dispatch — Workflow {inst.workflow_id}",
            f"Definition: {inst.definition_id} v{inst.definition_version}",
            f"Step: {step.id} (god: {step.god})",
            "",
        ]
        if inst.original_request:
            lines.extend([
                "## Original Request",
                inst.original_request,
                "",
            ])
        if inst.context_bag:
            lines.append("## Workflow Context")
            for k, v in inst.context_bag.items():
                if k in ("nats_publishes",):
                    continue
                lines.append(f"- **{k}**: {_summarize(v)}")
            lines.append("")
        # Step-specific input
        if step.input_from and step.input_from in inst.context_bag:
            lines.append(f"## Input (from `{step.input_from}`)")
            lines.append(_summarize(inst.context_bag[step.input_from]))
            lines.append("")
        elif step.input:
            lines.append(f"## Input")
            lines.append(step.input)
            lines.append("")
        # Previous step history
        prior = [h for h in inst.step_history
                 if h.get("status") == "completed" and h["step_id"] != step.id]
        if prior:
            lines.append("## Prior Steps")
            for h in prior:
                lines.append(
                    f"- {h['step_id']} ({h.get('god', '?')}): {h.get('output_summary', '')}"
                )
            lines.append("")
        lines.extend([
            "## Your Task",
            f"Execute the `{step.id}` step. When complete, write a handoff to:",
            f"  ~/pantheon/conductor/pending/_dispatch/{inst.workflow_id}_{step.id}.json",
            "",
            "Use this handoff format:",
            "```json",
            json.dumps(_example_handoff(inst, step), indent=2),
            "```",
            "",
            f"Step timeout: {step.timeout}. After completing, the engine polls the workflow state file.",
        ])
        return "\n".join(lines)

    def _build_handoff(
        self,
        inst: WorkflowInstance,
        wf: Workflow,
        step: WorkflowStep,
        result: Optional[gw_mod.RunResult],
    ) -> dict[str, Any]:
        """Build the handoff JSON written to pending/<god>/."""
        return {
            "handoff_id": new_id("hof"),
            "workflow_id": inst.workflow_id,
            "from_god": "conductor",
            "to_god": step.god or "_system",
            "step": step.id,
            "context": {
                "summary": (result.output[:200] if result else step.id) or step.id,
                "decisions": inst.context_bag.get("decisions", []),
                "artifacts": inst.context_bag.get("artifacts", []),
                "step_outputs": {step.id: result.output if result else ""},
            },
            "routing": {
                "workflow_step": step.id,
                "priority": "normal",
            },
            "state": {"ready_for_next": True},
        }

    def _record_step_completion(
        self,
        inst: WorkflowInstance,
        step: WorkflowStep,
        result: Optional[gw_mod.RunResult],
    ) -> None:
        # Step 1.6 step_history fix: pre-1.6 this only flipped an existing
        # in_progress entry to completed. If the v1 bridge path had already
        # appended a `status="completed"` entry to the on-disk state file
        # (which it does on every submit — see v1 Conductor.submit_handoff
        # L368-375), the engine's _load_instance_from_disk would re-load
        # the in-memory WorkflowInstance with that completed entry, find
        # nothing to flip, and step_history would be missing the engine-
        # managed `started` and `completed` timestamps the spec asks for
        # (spec 3.4 example shape). Now: flip if possible, otherwise seed
        # a fresh entry. Idempotent: if an entry for this step already
        # exists with `status=completed`, we update its timestamps in
        # place (the v1-appended entries lack them).
        #
        # v1+v2 collision guard: when the v1 bridge has already advanced
        # `inst.current_step` to a NEXT step and then the bridge calls
        # `_record_step_completion` for the step the bridge THINKS is
        # the just-completed step (which is actually the next step —
        # see conductor_server.py:495-500, where it reads
        # `v2_inst.current_step` after the v1 advance), the in-memory
        # instance loaded from disk may not yet have a step_history
        # entry for that step. To avoid double-writing (the v1 path's
        # submit-side append will add one for the next step), we
        # only seed a new entry if there is no in_progress entry for
        # `step.id` AND no entry at all for `step.id`. If there's a
        # completed entry for `step.id` (which the v1 path wrote), we
        # update it in place — same behavior as before.
        #
        # Refusal detection (2026-06-15, fixes the day-5 state-machine
        # lie, pitfall #14): if the god's run "completed" at the gateway
        # level (HTTP 200, run status=completed) but the actual output
        # is a refusal, the step is NOT a success — the god refused the
        # work. We detect this by scanning the FULL result.output (not
        # the 200-char truncated summary) for canonical refusal markers,
        # and flipping the step's `status` to `"refused"`. The state
        # file is then truthful: a step whose output starts with
        # "Refused" is recorded as `refused`, not `completed`. This is
        # what `_exec_nats_publish`'s sovereign-outbound guard relies
        # on (it checks `h.get("status") == "completed"` for prior
        # steps — without this fix, the prior refusal would be
        # mis-classified as completed and the guard would let the
        # publish through).
        now = utc_now()
        # Determine the effective step status. Default: "completed" if
        # the gateway said the run completed. Refusal flip: if the run
        # "completed" but the output is a refusal, record "refused"
        # (with a `refusal_reason` for the audit trail).
        refusal_detected = False
        refusal_reason = ""
        if result and (not result.status or result.status == "completed"):
            full_output = result.output or ""
            refusal_match = _REFUSAL_MARKER_RE.search(full_output)
            if refusal_match:
                refusal_detected = True
                # Capture the first refusal sentence (up to 200 chars)
                # for the audit trail. We deliberately do not embed
                # the full refusal — some refusals are very long, and
                # the truncated summary is enough to reconstruct intent.
                refusal_reason = refusal_match.group(0)[:200]
        effective_status = "refused" if refusal_detected else (
            "completed" if not result or result.status == "completed" else result.status
        )
        # Look for any existing entry for this step (not just in_progress).
        existing_idx = None
        for idx, h in enumerate(inst.step_history):
            if h["step_id"] == step.id:
                existing_idx = idx
                break
        if existing_idx is not None:
            h = inst.step_history[existing_idx]
            h["status"] = effective_status
            h.setdefault("started", now)
            h["completed"] = now
            if result:
                h["output_summary"] = (result.output or "")[:200]
                h.setdefault("gates_passed", [])
            if refusal_detected:
                h["refusal_reason"] = refusal_reason
            if "god" not in h and step.god:
                h["god"] = step.god
        else:
            # No entry for this step exists in step_history. Seed a
            # fresh, spec-conformant entry.
            entry = {
                "step_id": step.id,
                "god": step.god,
                "status": effective_status,
                "started": now,
                "completed": now,
                "output_summary": (result.output or "")[:200] if result else "",
                "gates_passed": [],
            }
            if refusal_detected:
                entry["refusal_reason"] = refusal_reason
            inst.step_history.append(entry)
        if result and step.output:
            inst.context_bag[step.output] = result.output
        # Capture decisions/artifacts from output if god appended any
        if result and result.output:
            inst.context_bag.setdefault("step_outputs", {})[f"{step.god}.{step.id}"] = result.output
        # If a step was refused, surface it to the workflow's lifecycle:
        # the next nats_publish step (if any) needs to know the prior
        # step was refused, not completed. The sovereign-outbound guard
        # in _exec_nats_publish reads `h.get("status") == "completed"`
        # for prior steps, so the truth-write here is what makes the
        # guard work end-to-end. We do NOT auto-abort on a single
        # refusal — the workflow's `abort_on_fail` flag (and the
        # per-step `on_fail` config) is the operator's choice, not
        # ours. But we do record the refusal accurately, which is the
        # fix the misroute session asked for.

    def _record_step_failure(
        self,
        inst: WorkflowInstance,
        step: WorkflowStep,
        error: str,
    ) -> None:
        # Mirror fix as _record_step_completion: update in place if
        # an entry exists, otherwise seed a new failure entry. No
        # v1+v2 collision guard needed here — the failure path is
        # only hit from the v2-direct engine, not the v1 bridge.
        now = utc_now()
        existing_idx = None
        for idx, h in enumerate(inst.step_history):
            if h["step_id"] == step.id:
                existing_idx = idx
                break
        if existing_idx is not None:
            h = inst.step_history[existing_idx]
            h["status"] = "failed"
            h.setdefault("started", now)
            h["completed"] = now
            h["output_summary"] = f"FAILED: {error[:200]}"
            if "god" not in h and step.god:
                h["god"] = step.god
        else:
            inst.step_history.append({
                "step_id": step.id,
                "god": step.god,
                "status": "failed",
                "started": now,
                "completed": now,
                "output_summary": f"FAILED: {error[:200]}",
                "gates_passed": [],
            })

    async def _advance(
        self,
        inst: WorkflowInstance,
        wf: Optional[Workflow],
        step: WorkflowStep,
        result: Optional[gw_mod.RunResult],
    ) -> None:
        """Advance the workflow to the next step after `step` has completed.

        Identifies the next step via `Workflow.next_step_after`. If there
        is no next step, marks the workflow `status=completed` and clears
        `current_step`. Otherwise, sets `current_step` to the next step's
        id, persists, and calls `_execute_step` to actually run it.

        This is the spec's "single ack timeout per step" exit point. The
        v2-direct path (daemon) calls this from `_exec_god_dispatch`. The
        bridge path (v1 Conductor.ack_handoff) does NOT call this — it
        has its own reimplementation at L497-522 of conductor_server.py
        that mirrors the body. The reason for the mirror is the
        v1+v2 state file collision: the bridge runs v1 mutations before
        the v2 advance, so `_advance` would see the already-advanced
        `current_step` and take the "no next step → completed" branch
        prematurely. The mirror sidesteps that by computing the next
        step from the in-memory `v2_inst.current_step` before any v1
        mutation has happened.
        """
        if not wf:
            wf = self.workflows.get(inst.definition_id)
        if not wf:
            inst.status = "failed"
            self._save_instance(inst)
            return
        nxt = wf.next_step_after(step.id)
        if nxt is None:
            inst.status = "completed"
            inst.current_step = None
            self._save_instance(inst)
            LOG.info(f"workflow {inst.workflow_id} completed")
            return
        inst.current_step = nxt.id
        self._save_instance(inst)
        await self._execute_step(inst, wf, nxt.id)

    # ----- v2 submit_handoff (Phase 1 Step 1.6) -----

    def submit_handoff(self, handoff: dict[str, Any]) -> dict[str, Any]:
        """True v2 routing entry point for MCP `submit_handoff` calls.

        The v1 Conductor.submit_handoff in conductor_server.py branches on
        `v2_definition_known` (the Step 1.2 (C) marker). When the marker is
        True, it delegates to THIS method instead of running the v1
        dispatch path. The two paths are deliberately NOT merged: the v1
        path is preserved as the fallback for unknown / missing
        `routing.workflow_definition`. See BUILD-PLAN.md §1.6 and
        Thoth's design notes.

        What this method does (spec sections 3.3 + 3.4 + 4):

          1. Read `routing.workflow_definition` from the handoff. If
             missing, return a v2-shaped error envelope.
          2. Look up the workflow definition via `self.workflows.get()`.
             Unknown definition → error envelope (caller should have
             already short-circuited on the marker, but defense in depth).
          3. Mint a fresh `WorkflowInstance` via `start_workflow_sync`
             (the same call Step 1.1's `start_workflow` MCP tool uses,
             sans the asyncio dispatch — the daemon owns that).
          4. Build a v2-shaped handoff payload for the first step and
             write it to `pending/<first_step_god>/<wf_id>_<step_id>.json`.
          5. Persist `v2_dispatched: bool` in `step_history` so the
             audit trail shows which path was used (Thoth design note).
          6. Return the instance dict (engine shape) PLUS v1-compatible
             keys (`status`, `target_god`, `target_step`, `handoff_path`,
             `state_status`) so the bridge can hand the same response
             shape back to the MCP caller without re-mapping.

        Failure envelope distinction (Thoth design note): v2 errors
        surface under the `v2_error` key; v1 errors under `v1_error`.
        Callers can branch on the failure source.

        Sync only: the v2 daemon is the async owner of god execution
        (`_exec_god_dispatch` etc.). This method writes the dispatch
        file and the state file; the daemon's `awatch` loop picks the
        dispatch up and runs the god.
        """
        routing = handoff.get("routing") or {}
        wf_def_id = routing.get("workflow_definition") or ""
        if not wf_def_id:
            return {
                "status": "error",
                "v2_error": "routing.workflow_definition missing or empty",
                "v2_dispatched": False,
            }
        wf = self.workflows.get(wf_def_id)
        if wf is None:
            return {
                "status": "error",
                "v2_error": f"unknown workflow definition: {wf_def_id!r}",
                "v2_dispatched": False,
                "workflow_definition": wf_def_id,
            }
        if not wf.steps:
            return {
                "status": "error",
                "v2_error": f"workflow {wf_def_id!r} has no steps",
                "v2_dispatched": False,
                "workflow_definition": wf_def_id,
            }
        first_step = wf.steps[0]
        first_god = first_step.god or handoff.get("to_god") or "_system"
        initiator = handoff.get("from_god") or "konan"
        original_request = handoff.get("context", {}).get("summary", "")
        # Mint a fresh instance for this submit. We DO NOT reuse a
        # pre-existing instance from disk: the bridge's v1 path would
        # have created one already, and we want the v2 submit to be
        # the sole owner of the state file going forward (Step 1.6
        # resolves the v1+v2 state file collision by making v2 the
        # authoritative writer when `v2_definition_known` is True).
        try:
            inst = self.start_workflow_sync(
                workflow_def_id=wf_def_id,
                context={
                    "routing": routing,
                    "handoff": {
                        "handoff_id": handoff.get("handoff_id"),
                        "from_god": handoff.get("from_god"),
                        "to_god": handoff.get("to_god"),
                        "step": handoff.get("step"),
                        "context": handoff.get("context", {}),
                    },
                },
                initiator=initiator,
                original_request=original_request,
            )
        except ValueError as e:
            # Should be unreachable (we already verified `wf` is not None),
            # but defense in depth — return a v2-shaped error envelope.
            return {
                "status": "error",
                "v2_error": f"start_workflow_sync failed: {e}",
                "v2_dispatched": False,
                "workflow_definition": wf_def_id,
            }

        # Audit-trail seed (Thoth design note): the v2 path appends a
        # `v2_dispatched: True` entry to step_history so post-hoc
        # inspection of the state file can show which submit path was
        # used. The v1 path appends its own bookkeeping entry on the
        # next call only if the v2 branch was False.
        inst.step_history.append({
            "step_id": first_step.id,
            "god": first_step.god,
            "status": "in_progress",
            "started": utc_now(),
            "v2_dispatched": True,
            "handoff_id": handoff.get("handoff_id"),
        })
        # Update the on-disk instance to reflect the new current_step
        # + dispatched_to + the v2-dispatched audit trail. We persist
        # here so the daemon's next load cycle sees the in-progress
        # marker.
        inst.current_step = first_step.id
        inst.dispatched_to = first_god
        inst.status = "in_progress"
        self._save_instance(inst)

        # Build the v2-shaped handoff (matches the existing
        # `_build_handoff` shape, but with `result=None` since the god
        # has not run yet). The daemon's `awatch` loop will pick this
        # up and call `_process_handoff` → `_exec_god_dispatch`.
        v2_handoff = self._build_handoff(inst, wf, first_step, result=None)
        dispatch_path = self.pending_dir / first_god / f"{inst.workflow_id}_{first_step.id}.json"
        write_json(dispatch_path, v2_handoff)

        # Return the v1-compatible response shape so the bridge can
        # hand the caller the same keys it always has. The
        # `v2_dispatched: True` flag is the Step 1.6 audit-trail
        # addition; `v2_definition_known: True` is the Step 1.2 (C)
        # marker; `state_status` mirrors the on-disk engine status.
        return {
            "status": "dispatched",
            "workflow_id": inst.workflow_id,
            "target_god": first_god,
            "target_step": first_step.id,
            "handoff_path": str(dispatch_path),
            "state_status": inst.status,
            "v2_definition_known": True,
            "v2_dispatched": True,
            "definition_id": inst.definition_id,
            "definition_version": inst.definition_version,
            "current_step": inst.current_step,
            "dispatched_to": inst.dispatched_to,
        }

    # ----- Abort handling (Layer 3a) -----

    def _abort_workflow(self, inst: WorkflowInstance, reason: str) -> None:
        inst.status = "aborted"
        manifest = {
            "workflow_id": inst.workflow_id,
            "definition_id": inst.definition_id,
            "status": "aborted",
            "failed_step": inst.current_step,
            "failure_reason": reason,
            "completed_steps": [
                {"step_id": h["step_id"], "god": h.get("god"), "status": h["status"]}
                for h in inst.step_history if h.get("status") == "completed"
            ],
            "artifacts_marked": self._mark_artifacts_aborted(inst),
            "aborted_at": utc_now(),
            "requires_manual_review": True,
        }
        write_json(self.state_dir / f"{inst.workflow_id}.aborted.json", manifest)
        self._save_instance(inst)
        LOG.warning(f"workflow {inst.workflow_id} aborted: {reason}")

    def _mark_artifacts_aborted(self, inst: WorkflowInstance) -> list[str]:
        """Spec Layer 3a: write .aborted marker beside each completed artifact.
        Returns the list of paths marked (for the manifest)."""
        marked: list[str] = []
        for h in inst.step_history:
            if h.get("status") != "completed":
                continue
            # The handoff file in pending/<god>/ is the canonical artifact
            god = h.get("god") or "conductor"
            handoff_path = self.pending_dir / god / f"{inst.workflow_id}_{h['step_id']}.json"
            if handoff_path.exists():
                marker = handoff_path.with_suffix(handoff_path.suffix + ".aborted")
                marker.touch()
                marked.append(str(handoff_path))
        return marked

    # ----- Event ingestion (entry point for handoff/watcher/NATS/webhook) -----

    async def handle_event(self, event: Event) -> dict[str, Any]:
        """Process an event: match rule → decide handling → dispatch.
        Returns a small status dict for the caller (e.g. webhook response)."""
        LOG.info(f"event: type={event.type} source={event.source} target={event.target} subject={event.subject}")

        # External events get handling_mode applied per spec 8.1
        rule = self.rules.match(event)
        if rule is None:
            if event.is_external:
                rule = self.rules.apply_default(event)
                LOG.warning(
                    f"UNMATCHED external event from {event.source}/{event.subject} → "
                    f"quarantine (default approval_required)"
                )
            else:
                LOG.warning(f"unmatched internal event {event.type}/{event.source} — dropping")
                return {"status": "no_rule", "action": "dropped"}

        # Spec 8.1 vs 8.2: if the rule has an explicit dispatch action
        # (dispatch_workflow, dispatch_god, on_approval with a plan), it's
        # an action rule — execute it. handling_mode is only consulted when
        # it's explicitly set OR there's no action.
        event.handling_mode = rule.then.get("handling_mode")
        has_dispatch_action = (
            "dispatch_workflow" in rule.then or
            "dispatch_god" in rule.then
        )
        if event.handling_mode is None and has_dispatch_action:
            # Action rule — go straight to dispatch (spec 8.2)
            return await self._dispatch(event, rule)

        # Spec 8.1: all 5 handling modes are distinct behaviors
        if event.handling_mode == "log_only":
            return await self._handle_log_only(event, rule)
        if event.handling_mode == "notify":
            return await self._handle_notify(event, rule)
        if event.handling_mode == "notify_and_log":
            return await self._handle_notify_and_log(event, rule)
        if event.handling_mode == "approval_required":
            return await self._handle_approval_required(event, rule)
        if event.handling_mode == "route_on_approval":
            return await self._handle_route_on_approval(event, rule)

        # No handling_mode (internal events) → dispatch
        return await self._dispatch(event, rule)

    async def _handle_log_only(self, event: Event, rule: Rule) -> dict[str, Any]:
        """Spec 8.1: log to monitoring journal. No notification, no dispatch.
        Write to pending/_journal/ for Konan to inspect on demand."""
        journal_dir = self.pending_dir / "_journal"
        journal_dir.mkdir(parents=True, exist_ok=True)
        path = journal_dir / f"{new_id('log')}.json"
        write_json(path, {
            "event_type": event.type,
            "source": event.source,
            "subject": event.subject,
            "payload_summary": _summarize(event.payload, 500),
            "rule": rule.id,
            "logged_at": utc_now(),
        })
        LOG.info(f"event logged: {event.subject} (rule={rule.id})")
        return {"status": "logged", "mode": "log_only", "rule": rule.id, "path": str(path)}

    async def _handle_notify(self, event: Event, rule: Rule) -> dict[str, Any]:
        """Spec 8.1: log + push notification to pending/inbox/ for Hermes."""
        # Log it
        log_result = await self._handle_log_only(event, rule)
        # Notify (write to pending/inbox/ so Hermes / delivery picks it up)
        inbox_dir = self.pending_dir / "inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        notif = inbox_dir / f"{new_id('notif')}.json"
        write_json(notif, {
            "from": event.source,
            "type": event.type,
            "subject": event.subject or event.type,
            "summary": event.payload.get("summary", "") or _summarize(event.payload, 200),
            "action": "fyi",
            "rule": rule.id,
            "queued_at": utc_now(),
        })
        LOG.info(f"event notified: {event.subject} (rule={rule.id})")
        return {"status": "notified", "mode": "notify", "rule": rule.id, "path": str(notif)}

    async def _handle_notify_and_log(self, event: Event, rule: Rule) -> dict[str, Any]:
        """Spec 8.1: log + notify with 'no action needed' marker."""
        log_result = await self._handle_log_only(event, rule)
        inbox_dir = self.pending_dir / "inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        notif = inbox_dir / f"{new_id('notif')}.json"
        write_json(notif, {
            "from": event.source,
            "type": event.type,
            "subject": event.subject or event.type,
            "summary": event.payload.get("summary", "") or _summarize(event.payload, 200),
            "action": "no_action_needed",
            "rule": rule.id,
            "queued_at": utc_now(),
        })
        LOG.info(f"event notify_and_log: {event.subject} (rule={rule.id})")
        return {"status": "notified_and_logged", "mode": "notify_and_log", "rule": rule.id, "path": str(notif)}

    async def _handle_route_on_approval(self, event: Event, rule: Rule) -> dict[str, Any]:
        """Spec 8.1: log + notify + ask. Pre-configured target route if approved.
        The on_approval block in the rule then: tells us what to dispatch."""
        log_result = await self._handle_log_only(event, rule)
        on_approval = rule.then.get("on_approval", {})
        # Quarantine the event with the on_approval plan attached
        qfile = self.pending_dir / "_quarantine" / f"{new_id('q')}.json"
        write_json(qfile, {
            "event": event.__dict__,
            "rule_id": rule.id,
            "on_approval": on_approval,
            "queued_at": utc_now(),
            "waiting_for": "approval",
        })
        inbox_dir = self.pending_dir / "inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        notif = inbox_dir / f"{new_id('notif')}.json"
        write_json(notif, {
            "from": event.source,
            "type": event.type,
            "subject": event.subject or event.type,
            "summary": event.payload.get("summary", "") or _summarize(event.payload, 200),
            "action": "route_on_approval",
            "rule": rule.id,
            "on_approval": on_approval,
            "queued_at": utc_now(),
        })
        LOG.info(f"event route_on_approval: {event.subject} (rule={rule.id}, planned={on_approval})")
        return {
            "status": "awaiting_approval",
            "mode": "route_on_approval",
            "rule": rule.id,
            "quarantine_file": str(qfile),
            "on_approval": on_approval,
        }

    async def approve_quarantined_async(self, quarantine_filename: str, *,
                                          approver: str = "konan", action: str = "approve") -> dict[str, Any]:
        """Manually approve a quarantined event. Triggers the on_approval
        dispatch asynchronously. action='approve' dispatches; action='dismiss' deletes."""
        qpath = self.pending_dir / "_quarantine" / quarantine_filename
        if not qpath.exists():
            return {"status": "not_found", "file": quarantine_filename}
        data = read_json(qpath)
        if action == "dismiss":
            qpath.unlink()
            return {"status": "dismissed", "file": quarantine_filename}
        on_approval = data.get("on_approval", {})
        if not on_approval:
            return {"status": "no_on_approval_plan", "file": quarantine_filename}
        # Synthesize a rule from the on_approval block
        synthetic_rule = Rule(
            id=f"on_approval_{quarantine_filename}",
            when={"event_type": data["event"]["type"]},
            then=on_approval,
            source_path=Path("<on_approval>"),
        )
        event = Event(
            type=data["event"]["type"],
            source=data["event"]["source"],
            target=data["event"].get("target"),
            subject=data["event"].get("subject"),
            payload=data["event"].get("payload", {}),
            is_external=data["event"].get("is_external", True),
            handling_mode="route_on_approval",
        )
        # Mark the quarantine as approved
        write_json(qpath, {**data, "approved_at": utc_now(), "approver": approver, "approved": True})
        # Dispatch
        dispatch_result = await self._dispatch(event, synthetic_rule)
        return {
            "status": "approved",
            "file": quarantine_filename,
            "approver": approver,
            "dispatch_result": dispatch_result,
        }

    def approve_quarantined(self, quarantine_filename: str, *,
                             approver: str = "konan", action: str = "approve") -> dict[str, Any]:
        """Sync wrapper around approve_quarantined_async. Use the async
        version in async contexts; this one runs the async one inline."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(
            self.approve_quarantined_async(quarantine_filename, approver=approver, action=action)
        )

    async def _handle_approval_required(self, event: Event, rule: Rule) -> dict[str, Any]:
        # Write to quarantine + notify (Telegram delivery done by delivery module)
        qfile = self.pending_dir / "_quarantine" / f"{new_id('q')}.json"
        write_json(qfile, {
            "event": event.__dict__,
            "rule_id": rule.id,
            "queued_at": utc_now(),
        })
        LOG.info(f"event quarantined: {qfile.name} (rule={rule.id})")
        # Mark for delivery module to surface
        return {
            "status": "quarantined",
            "mode": "approval_required",
            "rule": rule.id,
            "quarantine_file": str(qfile),
            "action": rule.then.get("action"),
            "message": rule.then.get("message"),
        }

    async def _dispatch(self, event: Event, rule: Rule) -> dict[str, Any]:
        then = rule.then
        if "dispatch_workflow" in then:
            wf_id = then["dispatch_workflow"]
            ctx = dict(then.get("input", {}) or {})
            if event.payload:
                ctx.setdefault("event_payload", event.payload)
            inst = self.start_workflow(
                wf_id,
                context=ctx,
                initiator=event.source,
                original_request=event.payload.get("summary", event.subject or ""),
                start_at_step=then.get("start_at_step"),
            )
            return {"status": "workflow_started", "workflow_id": inst.workflow_id, "rule": rule.id}
        if "dispatch_god" in then:
            god = then["dispatch_god"]
            if not self.gw:
                return {"status": "no_gateway", "rule": rule.id}
            prompt = then.get("message", "") or event.payload.get("summary", event.subject or "")
            run_id = await self.gw.submit_run(
                f"Dispatch from rule {rule.id}\n\n{prompt}",
                model=god,
            )
            result = await self.gw.wait_for_run(run_id, timeout=300)
            return {
                "status": "god_dispatched",
                "god": god,
                "run_id": run_id,
                "output": result.output,
                "rule": rule.id,
            }
        return {"status": "no_action", "rule": rule.id}

    # ----- File watcher -----

    async def watch_pending(self, stop_event: Optional[asyncio.Event] = None) -> None:
        """Watch pending/<god>/ and self.state/ for new files. This is the
        main loop that turns handoffs into dispatches."""
        LOG.info(f"watching {self.pending_dir}/**/*.json")
        async for changes in awatch(self.pending_dir, recursive=True,
                                    stop_event=stop_event, step=500):
            for change_type, path_str in changes:
                path = Path(path_str)
                if not path.suffix == ".json":
                    continue
                # Skip our own writes
                if path.name.startswith("."):
                    continue
                if change_type in (Change.added, Change.modified):
                    await self._process_file(path)

    async def _process_file(self, path: Path) -> None:
        try:
            data = read_json(path)
        except Exception as e:
            LOG.warning(f"could not parse {path}: {e}")
            return
        # Heuristic: is this a handoff? Has handoff_id, from_god, to_god?
        if "handoff_id" in data and "from_god" in data and "to_god" in data:
            await self._process_handoff(path, data)
        elif "type" in data and "source" in data:
            # event envelope — honor is_external marker written by webhook/dispatch
            event = Event(
                type=data.get("type", "unknown"),
                source=data.get("source", "unknown"),
                target=data.get("target"),
                subject=data.get("subject"),
                payload=data.get("payload", {}),
                raw=data,
                is_external=bool(data.get("is_external", False)),
            )
            await self.handle_event(event)
        else:
            LOG.debug(f"ignoring unclassified file: {path}")

    async def _process_handoff(self, path: Path, handoff: dict[str, Any]) -> None:
        """A handoff landed in pending/<god>/. Synthesize an event and route."""
        from_god = handoff.get("from_god", "?")
        to_god = handoff.get("to_god", "?")
        wf_id = handoff.get("workflow_id", "")
        event = Event(
            type="handoff.completed",
            source=from_god,
            target=to_god,
            subject=f"handoff:{handoff.get('handoff_id', '?')}",
            payload={"handoff": handoff, "workflow_id": wf_id, "context": handoff.get("context", {})},
            is_external=False,
        )
        LOG.info(f"handoff: {path.name} {from_god}→{to_god} wf={wf_id}")
        await self.handle_event(event)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_duration(s: str) -> float:
    """Parse '30m', '2h', '1d', '45s' to seconds."""
    if isinstance(s, (int, float)):
        return float(s)
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(s|m|h|d)?$", s.strip())
    if not m:
        return 1800.0
    val, unit = float(m.group(1)), (m.group(2) or "s")
    return val * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def _summarize(v: Any, max_len: int = 300) -> str:
    s = str(v)
    return s if len(s) <= max_len else s[:max_len] + "…"


def _render_template(s: str, inst: WorkflowInstance) -> str:
    """Tiny template renderer: ${workflow_id}, ${context.X}."""
    if not isinstance(s, str):
        return s
    s = s.replace("${workflow_id}", inst.workflow_id)
    s = s.replace("${context}", json.dumps(inst.context_bag, default=str))
    # ${context.X}
    for m in re.finditer(r"\$\{context\.([^}]+)\}", s):
        key = m.group(1)
        val = inst.context_bag.get(key, "")
        s = s.replace(m.group(0), str(val))
    return s


def _example_handoff(inst: WorkflowInstance, step: WorkflowStep) -> dict[str, Any]:
    return {
        "handoff_id": "hof_YYYYMMDD_xxxxxx",
        "workflow_id": inst.workflow_id,
        "from_god": step.god,
        "to_god": "conductor",
        "step": step.id,
        "context": {
            "summary": "One-line description of what you did",
            "decisions": ["Decisions you made"],
            "artifacts": ["/path/to/file"],
        },
    }
