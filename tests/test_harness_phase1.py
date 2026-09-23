"""Phase 1 acceptance tests: versioned harness store + append-only edit ledger.

These encode the plan's stated Phase 1 acceptance criteria:

  * apply -> revert restores **byte-identical** content
  * a re-applied marked block is a **logged no-op**, not a silent skip
  * `inputs_read` is mandatory (the anti-poisoning control)
  * every edit states how it improves the system (`expected_improvement`)
  * T3 classes are never autonomously editable
  * repeated reverts of a class freeze it to human-only
  * the ledger is append-only — reverts are new events, not rewrites

Everything runs against temporary store/live/ledger paths; no production
harness artifact is touched.
"""
from __future__ import annotations

import json

import pytest

from lib.ichor import edit_ledger
from lib.ichor.harness_store import HarnessStore, HarnessStoreError, sha256_bytes


@pytest.fixture()
def env(tmp_path):
    live = tmp_path / "hermes"
    (live / "profiles" / "thoth").mkdir(parents=True)
    store = HarnessStore(
        repo_dir=tmp_path / "store",
        live_root=live,
        ledger_path=tmp_path / "edit-ledger.jsonl",
    )
    return {"store": store, "live": live, "ledger": tmp_path / "edit-ledger.jsonl"}


def _ei(**over):
    base = {
        "mechanism": "the appended block instructs the agent to re-read written files, which removes the syntax errors that were recurring",
        "metric": "count of Python syntax errors per 100 code writes",
        "predicted_delta": "-30 errors per 100 writes",
        "blast_radius": "god system prompts only; no runtime path",
        "reversibility": "revert to the recorded parent revision",
    }
    base.update(over)
    return base


def _apply(env, content: bytes, **over):
    art = env["live"] / "profiles" / "thoth" / "SOUL.md"
    art.write_bytes(content)
    kwargs = dict(
        live_path=art,
        new_bytes=over.pop("new_bytes", content + b"\nAPPENDED\n"),
        author_god="thoth",
        trigger="cron",
        target_artifact_class="soul_append",
        rationale="recurring syntax errors in code writes",
        expected_improvement=_ei(),
        inputs_read=["/home/konan/.hermes/ichor/forge/god-thoth.jsonl"],
        human_approver="konan",
    )
    kwargs.update(over)
    return env["store"].apply_edit(**kwargs), art


# ── the headline guarantee: revert is byte-exact ───────────────────────────

def test_apply_then_revert_restores_byte_identical_content(env):
    original = b"# Persona\n\nBe careful.\n"
    res, art = _apply(env, original)

    assert res["no_op"] is False
    assert art.read_bytes() != original, "edit should have changed the file"

    rev = env["store"].revert(res["edit_id"], reason="unit test", automatic=True)

    assert rev["byte_identical"] is True, rev
    assert art.read_bytes() == original, "revert must restore the exact original bytes"
    assert sha256_bytes(art.read_bytes()) == res["before_sha256"]


@pytest.mark.parametrize("payload", [
    b"no trailing newline",
    b"crlf line endings\r\nsecond\r\n",
    "# unicode \u00e9\u00fc\u4e2d\u6587 \U0001f600\n".encode("utf-8"),
    b"",
])
def test_revert_is_byte_exact_for_awkward_content(env, payload):
    """A text-mode read would silently normalise some of these."""
    res, art = _apply(env, payload, new_bytes=payload + b"\nEXTRA\n")
    env["store"].revert(res["edit_id"], reason="awkward payload", automatic=True)
    assert art.read_bytes() == payload


# ── no-op must be RECORDED, never silently skipped ─────────────────────────

def test_reapplying_a_marked_block_is_a_logged_noop(env):
    marker = "## Code Quality Discipline (added by Ichor Forge)"
    art = env["live"] / "profiles" / "thoth" / "SOUL.md"
    art.write_text("# Persona\n\n" + marker + "\n\nrules...\n")

    res = env["store"].apply_edit(
        live_path=art,
        new_bytes=b"# Persona\n\n" + marker.encode() + b"\n\nrules...\n",
        author_god="thoth", trigger="cron", target_artifact_class="soul_append",
        rationale="re-apply the discipline block", expected_improvement=_ei(),
        inputs_read=["/x/forge.jsonl"], human_approver="konan",
        marker=marker,
    )

    assert res["no_op"] is True
    assert res["reason"] == "marker already present"

    # ...and it is visible in the ledger, which is the whole point. The old
    # appender skipped silently, so a no-op looked identical to a failure.
    logged = edit_ledger.noops(env["ledger"])
    assert len(logged) == 1
    assert logged[0]["reason"] == "marker already present"
    assert logged[0]["target_artifact_class"] == "soul_append"


def test_identical_content_is_also_a_recorded_noop(env):
    body = b"# Persona\n\nunchanged\n"
    res, _ = _apply(env, body, new_bytes=body)
    assert res["no_op"] is True
    assert res["reason"] == "content identical"
    assert len(edit_ledger.noops(env["ledger"])) == 1


# ── admission rules ────────────────────────────────────────────────────────

def test_inputs_read_is_mandatory(env):
    with pytest.raises(edit_ledger.EditRejected) as e:
        _apply(env, b"x\n", inputs_read=[])
    assert "inputs_read" in str(e.value)


def test_placeholder_inputs_are_rejected(env):
    with pytest.raises(edit_ledger.EditRejected) as e:
        _apply(env, b"x\n", inputs_read=["n/a"])
    assert "meaningful" in str(e.value)


def test_expected_improvement_is_mandatory(env):
    with pytest.raises(edit_ledger.EditRejected) as e:
        _apply(env, b"x\n", expected_improvement={"metric": "x"})
    assert "expected_improvement.mechanism is required" in str(e.value)


def test_mechanism_must_be_a_claim_not_a_restatement(env):
    with pytest.raises(edit_ledger.EditRejected) as e:
        _apply(env, b"x\n", expected_improvement=_ei(mechanism="adds the block"))
    assert "causal claim" in str(e.value)


def test_t2_with_a_null_approver_is_rejected(env):
    with pytest.raises(edit_ledger.EditRejected) as e:
        _apply(env, b"x\n", human_approver=None)
    assert "T2 requires human approval" in str(e.value)


def test_t3_class_is_never_autonomously_editable(env):
    with pytest.raises(edit_ledger.EditRejected) as e:
        _apply(env, b"x\n", target_artifact_class="guardrail")
    assert "T3" in str(e.value)


def test_rejected_edit_writes_nothing_to_the_store_or_live(env):
    art = env["live"] / "profiles" / "thoth" / "SOUL.md"
    art.write_bytes(b"original\n")
    before_store = env["store"].head()
    with pytest.raises(edit_ledger.EditRejected):
        _apply(env, b"original\n", new_bytes=b"CHANGED\n", inputs_read=[])
    assert art.read_bytes() == b"original\n", "a rejected edit must not touch the artifact"
    assert env["store"].head() == before_store


# ── append-only ────────────────────────────────────────────────────────────

def test_ledger_is_append_only_and_reverts_are_events(env):
    res, _ = _apply(env, b"v1\n")
    env["store"].revert(res["edit_id"], reason="because", automatic=True)

    lines = [json.loads(l) for l in env["ledger"].read_text().splitlines() if l.strip()]
    assert [l["event"] for l in lines] == ["recorded", "reverted"]

    folded = edit_ledger.load_edits(env["ledger"])
    assert len(folded) == 1
    assert folded[0]["reverted"] is True
    # the original record still says what it did — nothing was rewritten
    assert folded[0]["rationale"] == "recurring syntax errors in code writes"
    assert edit_ledger.live_edits(env["ledger"]) == []


def test_double_revert_is_refused(env):
    res, _ = _apply(env, b"v1\n")
    env["store"].revert(res["edit_id"], reason="first", automatic=True)
    with pytest.raises(HarnessStoreError):
        env["store"].revert(res["edit_id"], reason="again", automatic=True)


# ── freeze on repeated reverts ─────────────────────────────────────────────

def test_repeated_reverts_freeze_the_class(env, monkeypatch):
    monkeypatch.setattr(edit_ledger, "FREEZE_AFTER_REVERTS", 2)

    for i in range(2):
        res, _ = _apply(env, f"v{i}\n".encode())
        env["store"].revert(res["edit_id"], reason=f"regression {i}", automatic=True)

    frozen = edit_ledger.frozen_classes(env["ledger"])
    assert "soul_append" in frozen
    assert edit_ledger.is_frozen("soul_append", env["ledger"])

    # a frozen class can no longer be edited autonomously
    with pytest.raises(HarnessStoreError) as e:
        _apply(env, b"v3\n")
    assert "frozen to human-only" in str(e.value)


# ── invalidation by input provenance ───────────────────────────────────────

def test_edits_reading_a_corrupt_artifact_can_be_invalidated(env):
    poison = "/home/konan/.hermes/memory/poisoned-row.json"
    res, _ = _apply(env, b"v1\n", inputs_read=[poison, "/other.json"])

    hits = edit_ledger.edits_reading_artifact(poison, env["ledger"])
    assert [h["edit_id"] for h in hits] == [res["edit_id"]]

    reverted = env["store"].invalidate_by_input(poison, reason="input discovered corrupt")
    assert len(reverted) == 1
    assert reverted[0]["byte_identical"] is True
    assert edit_ledger.live_edits(env["ledger"]) == []


# ── promoted versions are tagged ───────────────────────────────────────────

def test_promoted_edit_is_tagged_and_resolvable(env):
    res, _ = _apply(env, b"v1\n", tag_as="soul-append-v1")
    assert res["promoted_tag"] == "soul-append-v1"
    assert env["store"].resolve("soul-append-v1") == res["version"]


def test_parent_version_is_captured_before_the_change(env):
    res, art = _apply(env, b"original\n")
    parent_bytes = env["store"].bytes_at(res["rel"], res["parent_version"])
    assert parent_bytes == b"original\n"
    assert res["version"] != res["parent_version"]

# ── symlinked targets: refuse, or record the real blast radius ─────────────

def _make_symlinked_profile(env):
    """`profiles/hermes/SOUL.md -> ../../SOUL.md`, as it is on the real system."""
    (env["live"] / "SOUL.md").write_bytes(b"# Global persona\n")
    link_dir = env["live"] / "profiles" / "hermes"
    link_dir.mkdir(parents=True, exist_ok=True)
    link = link_dir / "SOUL.md"
    link.symlink_to(env["live"] / "SOUL.md")
    return link


def test_symlinked_target_is_refused_by_default(env):
    link = _make_symlinked_profile(env)
    with pytest.raises(HarnessStoreError) as e:
        env["store"].apply_edit(
            live_path=link, new_bytes=b"# Global persona\nCHANGED\n",
            author_god="hermes", trigger="handoff", target_artifact_class="soul_append",
            rationale="edit through the profile path", expected_improvement=_ei(),
            inputs_read=["/x/forge.jsonl"], human_approver="konan",
        )
    msg = str(e.value)
    assert "symlink" in msg
    assert "hermes" in msg, "the refusal must name the profiles it would change"
    assert (env["live"] / "SOUL.md").read_bytes() == b"# Global persona\n", "nothing written"


def test_symlinked_target_records_its_real_scope_when_accepted(env):
    link = _make_symlinked_profile(env)
    res = env["store"].apply_edit(
        live_path=link, new_bytes=b"# Global persona\nCHANGED\n",
        author_god="hermes", trigger="handoff", target_artifact_class="soul_append",
        rationale="edit through the profile path", expected_improvement=_ei(),
        inputs_read=["/x/forge.jsonl"], human_approver="konan",
        allow_symlink=True,
    )
    assert res["no_op"] is False

    rec = edit_ledger.load_edits(env["ledger"])[0]
    # the diff understated nothing: the ledger names the resolution and the scope
    assert rec["resolved_target"].endswith("SOUL.md")
    assert rec["shared_with"] == ["hermes"]
    assert rec["symlink_accepted"] is True
    # ...and the store keyed on the RESOLVED path, not the profile path
    assert res["rel"] == "hermes/SOUL.md", res["rel"]

    # reverting through the global path returns the shared file's bytes
    env["store"].revert(res["edit_id"], reason="undo", automatic=True)
    assert (env["live"] / "SOUL.md").read_bytes() == b"# Global persona\n"


def test_editing_via_symlink_and_via_target_are_the_same_artifact(env):
    link = _make_symlinked_profile(env)
    global_path = env["live"] / "SOUL.md"
    assert env["store"].rel_for(link) == env["store"].rel_for(global_path)


def test_extra_cannot_shadow_core_ledger_fields(env):
    with pytest.raises(edit_ledger.EditRejected) as e:
        edit_ledger.build_record(
            author_god="hermes", trigger="handoff", target_artifact_class="soul_append",
            target_path="/x/SOUL.md", inputs_read=["/x/forge.jsonl"],
            rationale="real reason", expected_improvement=_ei(),
            parent_version="abc", human_approver="konan",
            extra={"rationale": "rewritten after the fact"},
        )
    assert "cannot overwrite core fields" in str(e.value)


def test_extra_is_preserved_and_validated(env):
    rec = edit_ledger.build_record(
        author_god="hermes", trigger="handoff", target_artifact_class="soul_append",
        target_path="/x/SOUL.md", inputs_read=["/x/forge.jsonl"],
        rationale="real reason", expected_improvement=_ei(), parent_version="abc",
        human_approver="konan",
        extra={"resolved_target": "/x/real/SOUL.md", "shared_with": ["hermes"]},
    )
    assert rec["resolved_target"] == "/x/real/SOUL.md"
    assert rec["shared_with"] == ["hermes"]


def test_apply_through_a_symlink_does_not_destroy_the_symlink(env):
    """os.replace() on a symlink path replaces the LINK, not the target.

    If that regresses, editing profiles/hermes/SOUL.md silently detaches the
    profile from the shared global file and the edit never reaches the artifact
    the store keyed it against.
    """
    link = _make_symlinked_profile(env)
    global_path = env["live"] / "SOUL.md"

    env["store"].apply_edit(
        live_path=link, new_bytes=b"# Global persona\nCHANGED\n",
        author_god="hermes", trigger="handoff", target_artifact_class="soul_append",
        rationale="edit through the profile path", expected_improvement=_ei(),
        inputs_read=["/x/forge.jsonl"], human_approver="konan",
        allow_symlink=True,
    )

    assert link.is_symlink(), "the symlink must survive the edit"
    assert link.resolve() == global_path.resolve()
    assert global_path.read_bytes() == b"# Global persona\nCHANGED\n", (
        "the SHARED artifact must carry the change, not a private copy"
    )
    assert link.read_bytes() == global_path.read_bytes()
