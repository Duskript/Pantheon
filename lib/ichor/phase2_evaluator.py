"""Phase 2 evaluator — precision as the primary metric, with an explicit denominator.

WHY PRECISION AND NOT YIELD
---------------------------
Yield (items produced per event) always rewards producing MORE. An extractor that
emits file paths, licence strings and truncated sentence fragments scores HIGHER
than one that emits nothing, so the metric pays for hallucination: the number
improves while the output gets worse. Measured on the live corpus, 15.3% of 23,859
entities are sentence-fragment shaped and the recent tail includes `LICENSE.txt`,
`AL2.0` and `META-INF`. Yield cannot see any of that.

Precision — of the items produced, what fraction are real — cannot be raised by
emitting more, because junk counts against it. That is the counterweight.

THE PRECONDITION, STATED AS A PRECONDITION
------------------------------------------
Precision needs labels from a source INDEPENDENT of the extractor. It cannot be
derived by inspecting the producer's own output: an evaluator sharing the
producer's model family agrees with it and measures self-consistency, not
correctness — a student marking their own exam. Independence is therefore a
required argument here, not an implementation detail, and `evaluate()` refuses to
report a rate without it.

  extractor : deepseek-v4.1-flash
  judge     : minimax-m3  (MiniMax — a different family)
  calibration: v2 definition, 19/20 = 95% agreement with human adjudication

FRESHNESS IS ENFORCED, NOT CHECKED
----------------------------------
A metric that cannot state when it was last written must not be reported. The
vault's `max_age` is declared in `MAX_AGES` and a stale vault raises rather than
returning a number — a report that prints a stale figure IS the original bug.

NO DEFAULTED DENOMINATOR
------------------------
A missing denominator is `None`, never `1`. A fabricated denominator makes every
un-instrumented row a fake rate.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from lib.ichor.freshness import stamp_for_file
from lib.pantheon_path import account_home

#: Full paths — an unqualified filename is ambiguous on a host holding several
#: files with that name, and ambiguity turns a wrong path into a plausible reading.
VAULT_DIR = account_home() / ".hermes" / "ichor" / "ood-vault"
VAULT_ITEMS = VAULT_DIR / "items.jsonl"
VAULT_MANIFEST = VAULT_DIR / "manifest.json"

#: Declared maximum age of the label set, in seconds. Past this the labels are not
#: a measurement and the evaluator refuses rather than reporting.
MAX_AGE_LABELS = 90 * 24 * 3600  # 90 days — labels are a frozen asset, not a stream


class EvaluatorError(RuntimeError):
    """Raised when a rate cannot honestly be computed."""


@dataclass
class MetricRecord:
    """Structured fields, with the denominator as a COLUMN.

    An outcome written as prose parses but cannot be normalized, and the input size
    that produced it is gone. A numerator you can read but cannot divide is not a
    metric.
    """
    metric: str
    numerator: Optional[float]
    denominator: Optional[int]
    value: Optional[float]
    rate_reliable: bool
    producer: str
    label_source: str
    label_definition_version: str
    label_independence: str
    label_age_s: Optional[float]
    excluded_unparsed: int
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _load_vault(vault_dir: Path = VAULT_DIR) -> tuple[List[dict], dict]:
    items_path = vault_dir / "items.jsonl"
    manifest_path = vault_dir / "manifest.json"
    if not manifest_path.exists():
        raise EvaluatorError(f"no vault manifest at {manifest_path} — cannot cite label provenance")
    manifest = json.loads(manifest_path.read_text())

    # Freshness is ENFORCED. A stale label set is not a measurement.
    stamp = stamp_for_file(items_path, "ood_labels", max_age_s=MAX_AGE_LABELS)
    if not stamp.is_fresh:
        raise EvaluatorError(
            f"label set is stale: {stamp.human_age()} old, max {MAX_AGE_LABELS / 86400:.0f}d "
            f"— refusing to report a rate from it ({items_path})"
        )

    # The hash must match, or the labels are not the ones the judge produced.
    actual = hashlib.sha256(items_path.read_bytes()).hexdigest()
    if actual != manifest.get("content_sha256"):
        raise EvaluatorError(
            f"vault contents changed after freezing: manifest "
            f"{str(manifest.get('content_sha256'))[:12]} vs actual {actual[:12]} — "
            "the labels are no longer the ones the judge saw"
        )
    items = [json.loads(l) for l in items_path.read_text().splitlines()]
    return items, manifest


def _results_path(vault_dir: Path, tag: str = "v2") -> Path:
    p = vault_dir / f"judge_results_{tag}.jsonl"
    return p if p.exists() else vault_dir / "judge_results.jsonl"


def evaluate(
    *,
    producer: str,
    label_independence: str,
    vault_dir: Path = VAULT_DIR,
    tag: str = "v2",
    by_writer: bool = True,
) -> Dict[str, Any]:
    """Compute precision over the frozen labels, with the denominator explicit.

    `producer` names the writer whose output is measured, so the metric is
    attributable. `label_independence` must state why the label source does not
    share the extractor's model family — an empty string is refused, because a
    metric whose independence is unstated cannot be distinguished from
    self-agreement.
    """
    if not label_independence or len(label_independence) < 20:
        raise EvaluatorError(
            "label_independence must state the relationship between the label source "
            "and the extractor; an unstated independence is indistinguishable from "
            "self-agreement"
        )

    items, manifest = _load_vault(vault_dir)
    results_path = _results_path(vault_dir, tag)
    if not results_path.exists():
        raise EvaluatorError(f"no judge results at {results_path}")
    results = [json.loads(l) for l in results_path.read_text().splitlines()]

    by_id = {r["item_id"]: r for r in results}
    verdicts = {"REAL": 0, "NOISE": 0, "UNPARSED": 0}
    per_writer: Dict[str, Dict[str, int]] = {}
    for it in items:
        r = by_id.get(it["item_id"])
        v = (r or {}).get("judge_verdict", "UNPARSED")
        verdicts[v] = verdicts.get(v, 0) + 1
        # Split by writer before computing a rate: a table fed by more than one
        # producer measures a blend of them.
        w = it.get("writer") or it.get("bucket") or "unknown"
        per_writer.setdefault(w, {"REAL": 0, "NOISE": 0, "UNPARSED": 0})[v] = \
            per_writer.setdefault(w, {"REAL": 0, "NOISE": 0, "UNPARSED": 0}).get(v, 0) + 1

    judged = verdicts["REAL"] + verdicts["NOISE"]
    stamp = stamp_for_file(VAULT_ITEMS, "ood_labels", max_age_s=MAX_AGE_LABELS)

    # A missing denominator is None, never a defaulted 1.
    if judged == 0:
        precision = None
        reliable = False
        notes = ["no judged items — rate unavailable (a fabricated denominator makes "
                 "every un-instrumented row a fake rate)"]
    else:
        precision = verdicts["REAL"] / judged
        reliable = verdicts["UNPARSED"] / max(1, len(items)) < 0.10
        notes = []
        if not reliable:
            notes.append(
                f"{verdicts['UNPARSED']} of {len(items)} items UNPARSED — above the 10% "
                "threshold, so the rate is not reliable"
            )

    rec = MetricRecord(
        metric="l2_extraction_precision",
        numerator=verdicts["REAL"],
        denominator=judged,
        value=round(precision, 4) if precision is not None else None,
        rate_reliable=reliable,
        producer=producer,
        label_source=str(results_path),
        label_definition_version=manifest.get("label_definition_version", "unknown"),
        label_independence=label_independence,
        label_age_s=round(stamp.age_s, 1),
        excluded_unparsed=verdicts["UNPARSED"],
        notes=notes + [
            "PRIMARY metric is precision: junk counts against it, so it cannot be "
            "raised by emitting more. Yield is retained only as a gaming detector.",
            f"vault content_sha256 {manifest.get('content_sha256', '')[:12]}",
            f"judge {manifest.get('judge_model', '?')}; human agreement "
            f"{manifest.get('calibration', {}).get('v2_vs_human', {}).get('agreement', '?')}",
        ],
    )
    out: Dict[str, Any] = {"precision": rec.as_dict(), "verdicts": verdicts,
                           "n_items": len(items)}
    if by_writer:
        out["by_writer"] = {}
        for w, c in sorted(per_writer.items()):
            d = c["REAL"] + c["NOISE"]
            out["by_writer"][w] = {
                "numerator": c["REAL"], "denominator": d,
                "precision": round(c["REAL"] / d, 4) if d else None,
                "rate_reliable": d > 0,
            }
    return out


def yield_secondary(db_path: Path, *, writer: Optional[str] = None) -> Dict[str, Any]:
    """Yield, kept ONLY as a detector that the primary metric is being gamed.

    If yield rises while precision falls, the extractor has learned to satisfy the
    counter by emitting more — which is exactly the behaviour precision exists to
    catch. Yield must never be the objective.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        q = ("SELECT COALESCE(SUM(events_in_batch), 0), COUNT(*) FROM extraction_log "
             "WHERE events_in_batch IS NOT NULL")
        params: tuple = ()
        if writer:
            q += " AND writer = ?"
            params = (writer,)
        events, batches = conn.execute(q, params).fetchone()
    finally:
        conn.close()
    return {
        "metric": "l2_extraction_yield_denominator",
        "events_observed": events,
        "batches": batches,
        # A missing denominator is None, never a defaulted 1.
        "events_per_batch": round(events / batches, 3) if batches else None,
        "rate_reliable": batches > 0,
        "role": "SECONDARY — gaming detector only, never the objective",
        "writer_filter": writer,
    }
