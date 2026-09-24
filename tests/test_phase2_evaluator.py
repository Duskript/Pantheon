"""The Phase 2 evaluator must refuse to report a rate it cannot honestly compute.

Every test here pins a rule from `metric-instrumentation-integrity`, because each
one is a failure mode this session actually hit:

  * a rate needs a DENOMINATOR, and a missing one is `None`, never a defaulted 1
  * precision needs labels from a source INDEPENDENT of the extractor — an unstated
    independence is indistinguishable from self-agreement
  * a metric that cannot state when it was last written must NOT be reported
  * the label set must be the one the judge actually saw (hash match)
  * a count-based metric pays for emission, so yield must never be the objective

FALSIFICATION
-------------
`test_refuses_when_the_denominator_is_missing` fails if `judged == 0` is allowed to
fall through to `precision = 0.0` — a fabricated denominator makes every
un-instrumented row a fake rate.
`test_refuses_a_changed_label_set` fails if the hash comparison is removed, which is
how a silently edited vault becomes an unfalsifiable metric.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from lib.ichor.phase2_evaluator import (  # noqa: E402
    EvaluatorError, evaluate, yield_secondary,
)

GOOD_INDEPENDENCE = (
    "judge minimax-m3 (MiniMax) vs extractor deepseek-v4.1-flash: a different model "
    "family, so verdicts are not self-agreement."
)


def _make_vault(tmp_path: Path, verdicts: list[str], *, mtime_days_ago: float = 0.0,
                corrupt_hash: bool = False) -> Path:
    """A minimal vault with a manifest, a hash, and judge results."""
    v = tmp_path / "ood-vault"
    v.mkdir(parents=True, exist_ok=True)
    items = [{"item_id": f"ent:{i}", "text": f"item {i}", "bucket": "clean",
              "kind": "entity", "source_excerpt": ""} for i in range(len(verdicts))]
    body = "\n".join(json.dumps(i, sort_keys=True) for i in items) + "\n"
    (v / "items.jsonl").write_text(body)
    digest = hashlib.sha256(body.encode()).hexdigest()
    (v / "manifest.json").write_text(json.dumps({
        "content_sha256": "0" * 64 if corrupt_hash else digest,
        "label_definition_version": "v2",
        "judge_model": "minimax-m3",
        "calibration": {"v2_vs_human": {"agreement": 0.95}},
    }))
    (v / "judge_results_v2.jsonl").write_text("\n".join(
        json.dumps({"item_id": f"ent:{i}", "judge_verdict": verdict,
                    "judge_reason": "test"})
        for i, verdict in enumerate(verdicts)) + "\n")
    if mtime_days_ago:
        import os
        import time
        when = time.time() - mtime_days_ago * 86400
        os.utime(v / "items.jsonl", (when, when))
    return v


def test_computes_precision_with_an_explicit_denominator(tmp_path):
    v = _make_vault(tmp_path, ["REAL"] * 6 + ["NOISE"] * 4)
    r = evaluate(producer="test", label_independence=GOOD_INDEPENDENCE, vault_dir=v)
    p = r["precision"]
    assert p["numerator"] == 6
    assert p["denominator"] == 10
    assert p["value"] == pytest.approx(0.6)
    assert p["rate_reliable"] is True


def test_refuses_when_the_denominator_is_missing(tmp_path):
    """A missing denominator is None, never 1. No judged items => no rate."""
    v = _make_vault(tmp_path, ["UNPARSED"] * 5)
    r = evaluate(producer="test", label_independence=GOOD_INDEPENDENCE, vault_dir=v)
    p = r["precision"]
    assert p["denominator"] == 0
    assert p["value"] is None, "a rate was fabricated from an empty denominator"
    assert p["rate_reliable"] is False
    assert any("unavailable" in n for n in p["notes"])


def test_refuses_an_unstated_label_independence(tmp_path):
    """Unstated independence is indistinguishable from self-agreement."""
    v = _make_vault(tmp_path, ["REAL"] * 4)
    for bad in ("", "same model", "independent"):
        with pytest.raises(EvaluatorError):
            evaluate(producer="test", label_independence=bad, vault_dir=v)


def test_refuses_a_stale_label_set(tmp_path):
    """Detection is not a guard. A stale label set must RAISE, not warn."""
    v = _make_vault(tmp_path, ["REAL"] * 4, mtime_days_ago=400)
    with pytest.raises(EvaluatorError, match="stale"):
        evaluate(producer="test", label_independence=GOOD_INDEPENDENCE, vault_dir=v)


def test_refuses_a_changed_label_set(tmp_path):
    """If the hash does not match, the labels are not the ones the judge saw."""
    v = _make_vault(tmp_path, ["REAL"] * 4, corrupt_hash=True)
    with pytest.raises(EvaluatorError, match="changed after freezing"):
        evaluate(producer="test", label_independence=GOOD_INDEPENDENCE, vault_dir=v)


def test_unparsed_above_threshold_marks_the_rate_unreliable(tmp_path):
    """A rate computed mostly over unparsed items is not a measurement."""
    v = _make_vault(tmp_path, ["REAL"] * 5 + ["UNPARSED"] * 5)
    r = evaluate(producer="test", label_independence=GOOD_INDEPENDENCE, vault_dir=v)
    assert r["precision"]["rate_reliable"] is False
    assert r["precision"]["excluded_unparsed"] == 5


def test_every_record_carries_its_provenance(tmp_path):
    """A number without its source, definition and age cannot be audited."""
    v = _make_vault(tmp_path, ["REAL"] * 3)
    p = evaluate(producer="p", label_independence=GOOD_INDEPENDENCE, vault_dir=v)["precision"]
    assert p["producer"] == "p"
    assert p["label_definition_version"] == "v2"
    assert p["label_independence"]
    assert p["label_age_s"] is not None
    assert any("content_sha256" in n for n in p["notes"])


def test_yield_is_labelled_secondary_not_objective():
    """Yield pays for emission — it must never be presented as the goal."""
    import inspect
    src = inspect.getsource(yield_secondary)
    assert "SECONDARY" in src
    assert "never the objective" in src
