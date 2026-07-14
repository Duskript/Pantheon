"""HephaestusBuildCard — the contract between spec decomposer and god-workers.

Every card written to the kanban by Hephaestus (or any spec-to-cards skill)
MUST validate against ``HEPHAESTUS_BUILD_CARD_SCHEMA``. The
``additionalProperties: false`` constraint is the load-bearing rule:
no field outside this set is allowed. If a card has an unexpected
field, the validator rejects it before it ever reaches the DB.

Three public surfaces:

1. ``HEPHAESTUS_BUILD_CARD_SCHEMA`` — JSON Schema (draft-07) for validation
2. ``HephaestusBuildCard`` — typed dataclass for in-memory use
3. ``validate_card`` / ``render_worker_prompt`` / ``detect_conflicts`` — helpers

Why this exists: Hephaestus previously read a 232-line freeform build spec
and used engineering judgment to pick what to build. That judgment drift
produced ``twitter_bot.py`` (24K, off-spec, shipped 2.5h before the
"Twitter OFF the table" message). The contract makes spec compliance
mechanical — every card the decomposer writes is small, bounded, and
auditable against the spec.

Mirrored at ``hermes-agent/hermes_cli/kanban_contract.py`` so the local
``hermes_cli`` package can import it without sys.path manipulation. Keep
both copies byte-identical.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Hard cap on max_loc_delta. Cards above this are rejected at creation time.
# 100 LoC is the "this needs to be decomposed further" threshold.
MAX_LOC_DELTA_HARD_CAP = 100

# Standard out_of_scope rules pre-filled into every card. Workers may add
# more, but these five are the floor — they are the safety belt that
# prevents drift.
STANDARD_OUT_OF_SCOPE = [
    "Do not modify any file outside output.file",
    "Do not add new dependencies (requirements.txt, package.json, etc.)",
    "Do not refactor unrelated code",
    "Do not change the public API of existing classes/functions",
    "Do not add new tests beyond what verify.command requires",
]

# card_id pattern — strict format prevents collisions and aids audit trails.
_CARD_ID_RE = re.compile(r"^hep-\d{4}-\d{2}-\d{2}-\d{3}$")

# Tautological verify commands — these are the anti-pattern. A verify
# command that always succeeds tells us nothing.
_TAUTOLOGIES = ("true", "echo ok", ":")

# Substrings in verify commands that suggest shell injection or unsafe
# filesystem operations. We block these at card-creation time rather than
# rely on the dispatcher to sanitize.
_DANGEROUS_SUBSTRINGS = ("`", "$()", "&& rm", "; rm", "| rm", "$(rm")


# ---------------------------------------------------------------------------
# JSON Schema
# ---------------------------------------------------------------------------

HEPHAESTUS_BUILD_CARD_SCHEMA = {
    "$schema": "https://json-schema.org/draft-07/schema#",
    "title": "HephaestusBuildCard",
    "type": "object",
    # CRITICAL: no extra fields. If a card has any field outside this set,
    # the validator rejects it. This is the load-bearing constraint.
    "additionalProperties": False,
    "required": [
        "card_id", "type", "assignee", "input", "output",
        "verify", "out_of_scope",
    ],
    "properties": {
        "card_id": {
            "type": "string",
            "pattern": r"^hep-\d{4}-\d{2}-\d{2}-\d{3}$",
            "description": "Unique card id, format hep-YYYY-MM-DD-NNN",
        },
        "type": {
            "enum": ["build", "review", "qa"],
            "description": (
                "build (Marvin writes code), review (Hephaestus self-checks), "
                "qa (Ponytail QA gate)"
            ),
        },
        "assignee": {
            "enum": ["marvin", "hephaestus", "iris", "rheta", "konan"],
            "description": "The god profile that picks up this card",
        },
        "depends_on": {
            "type": "array",
            "items": {"type": "string"},
            "default": [],
            "description": "List of card_ids that must be done first",
        },
        "conflicts_with": {
            "type": "array",
            "items": {"type": "string"},
            "default": [],
            "description": "List of card_ids that share state — never run in parallel",
        },
        "parallel_group": {
            "type": "string",
            "pattern": r"^[a-z0-9-]+$",
            "description": (
                "Optional. Cards in the same group are confirmed-safe to run "
                "in parallel even without explicit depends_on chain."
            ),
        },
        "input": {
            "type": "object",
            "required": ["files"],
            "properties": {
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
                "context_lines": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                    "description": "Optional. Which lines/sections of the input files matter. Keep short.",
                },
            },
        },
        "output": {
            "type": "object",
            "required": ["file", "change"],
            "properties": {
                "file": {"type": "string", "description": "Path to write to"},
                "change": {
                    "type": "string",
                    "maxLength": 200,
                    "description": "One-sentence description of the code change",
                },
                "max_loc_delta": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 30,
                    "description": "HARD CAP on LoC change. Card rejected if >100.",
                },
            },
        },
        "verify": {
            "type": "object",
            "required": ["command", "must_pass"],
            "properties": {
                "command": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Exact shell command. Must exit 0 when the change is correct.",
                },
                "must_pass": {"type": "boolean", "default": True},
                "timeout_seconds": {
                    "type": "integer",
                    "default": 30,
                    "maximum": 300,
                    "description": "Verify command timeout. Default 30s, max 5min.",
                },
            },
        },
        "out_of_scope": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "description": (
                "Explicit list of things the worker must NOT do. "
                "Min 3 entries — this is the safety belt."
            ),
        },
        "evidence_required": {
            "type": "array",
            "items": {
                "enum": [
                    "diff_of_changed_file",
                    "output_of_verify_command",
                    "list_of_new_files",
                    "summary_of_changes",
                ],
            },
            "default": ["diff_of_changed_file", "output_of_verify_command"],
            "description": "What the worker must return when completing the card.",
        },
    },
}


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class HephaestusBuildCard:
    """Validated, in-memory representation of a card.

    Use ``from_dict`` to construct from a validated dict, or pass
    keyword arguments directly. ``to_dict`` / ``to_json`` serialize
    cleanly (drops None and empty defaults).
    """

    card_id: str
    type: str
    assignee: str
    input: dict
    output: dict
    verify: dict
    out_of_scope: list
    depends_on: list = field(default_factory=list)
    conflicts_with: list = field(default_factory=list)
    parallel_group: Optional[str] = None
    evidence_required: list = field(default_factory=lambda: [
        "diff_of_changed_file", "output_of_verify_command",
    ])

    def to_dict(self) -> dict:
        d = asdict(self)
        # Drop None and empty lists so the rendered output is clean.
        return {k: v for k, v in d.items() if v is not None and v != []}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _manual_validate(card_dict: dict) -> list[str]:
    """Manual schema validation fallback (used if jsonschema isn't installed).

    Returns a list of error messages; empty list means valid.
    """
    errors: list[str] = []
    required = HEPHAESTUS_BUILD_CARD_SCHEMA["required"]
    for field_name in required:
        if field_name not in card_dict:
            errors.append(f"required field {field_name!r} missing")
    if HEPHAESTUS_BUILD_CARD_SCHEMA.get("additionalProperties") is False:
        allowed = set(HEPHAESTUS_BUILD_CARD_SCHEMA["properties"].keys())
        extras = set(card_dict.keys()) - allowed
        if extras:
            errors.append(
                f"unexpected fields: {sorted(extras)}. "
                f"Only allowed: {sorted(allowed)}"
            )
    return errors


def validate_card(card_dict: dict) -> tuple[bool, list[str]]:
    """Validate a card dict against the schema and contract rules.

    Returns ``(is_valid, list_of_errors)``. Never raises — all failures
    surface as returned error messages.

    The function runs in two passes:

    1. JSON Schema validation via ``jsonschema`` (with manual fallback).
    2. Contract-specific checks: max_loc_delta hard cap, out_of_scope
       minimum, card_id pattern, tautological/dangerous verify commands.

    Both passes run even if the first one fails — the caller gets every
    reason a card is invalid in one shot rather than fixing one error
    only to discover the next.
    """
    if not isinstance(card_dict, dict):
        return False, [f"card must be a dict, got {type(card_dict).__name__}"]

    errors: list[str] = []

    # Pass 1: JSON Schema
    try:
        import jsonschema  # type: ignore
        try:
            jsonschema.validate(instance=card_dict, schema=HEPHAESTUS_BUILD_CARD_SCHEMA)
        except jsonschema.ValidationError as exc:
            # ``exc.message`` is human-readable; ``exc.path`` pinpoints the bad field.
            path = "/".join(str(p) for p in exc.absolute_path) or "<root>"
            errors.append(f"schema: {path}: {exc.message}")
        except jsonschema.SchemaError as exc:
            # Schema itself is broken — that's a bug in this file, not the card.
            errors.append(f"schema internal error: {exc.message}")
    except ImportError:
        errors.extend(_manual_validate(card_dict))

    # Pass 2: contract-specific checks (always run)
    out = card_dict.get("output")
    if isinstance(out, dict):
        mld = out.get("max_loc_delta")
        if isinstance(mld, int) and mld > MAX_LOC_DELTA_HARD_CAP:
            errors.append(
                f"max_loc_delta {mld} exceeds hard cap {MAX_LOC_DELTA_HARD_CAP}. "
                f"Card is too big — decompose further."
            )

    oos = card_dict.get("out_of_scope")
    if isinstance(oos, list) and len(oos) < 3:
        errors.append(
            f"out_of_scope has {len(oos)} entries; min 3 required."
        )

    cid = card_dict.get("card_id")
    if isinstance(cid, str) and not _CARD_ID_RE.match(cid):
        errors.append(
            f"card_id {cid!r} doesn't match pattern hep-YYYY-MM-DD-NNN"
        )

    verify = card_dict.get("verify")
    if isinstance(verify, dict):
        cmd = verify.get("command")
        if isinstance(cmd, str):
            stripped = cmd.strip()
            if stripped in _TAUTOLOGIES:
                errors.append(
                    f"verify.command is {cmd!r} — a tautology. Use a real check."
                )
            for bad in _DANGEROUS_SUBSTRINGS:
                if bad in cmd:
                    errors.append(
                        f"verify.command contains dangerous shell pattern {bad!r}: {cmd!r}"
                    )
                    break  # one dangerous pattern is enough to reject

    return (len(errors) == 0, errors)


# ---------------------------------------------------------------------------
# Worker prompt rendering
# ---------------------------------------------------------------------------


def render_worker_prompt(card: HephaestusBuildCard) -> str:
    """Render a card into a tight, deterministic prompt for the worker.

    The output is what Marvin (or whoever) sees when picking up the card.
    It is intentionally short — every line is contract, not context. If
    a prompt exceeds 2KB, drift has crept in (the renderer is supposed to
    be terse, not narrative).
    """
    out_of_scope_str = "\n".join(f"  - {rule}" for rule in card.out_of_scope)
    input_files = "\n".join(f"  - {f}" for f in card.input.get("files", []))
    context_lines = card.input.get("context_lines", []) or []
    context_str = ""
    if context_lines:
        context_str = "  CONTEXT:\n" + "\n".join(f"    - {c}" for c in context_lines)

    evidence = "\n".join(f"  - {e}" for e in card.evidence_required)
    timeout = (card.verify or {}).get("timeout_seconds", 30)
    max_loc = (card.output or {}).get("max_loc_delta", 30)

    deps_str = ""
    if card.depends_on:
        deps_str = (
            f"DEPENDS ON (must be done first): {', '.join(card.depends_on)}\n"
        )

    conflicts_str = ""
    if card.conflicts_with:
        conflicts_str = (
            f"DO NOT RUN IN PARALLEL WITH: {', '.join(card.conflicts_with)}\n"
        )

    parallel_str = ""
    if card.parallel_group:
        parallel_str = f"PARALLEL GROUP: {card.parallel_group}\n"

    return (
        f"TASK: {card.card_id}\n"
        f"TYPE: {card.type}\n"
        f"ASSIGNEE: {card.assignee}\n"
        f"{deps_str}{conflicts_str}{parallel_str}"
        f"INPUT FILES:\n{input_files}\n"
        f"{context_str}\n"
        f"OUTPUT:\n"
        f"  FILE: {card.output['file']}\n"
        f"  CHANGE: {card.output['change']}\n"
        f"  MAX LoC DELTA: {max_loc}\n"
        f"\n"
        f"VERIFY (must exit 0):\n"
        f"  {card.verify['command']}\n"
        f"  TIMEOUT: {timeout}s\n"
        f"\n"
        f"OUT OF SCOPE — DO NOT:\n"
        f"{out_of_scope_str}\n"
        f"\n"
        f"EVIDENCE REQUIRED (return these when done):\n"
        f"{evidence}\n"
        f"\n"
        f"Begin. Return the diff and the verify command output.\n"
    )


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------


def detect_conflicts(
    cards: list[HephaestusBuildCard],
) -> list[tuple[str, str, str]]:
    """Detect potential conflicts between cards.

    Returns a list of ``(card_a_id, card_b_id, reason)`` tuples. The
    caller decides what to do — typically auto-set ``conflicts_with``
    on both cards so the dispatcher knows never to run them in parallel.

    Conflict types detected:

    * Same ``output.file`` — two cards cannot both write the same file.
    * Same ``parallel_group`` AND shared input — race condition on reads.

    Same ``depends_on`` chain is NOT a conflict (that's the point of
    depends_on — they run sequentially).
    """
    conflicts: list[tuple[str, str, str]] = []
    for i, a in enumerate(cards):
        for b in cards[i + 1:]:
            a_file = (a.output or {}).get("file")
            b_file = (b.output or {}).get("file")
            if a_file and a_file == b_file:
                conflicts.append((a.card_id, b.card_id, "same output file"))
                continue
            if (a.parallel_group and a.parallel_group == b.parallel_group):
                a_inputs = set((a.input or {}).get("files", []))
                b_inputs = set((b.input or {}).get("files", []))
                shared = a_inputs & b_inputs
                if shared:
                    conflicts.append((
                        a.card_id, b.card_id,
                        f"same parallel_group + shared input: {sorted(shared)}",
                    ))
    return conflicts
