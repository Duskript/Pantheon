"""TDD tests for the HephaestusBuildCard contract.

Each test maps to an acceptance criterion in the spec. Run from the
repository root:

    cd /home/konan/pantheon && python3 -m pytest hermes_cli/kanban_contract_test.py -v

The 12 tests cover:
  1.  Minimal valid card passes validation
  2.  additionalProperties: false — extra fields are rejected
  3.  Required fields — missing card_id is rejected
  4.  card_id pattern — must be hep-YYYY-MM-DD-NNN
  5.  max_loc_delta hard cap (100) — oversized cards are rejected
  6.  out_of_scope minimum — fewer than 3 entries is rejected
  7.  Tautological verify command (`true`) is rejected
  8.  Dangerous shell patterns in verify command are rejected
  9.  render_worker_prompt produces tight, deterministic output (< 2KB)
  10. detect_conflicts — same output file
  11. detect_conflicts — different output files, no conflict
  12. depends_on + parallel_group are independent fields
"""
from __future__ import annotations

import pytest

from hermes_cli.kanban_contract import (
    HEPHAESTUS_BUILD_CARD_SCHEMA,
    MAX_LOC_DELTA_HARD_CAP,
    STANDARD_OUT_OF_SCOPE,
    HephaestusBuildCard,
    detect_conflicts,
    render_worker_prompt,
    validate_card,
)


def _minimal_card(**overrides) -> dict:
    """Return a card dict that passes validation. Apply overrides last.

    Each test starts from this baseline and tweaks exactly one thing,
    so the failure point is unambiguous.
    """
    base = {
        "card_id": "hep-2026-06-21-001",
        "type": "build",
        "assignee": "marvin",
        "input": {
            "files": ["/home/konan/athenaeum/Codex-Work/side-hustle-crm/lead.py"],
            "context_lines": ["the Lead dataclass at the top of the file"],
        },
        "output": {
            "file": "/home/konan/athenaeum/Codex-Work/side-hustle-crm/lead.py",
            "change": "Add class LeadStore with methods add, get, mark_contacted",
            "max_loc_delta": 30,
        },
        "verify": {
            "command": 'python3 -c "from lead import LeadStore; s = LeadStore(\\"/tmp/x.json\\"); s.add({\\"id\\": \\"1\\"})"',
            "must_pass": True,
            "timeout_seconds": 30,
        },
        "out_of_scope": STANDARD_OUT_OF_SCOPE[:3],
        "evidence_required": ["diff_of_changed_file", "output_of_verify_command"],
    }
    base.update(overrides)
    return base


# ---- AC1 --------------------------------------------------------------------
def test_minimal_card_validates():
    """AC1: A minimal valid card passes validation."""
    is_valid, errors = validate_card(_minimal_card())
    assert is_valid, f"Expected valid, got errors: {errors}"


# ---- AC2 --------------------------------------------------------------------
def test_extra_fields_rejected():
    """AC2: additionalProperties: false — extra fields are rejected."""
    card = _minimal_card(extra_field="surprise")
    is_valid, errors = validate_card(card)
    assert not is_valid, "Card with extra field should be invalid"
    assert any("unexpected" in e.lower() for e in errors), (
        f"Expected 'unexpected fields' error, got: {errors}"
    )


# ---- AC3 --------------------------------------------------------------------
def test_missing_required_field_rejected():
    """AC3: Required fields — missing card_id is rejected."""
    card = _minimal_card()
    del card["card_id"]
    is_valid, errors = validate_card(card)
    assert not is_valid, "Card without card_id should be invalid"
    assert any("card_id" in e for e in errors), (
        f"Expected card_id error, got: {errors}"
    )


# ---- AC4 --------------------------------------------------------------------
def test_invalid_card_id_pattern_rejected():
    """AC4: card_id pattern — must be hep-YYYY-MM-DD-NNN."""
    card = _minimal_card(card_id="card-1")  # wrong format
    is_valid, errors = validate_card(card)
    assert not is_valid, "Card with bad card_id pattern should be invalid"
    assert any("pattern" in e.lower() or "card_id" in e for e in errors), (
        f"Expected pattern/card_id error, got: {errors}"
    )


# ---- AC5 --------------------------------------------------------------------
def test_oversized_card_rejected():
    """AC5: max_loc_delta hard cap — cards above 100 are rejected."""
    card = _minimal_card()
    card["output"]["max_loc_delta"] = 250  # way over cap
    is_valid, errors = validate_card(card)
    assert not is_valid, "Oversized card should be invalid"
    assert any("hard cap" in e for e in errors), (
        f"Expected hard cap error, got: {errors}"
    )


# ---- AC6 --------------------------------------------------------------------
def test_too_few_out_of_scope_rejected():
    """AC6: out_of_scope minimum — fewer than 3 entries is rejected."""
    card = _minimal_card()
    card["out_of_scope"] = ["only one rule"]  # below min of 3
    is_valid, errors = validate_card(card)
    assert not is_valid, "Card with <3 out_of_scope entries should be invalid"
    assert any("out_of_scope" in e for e in errors), (
        f"Expected out_of_scope error, got: {errors}"
    )


# ---- AC7 --------------------------------------------------------------------
def test_tautology_verify_rejected():
    """AC7: Tautological verify command — `true` is rejected."""
    card = _minimal_card()
    card["verify"]["command"] = "true"
    is_valid, errors = validate_card(card)
    assert not is_valid, "Tautological verify command should be invalid"
    assert any("tautology" in e for e in errors), (
        f"Expected tautology error, got: {errors}"
    )


# ---- AC8 --------------------------------------------------------------------
def test_dangerous_shell_rejected():
    """AC8: Dangerous shell patterns in verify command are rejected."""
    card = _minimal_card()
    card["verify"]["command"] = "echo `rm -rf /`"
    is_valid, errors = validate_card(card)
    assert not is_valid, "Verify command with shell injection should be invalid"
    assert any("dangerous" in e for e in errors), (
        f"Expected dangerous error, got: {errors}"
    )


# ---- AC9 --------------------------------------------------------------------
def test_render_worker_prompt_tight():
    """AC9: render_worker_prompt — produces a tight, deterministic output."""
    card = HephaestusBuildCard(**_minimal_card())
    prompt = render_worker_prompt(card)

    # Must contain the contract fields
    assert "TASK: hep-2026-06-21-001" in prompt
    assert "ASSIGNEE: marvin" in prompt
    assert "Add class LeadStore" in prompt
    assert "VERIFY (must exit 0):" in prompt
    assert "OUT OF SCOPE — DO NOT:" in prompt

    # Must NOT contain vague context paragraphs (drift signals)
    assert "rationale" not in prompt.lower(), (
        "Prompt contains 'rationale' — drift signal: worker should not get rationale"
    )
    assert "why we're doing this" not in prompt.lower(), (
        "Prompt contains 'why we're doing this' — drift signal"
    )

    # Length: < 2KB. If it's longer, drift has crept in.
    assert len(prompt) < 2048, f"Prompt too long ({len(prompt)} chars). Drift?"


# ---- AC10 -------------------------------------------------------------------
def test_detect_conflicts_same_output_file():
    """AC10: detect_conflicts — same output file."""
    a = HephaestusBuildCard(**_minimal_card(card_id="hep-2026-06-21-001"))
    b = HephaestusBuildCard(**_minimal_card(card_id="hep-2026-06-21-002"))
    conflicts = detect_conflicts([a, b])
    assert any("same output file" in c[2] for c in conflicts), (
        f"Expected 'same output file' conflict, got: {conflicts}"
    )


# ---- AC11 -------------------------------------------------------------------
def test_detect_conflicts_different_outputs():
    """AC11: detect_conflicts — different output files, no conflict."""
    a = HephaestusBuildCard(**_minimal_card(card_id="hep-2026-06-21-001"))
    b_dict = _minimal_card(card_id="hep-2026-06-21-002")
    b_dict["output"]["file"] = "/different/path.py"
    b = HephaestusBuildCard(**b_dict)
    conflicts = detect_conflicts([a, b])
    assert conflicts == [], (
        f"Expected no conflicts between cards with different output files, got: {conflicts}"
    )


# ---- AC12 -------------------------------------------------------------------
def test_depends_on_and_parallel_group_independent():
    """AC12: depends_on + parallel_group are independent fields."""
    card_dict = _minimal_card(
        depends_on=["hep-2026-06-21-000"],
        parallel_group="stage-2-frontend",
    )
    is_valid, errors = validate_card(card_dict)
    assert is_valid, f"Expected valid, got errors: {errors}"

    # And the rendered prompt should mention both
    card = HephaestusBuildCard(**card_dict)
    prompt = render_worker_prompt(card)
    assert "DEPENDS ON" in prompt and "hep-2026-06-21-000" in prompt
    assert "PARALLEL GROUP: stage-2-frontend" in prompt


# ---- Schema-level invariant (defensive) ------------------------------------
def test_schema_additional_properties_is_false():
    """Defensive: schema MUST have additionalProperties: False.

    This is the load-bearing rule of the contract. If a future edit
    flips it to True, every other test still passes but drift returns.
    """
    assert HEPHAESTUS_BUILD_CARD_SCHEMA.get("additionalProperties") is False, (
        "HEPHAESTUS_BUILD_CARD_SCHEMA lost its additionalProperties: False — "
        "this is the load-bearing rule. Do not change it without revisiting "
        "the spec-to-cards pipeline."
    )


def test_hard_cap_is_one_hundred():
    """Defensive: hard cap MUST be 100 LoC. Cards above this get rejected."""
    assert MAX_LOC_DELTA_HARD_CAP == 100, (
        f"MAX_LOC_DELTA_HARD_CAP is {MAX_LOC_DELTA_HARD_CAP}, expected 100"
    )
