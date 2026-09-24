"""The OOD label vault must be WRITE-ONLY to the proposal path.

WHY THIS IS A TEST AND NOT A CONVENTION
---------------------------------------
The Phase 2 evaluator grades the extractor on labels drawn from this vault. If the
thing that PROPOSES changes can also READ the labels, it can optimise against them
directly — and a held-out set that the proposer has seen is a training set. The
metric would keep improving while the underlying extraction quality did not move,
which is the same failure shape as the yield metric this work exists to replace.

So the isolation is enforced mechanically here, not by a comment asking people to
be careful.

WHAT IS AND IS NOT FORBIDDEN
----------------------------
FORBIDDEN: the proposal path (`lib/clawforge/*`, the exporters, the recommendation
applier, the forge sweep, the weight tuner) reading the vault, at any point, for any
reason. Those modules propose; they must not see the answers.

ALLOWED: the judge runner and the vault builder (they produce the labels), and a
human-facing review script that renders the checklist. Those are the labelling side.

FALSIFICATION
-------------
Add `open(Path.home()/".hermes"/"ichor"/"ood-vault"/"items.jsonl")` to
`lib/clawforge/recommendation_applier.py` and this test fails naming that file.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
VAULT = Path.home() / ".hermes" / "ichor" / "ood-vault"

# Anything that proposes, applies, tunes, or sweeps. These must never read the vault.
PROPOSAL_GLOBS = [
    "lib/clawforge/*.py",
    "lib/ichor_forge.py",
    "lib/forge_sweep.py",
    "lib/ichor/entities/l2_llm.py",
    "lib/ichor_hybrid.py",
]

# The vault's identifying strings — a read of it will name one of these.
VAULT_MARKERS = re.compile(
    r"ood[-_]vault|ood-vault|ood_label|ood-label|items\.jsonl|judge_results|"
    r"judge_summary|ood_vault_build|ood_judge_run",
    re.I,
)

# Files legitimately on the labelling side.
LABELLING_SIDE = {"ood_vault_build.py", "ood_judge_run.py", "ood_review_render.py"}


def _proposal_files() -> list[Path]:
    out: list[Path] = []
    for g in PROPOSAL_GLOBS:
        out.extend(p for p in REPO.glob(g) if p.is_file())
    return sorted(set(out))


def test_proposal_path_never_references_the_vault():
    """The load-bearing check: no proposing module may name the vault."""
    offenders = []
    for p in _proposal_files():
        txt = p.read_text(errors="ignore")
        for n, line in enumerate(txt.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue  # a comment explaining the rule is not a violation
            if VAULT_MARKERS.search(line):
                offenders.append(f"{p.relative_to(REPO)}:{n}: {line.strip()[:90]}")
    assert not offenders, (
        "the proposal path references the OOD vault — a proposer that can read the "
        "labels converts a held-out set into a training set:\n  " + "\n  ".join(offenders)
    )


def test_the_guarded_set_is_not_empty():
    """A guard over zero files passes vacuously — the failure mode this repo keeps hitting."""
    files = _proposal_files()
    assert len(files) >= 4, f"only {len(files)} proposal files matched; the globs are stale"
    names = {p.name for p in files}
    assert "recommendation_applier.py" in names
    assert "ichor_forge.py" in names


def test_the_labelling_side_is_allowed_to_read_it():
    """The rule must not be so broad that it forbids producing the labels."""
    assert (REPO / "scripts" / "ood_vault_build.py").exists()
    assert (REPO / "scripts" / "ood_judge_run.py").exists()
    for name in ("ood_vault_build.py", "ood_judge_run.py"):
        assert name in LABELLING_SIDE


def test_vault_manifest_declares_write_only():
    """If the vault exists, its manifest must say it is write-only and carry a hash."""
    mf = VAULT / "manifest.json"
    if not mf.exists():
        pytest.skip("vault not built yet")
    import json
    m = json.loads(mf.read_text())
    assert m.get("write_only") is True
    assert m.get("content_sha256"), "the vault must be content-hashed so edits are detectable"
    assert m.get("judge_model"), "the judge model must be recorded for reproducibility"


def test_vault_hash_matches_its_contents():
    """A hash that does not match its file is a hash that detects nothing."""
    import hashlib
    import json
    items = VAULT / "items.jsonl"
    mf = VAULT / "manifest.json"
    if not (items.exists() and mf.exists()):
        pytest.skip("vault not built yet")
    m = json.loads(mf.read_text())
    actual = hashlib.sha256(items.read_bytes()).hexdigest()
    assert actual == m["content_sha256"], (
        f"vault contents changed after freezing: manifest {m['content_sha256'][:12]} "
        f"vs actual {actual[:12]} — the labels are no longer the ones the judge saw"
    )
