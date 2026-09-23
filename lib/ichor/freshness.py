"""Freshness assertions for reported metrics — the class-4 guard.

Why this exists
---------------
Four failure classes have been catalogued in this codebase, and the fourth is the
worst:

  1. green-but-wrong      a clean exit code, no work done
  2. silent no-op         nothing written, nothing logged
  3. never wired          no number at all
  4. stale-but-plausible  A NUMBER THAT IS NOT OBVIOUSLY WRONG

Classes 1-3 each present something detectably wrong or absent. Class 4 presents a
confident figure that stopped being true weeks ago and keeps being printed, and
**only the timestamp gives it away** — a timestamp that reports usually do not
print.

Two confirmed instances on this host:

  * the Dojo's ``metrics.json`` reported ``overall_success_rate: 90.0`` for 65
    days after its writer stopped, from three writes inside 166 seconds.
  * the Ichor Forge improvement report was 103 days stale when it surfaced.

The guard is not more instrumentation. It is an assertion: **every reported
metric declares a maximum age and FAILS HARD past it.** A warning is not enough —
a warning is a line in a log that nobody reads, which is how a metric stays stale
for 65 days.

Design note: this fails hard on purpose. Reporting a stale number as if current is
worse than reporting nothing, because it is indistinguishable from a live reading
and will be acted on.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

__all__ = ["StaleMetric", "MetricStamp", "stamp_for_file", "check_all", "MAX_AGES"]

#: Default maximum ages, in seconds, by metric family. Declared centrally so a
#: metric cannot quietly pick its own lenient bound. Override per call only with
#: a reason.
MAX_AGES: Dict[str, int] = {
    "dojo_metrics": 48 * 3600,        # hourly writer -> 2 days is already generous
    "forge_improvement_report": 48 * 3600,
    "l2_extraction_yield": 6 * 3600,  # batches land continuously
    "mistake_ledger": 30 * 24 * 3600, # event-driven, not scheduled
    "harness_edit_ledger": 30 * 24 * 3600,
}


class StaleMetric(RuntimeError):
    """Raised when a metric is older than its declared maximum age."""


@dataclass
class MetricStamp:
    """A metric's name, when it was last written, and how old it may be."""

    name: str
    written_at: float                      # epoch seconds
    max_age_s: int
    source: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def age_s(self) -> float:
        return max(0.0, time.time() - self.written_at)

    @property
    def is_fresh(self) -> bool:
        return self.age_s <= self.max_age_s

    def human_age(self) -> str:
        a = self.age_s
        for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
            if a >= size:
                return f"{a / size:.1f}{unit}"
        return f"{a:.0f}s"

    def assert_fresh(self) -> "MetricStamp":
        """Raise `StaleMetric` if this reading is too old. Returns self otherwise."""
        if not self.is_fresh:
            raise StaleMetric(
                f"{self.name} is {self.human_age()} old (max {self.max_age_s / 3600:.0f}h)"
                + (f" — source {self.source}" if self.source else "")
                + ". Refusing to report a stale value as current: a stale number is "
                  "indistinguishable from a live one and will be acted on."
            )
        return self

    def as_dict(self) -> Dict[str, Any]:
        d = {
            "name": self.name,
            "age": self.human_age(),
            "age_s": round(self.age_s, 1),
            "max_age_s": self.max_age_s,
            "fresh": self.is_fresh,
        }
        if self.source:
            d["source"] = self.source
        d.update(self.extra)
        return d


def stamp_for_file(
    path: Path | str,
    name: str,
    max_age_s: Optional[int] = None,
    *,
    written_at: Optional[float] = None,
) -> MetricStamp:
    """Build a stamp from a file's mtime (or an explicit `written_at`).

    A missing file is NOT "fresh" and NOT "stale" — it is absent, which is
    class 3. Callers get `written_at = 0`, i.e. maximally stale, because
    reporting nothing is the correct outcome and raising is the correct signal.
    """
    p = Path(path)
    if written_at is None:
        written_at = p.stat().st_mtime if p.exists() else 0.0
    if max_age_s is None:
        max_age_s = MAX_AGES.get(name, 24 * 3600)
    return MetricStamp(name=name, written_at=written_at, max_age_s=max_age_s, source=str(p))


def check_all(stamps: Iterable[MetricStamp], *, fail_fast: bool = True) -> List[MetricStamp]:
    """Assert every stamp is fresh. Returns the fresh ones, or raises.

    `fail_fast=False` collects all stale metrics and raises once with the full
    list — useful for a report that must state everything wrong at once.
    """
    stamps = list(stamps)
    if fail_fast:
        for s in stamps:
            s.assert_fresh()
        return stamps
    stale = [s for s in stamps if not s.is_fresh]
    if stale:
        detail = "; ".join(f"{s.name} {s.human_age()} > {s.max_age_s / 3600:.0f}h" for s in stale)
        raise StaleMetric(f"{len(stale)} stale metric(s): {detail}")
    return stamps
