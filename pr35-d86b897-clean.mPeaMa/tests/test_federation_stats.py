"""Tests for E2.4 Clawforge Federation Stats daemon.

The federation-stats daemon (relay-7, run via systemd timer) reads the
3 source registries + pattern-effectiveness.json + PROFILES.json and
writes a privacy-first INDEX.json to /var/www/clawforge/federation/.

Covers:
  - Default compute: with synthetic 4-instance data, produces correct
    per-instance/per-source/per-type aggregates
  - Privacy contract: strip patch, pattern, trigger, source_ref,
    submitted_at, and other content fields
  - Privacy: keep only numeric effectiveness metrics and type/category
  - Privacy: never expose the actual code/config being shared
  - Privacy: instance_id (12-hex) and display_name from PROFILES.json
    are allowed (so an instance can identify their own row)
  - Pattern quality leaderboard: sorted by promoted count desc
  - Cross-instance benchmarks: numeric averages, no raw content
  - Output schema: required top-level keys (schema_version, updated_at,
    totals, by_source, cross_instance_benchmarks, patterns,
    instance_health, pattern_quality_leaderboard, _privacy)
  - Backwards compat: empty registries → empty but valid output
  - Profiles missing: instance display_name falls back to instance_id
  - Malformed registry: doesn't crash, treats as empty
  - Atomic write: writes via temp file + rename
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "clawforge-federation-stats.py"


def _load_module():
    """Import the federation-stats script as a module under a stable name."""
    spec = importlib.util.spec_from_file_location(
        "clawforge_federation_stats", str(SCRIPT_PATH)
    )
    if spec is None:
        raise ImportError(f"could not load spec for {SCRIPT_PATH}")
    mod = importlib.util.module_from_spec(spec)
    loader = spec.loader
    if loader is None:
        raise ImportError(f"spec has no loader for {SCRIPT_PATH}")
    loader.exec_module(mod)
    return mod


# Load once at import time
fed = _load_module()


# ---------------------------------------------------------------------------
# Fixtures: synthetic 4-instance federation in a temp dir
# ---------------------------------------------------------------------------


def _build_synthetic_federation(td: str) -> Path:
    """Build a synthetic federation in temp dir `td/var/www/clawforge/...`.

    Returns the registry_dir path.
    """
    rd = Path(td) / "var" / "www" / "clawforge"
    for sub in ("memory-patterns", "forge-adjustments", "dojo-learnings",
                "pattern-effectiveness", "profiles"):
        (rd / sub).mkdir(parents=True, exist_ok=True)

    # 3 instances on memory, each with a synonym_expansion pattern
    mp = []
    for inst in ("aaaa1111aaaa", "bbbb2222bbbb", "cccc3333cccc"):
        mp.append({
            "instance_id": inst,
            "submitted_at": "2026-06-11T00:00:00Z",
            "patterns": [{
                "type": "synonym_expansion",
                "trigger": f"secret-trigger-{inst}",
                "patch": {"replace": f"SECRET-PATCH-{inst}"},
                "effectiveness": {
                    "improvement_pct": 15.0,
                    "false_positive_pct": 2.0,
                },
            }],
        })
    (rd / "memory-patterns" / "INDEX.json").write_text(json.dumps(mp))

    # 2 instances on forge
    fa = []
    for inst in ("aaaa1111aaaa", "dddd4444dddd"):
        fa.append({
            "instance_id": inst,
            "submitted_at": "2026-06-11T01:00:00Z",
            "adjustments": [{
                "type": "gate_health",
                "trigger": f"secret-forge-{inst}",
                "patch": {"gate": f"SECRET-FORGE-{inst}"},
                "effectiveness": {"improvement_pct": 20.0},
            }],
        })
    (rd / "forge-adjustments" / "INDEX.json").write_text(json.dumps(fa))

    # 1 instance on dojo (no improvements)
    (rd / "dojo-learnings" / "INDEX.json").write_text(json.dumps([{
        "instance_id": "bbbb2222bbbb",
        "submitted_at": "2026-06-11T02:00:00Z",
        "learnings": [{
            "type": "feedback_loop",
            "trigger": "secret-dojo-1",
            "patch": {"feedback": "SECRET-DOJO-1"},
        }],
    }]))

    # pattern-effectiveness: 1 promoted (3 instances tested) and 1 candidate
    (rd / "pattern-effectiveness" / "INDEX.json").write_text(json.dumps({
        "schema_version": 1,
        "updated_at": "2026-06-11T05:00:00Z",
        "total_patterns": 2,
        "promoted_count": 1,
        "candidate_count": 1,
        "unvalidated_count": 0,
        "patterns": [
            {
                "pattern_id": "pat_promoted_0001",
                "type": "synonym_expansion",
                "status": "promoted",
                "instances_validated": 3,
                "instances_confirmed": 3,
                "instances_rejected": 0,
                "instances_tested_list": ["aaaa1111aaaa", "bbbb2222bbbb", "cccc3333cccc"],
                "avg_improvement_pct": 15.0,
                "avg_false_positive_pct": 2.0,
                "source_systems": ["memory"],
            },
            {
                "pattern_id": "pat_candidate_0001",
                "type": "gate_health",
                "status": "candidate",
                "instances_validated": 1,
                "instances_confirmed": 1,
                "instances_rejected": 0,
                "instances_tested_list": ["dddd4444dddd"],
                "avg_improvement_pct": 20.0,
                "avg_false_positive_pct": None,
                "source_systems": ["forge"],
            },
        ],
    }))

    # profiles with display names for 2 of the 4 instances
    (rd / "profiles" / "PROFILES.json").write_text(json.dumps({
        "updated_at": "2026-06-11T05:00:00Z",
        "instances": {
            "aaaa1111aaaa": {
                "display_name": "Instance Alpha",
                "last_seen": "2026-06-11T05:00:00Z",
            },
            "bbbb2222bbbb": {
                "display_name": "Instance Beta",
                "last_seen": "2026-06-11T05:00:00Z",
            },
        },
    }))

    return rd


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestComputeBasics(unittest.TestCase):
    """Default behavior with synthetic 4-instance data."""

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.td, ignore_errors=True))
        self.rd = _build_synthetic_federation(self.td)

    def _compute(self):
        profiles = fed._read_profiles.__wrapped__(fed) if hasattr(fed._read_profiles, "__wrapped__") else None
        # Use direct call to compute_stats with our profiles dict
        with mock.patch.object(fed, "REGISTRY_DIR", type(fed.REGISTRY_DIR)(str(self.rd))):
            return fed.compute_stats(fed._read_profiles())

    def test_totals(self):
        """Top-level totals reflect the synthetic dataset."""
        payload = self._compute()
        t = payload["totals"]
        self.assertEqual(t["instances"], 4)
        self.assertEqual(t["submissions"], 6)        # 3 mem + 2 forge + 1 dojo
        self.assertEqual(t["patterns_promoted"], 1)
        self.assertEqual(t["patterns_candidate"], 1)
        self.assertEqual(t["patterns_unvalidated"], 0)

    def test_by_source_counts(self):
        """Per-source submission counts match the synthetic dataset."""
        payload = self._compute()
        bs = payload["by_source"]
        self.assertEqual(bs["memory"]["submitted"], 3)
        self.assertEqual(bs["forge"]["submitted"], 2)
        self.assertEqual(bs["dojo"]["submitted"], 1)

    def test_by_source_averages(self):
        """Per-source averages reflect the synthetic data."""
        payload = self._compute()
        bs = payload["by_source"]
        # Memory: all 3 submissions have imp=15.0, fpr=2.0
        self.assertEqual(bs["memory"]["avg_improvement_pct"], 15.0)
        self.assertEqual(bs["memory"]["avg_false_positive_pct"], 2.0)
        # Forge: 2 submissions with imp=20.0, no fpr
        self.assertEqual(bs["forge"]["avg_improvement_pct"], 20.0)
        self.assertIsNone(bs["forge"]["avg_false_positive_pct"])
        # Dojo: 1 submission, no effectiveness metrics
        self.assertIsNone(bs["dojo"]["avg_improvement_pct"])
        self.assertIsNone(bs["dojo"]["avg_false_positive_pct"])

    def test_by_source_by_type(self):
        """Per-source.by_type counts each pattern type."""
        payload = self._compute()
        bs = payload["by_source"]
        self.assertEqual(bs["memory"]["by_type"]["synonym_expansion"], 3)
        self.assertEqual(bs["forge"]["by_type"]["gate_health"], 2)
        self.assertEqual(bs["dojo"]["by_type"]["feedback_loop"], 1)

    def test_cross_instance_benchmarks(self):
        """Per-type aggregates across all instances."""
        payload = self._compute()
        cib = {x["type"]: x for x in payload["cross_instance_benchmarks"]}
        self.assertEqual(cib["synonym_expansion"]["total_submissions"], 3)
        self.assertEqual(cib["synonym_expansion"]["avg_improvement_pct"], 15.0)
        self.assertEqual(cib["gate_health"]["total_submissions"], 2)
        self.assertEqual(cib["feedback_loop"]["total_submissions"], 1)
        # Sorted by total_submissions desc
        totals = [x["total_submissions"] for x in payload["cross_instance_benchmarks"]]
        self.assertEqual(totals, sorted(totals, reverse=True))

    def test_patterns_list(self):
        """Pattern-level aggregates from pattern-effectiveness.json."""
        payload = self._compute()
        self.assertEqual(len(payload["patterns"]), 2)
        promoted = [p for p in payload["patterns"] if p["status"] == "promoted"]
        self.assertEqual(len(promoted), 1)
        self.assertEqual(promoted[0]["pattern_id"], "pat_promoted_0001")
        self.assertEqual(promoted[0]["instances_validated"], 3)
        self.assertEqual(promoted[0]["avg_improvement_pct"], 15.0)
        self.assertEqual(promoted[0]["avg_false_positive_pct"], 2.0)

    def test_instance_health_counts(self):
        """Per-instance counts: submitted, promoted, candidate."""
        payload = self._compute()
        # Build {instance_id: row}
        ih = {x["instance_id"]: x for x in payload["instance_health"]}
        # Alpha (aaaa): 1 mem + 1 forge = 2 submitted, 1 promoted, 0 candidate
        self.assertEqual(ih["aaaa1111aaaa"]["submitted"], 2)
        self.assertEqual(ih["aaaa1111aaaa"]["promoted"], 1)
        self.assertEqual(ih["aaaa1111aaaa"]["candidate"], 0)
        self.assertEqual(ih["aaaa1111aaaa"]["display_name"], "Instance Alpha")
        # Beta (bbbb): 1 mem + 1 dojo = 2 submitted, 1 promoted
        self.assertEqual(ih["bbbb2222bbbb"]["submitted"], 2)
        self.assertEqual(ih["bbbb2222bbbb"]["display_name"], "Instance Beta")
        # Gamma (cccc): 1 mem = 1 submitted, 1 promoted (in promoted pattern)
        self.assertEqual(ih["cccc3333cccc"]["submitted"], 1)
        # Delta (dddd): 1 forge = 1 submitted, 0 promoted, 1 candidate
        self.assertEqual(ih["dddd4444dddd"]["submitted"], 1)
        self.assertEqual(ih["dddd4444dddd"]["promoted"], 0)
        self.assertEqual(ih["dddd4444dddd"]["candidate"], 1)
        # Delta has no profile entry → display_name falls back to instance_id
        self.assertEqual(ih["dddd4444dddd"]["display_name"], "dddd4444dddd")

    def test_instance_health_sorted_by_submissions_desc(self):
        """instance_health is sorted by submitted desc, then promoted desc."""
        payload = self._compute()
        submitted = [x["submitted"] for x in payload["instance_health"]]
        self.assertEqual(submitted, sorted(submitted, reverse=True))

    def test_leaderboard_sorted_by_promoted_desc(self):
        """pattern_quality_leaderboard is sorted by promoted desc, then submitted desc."""
        payload = self._compute()
        lb = payload["pattern_quality_leaderboard"]
        # Tiebreaker check: ties broken by submitted desc
        for i in range(len(lb) - 1):
            cur = lb[i]
            nxt = lb[i + 1]
            if cur["promoted"] == nxt["promoted"]:
                self.assertGreaterEqual(cur["submitted"], nxt["submitted"])


class TestPrivacyContract(unittest.TestCase):
    """The privacy contract is the most important thing E2.4 ships."""

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.td, ignore_errors=True))
        self.rd = _build_synthetic_federation(self.td)

    def _compute(self):
        with mock.patch.object(fed, "REGISTRY_DIR", type(fed.REGISTRY_DIR)(str(self.rd))):
            return fed.compute_stats(fed._read_profiles())

    def test_no_patch_content_exposed(self):
        """The 'patch' field is STRIPPED — never appears in output."""
        payload = self._compute()
        blob = json.dumps(payload)
        # The synthetic data has "SECRET-PATCH-aaaa1111aaaa" etc. — these
        # must NOT appear anywhere in the output.
        for secret in ("SECRET-PATCH-aaaa1111aaaa",
                       "SECRET-PATCH-bbbb2222bbbb",
                       "SECRET-PATCH-cccc3333cccc",
                       "SECRET-FORGE-aaaa1111aaaa",
                       "SECRET-FORGE-dddd4444dddd",
                       "SECRET-DOJO-1"):
            self.assertNotIn(secret, blob, f"{secret!r} leaked into output")

    def test_no_trigger_strings_exposed(self):
        """The 'trigger' field is STRIPPED — never appears in output."""
        payload = self._compute()
        blob = json.dumps(payload)
        for secret in ("secret-trigger-aaaa1111aaaa",
                       "secret-trigger-bbbb2222bbbb",
                       "secret-trigger-cccc3333cccc",
                       "secret-forge-aaaa1111aaaa",
                       "secret-forge-dddd4444dddd",
                       "secret-dojo-1"):
            self.assertNotIn(secret, blob, f"{secret!r} leaked into output")

    def test_submission_timestamps_not_in_payload_data(self):
        """The 'submitted_at' field does not appear in PAYLOAD DATA.

        It MAY appear in the _privacy.stripped_fields list (a meta-record
        of what was stripped), but never as actual data.
        """
        payload = self._compute()
        # Walk all values; the only "submitted_at" string should be inside
        # _privacy.stripped_fields.
        def _walk(o, path=""):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k == "submitted_at" and path != "_privacy":
                        # We do allow it to be a KEY name (e.g. inside the
                        # _privacy contract block); the assertion checks
                        # that it isn't a data value.
                        if isinstance(v, str):
                            self.fail(f"submitted_at value leaked at {path}.{k}: {v!r}")
                    _walk(v, f"{path}.{k}")
            elif isinstance(o, list):
                for i, v in enumerate(o):
                    _walk(v, f"{path}[{i}]")
        _walk(payload)

    def test_pattern_aggregates_have_no_patch(self):
        """Per-pattern aggregates (from pattern-effectiveness) must not include patch."""
        payload = self._compute()
        for p in payload["patterns"]:
            self.assertNotIn("patch", p, f"patch leaked into pattern aggregate {p.get('pattern_id')}")
            self.assertNotIn("trigger", p, f"trigger leaked into pattern aggregate {p.get('pattern_id')}")

    def test_privacy_block_documented(self):
        """The _privacy block documents what was stripped (for auditors)."""
        payload = self._compute()
        self.assertIn("_privacy", payload)
        p = payload["_privacy"]
        self.assertIn("stripped_fields", p)
        self.assertIn("patch", p["stripped_fields"])
        self.assertIn("trigger", p["stripped_fields"])
        self.assertIn("submitted_at", p["stripped_fields"])
        self.assertFalse(p["patch_content_exposed"])
        self.assertFalse(p["trigger_strings_exposed"])
        self.assertFalse(p["submission_timestamps_exposed"])
        self.assertTrue(p["instance_id_is_anonymous_hash"])

    def test_instance_id_is_anonymous_hash(self):
        """Instance identities in the output are the 12-hex-char anonymous hashes."""
        payload = self._compute()
        for row in payload["instance_health"]:
            self.assertEqual(len(row["instance_id"]), 12, f"unexpected instance_id: {row['instance_id']!r}")
            # 12 hex chars
            try:
                int(row["instance_id"], 16)
            except ValueError:
                self.fail(f"instance_id {row['instance_id']!r} is not pure hex")
        for row in payload["pattern_quality_leaderboard"]:
            self.assertEqual(len(row["instance_id"]), 12)

    def test_display_names_come_from_profiles(self):
        """Display names are pulled from PROFILES.json (sanity check)."""
        payload = self._compute()
        ih = {x["instance_id"]: x for x in payload["instance_health"]}
        # Profiles has 2 of 4 instances
        self.assertEqual(ih["aaaa1111aaaa"]["display_name"], "Instance Alpha")
        self.assertEqual(ih["bbbb2222bbbb"]["display_name"], "Instance Beta")
        # Unregistered instances fall back to instance_id
        self.assertEqual(ih["cccc3333cccc"]["display_name"], "cccc3333cccc")
        self.assertEqual(ih["dddd4444dddd"]["display_name"], "dddd4444dddd")


class TestSanitizeItem(unittest.TestCase):
    """The _sanitize_item helper is the building block of the privacy contract."""

    def test_strips_all_private_fields(self):
        item = {
            "type": "synonym_expansion",
            "trigger": "secret",
            "patch": {"x": 1},
            "source_ref": "/path/to/secret",
            "submitted_at": "2026-06-11T00:00:00Z",
            "effectiveness": {"improvement_pct": 15.0, "false_positive_pct": 2.0},
        }
        safe = fed._sanitize_item(item)
        self.assertEqual(safe.get("type"), "synonym_expansion")
        self.assertNotIn("trigger", safe)
        self.assertNotIn("patch", safe)
        self.assertNotIn("source_ref", safe)
        self.assertNotIn("submitted_at", safe)
        # Effectiveness numeric metrics are kept
        self.assertEqual(safe["effectiveness"]["improvement_pct"], 15.0)
        self.assertEqual(safe["effectiveness"]["false_positive_pct"], 2.0)

    def test_keeps_only_numeric_effectiveness(self):
        item = {
            "type": "t",
            "effectiveness": {
                "improvement_pct": 10.0,
                "improvementPct": 11.0,        # alt name
                "false_positive_pct": 1.0,
                "falsePositivePct": 1.5,         # alt name
                "contradiction_rate_pct": 0.5,
                "qualitative_note": "great",     # not numeric — should be dropped
            },
        }
        safe = fed._sanitize_item(item)
        eff = safe.get("effectiveness", {})
        self.assertEqual(eff.get("improvement_pct"), 10.0)
        self.assertEqual(eff.get("improvementPct"), 11.0)
        self.assertEqual(eff.get("false_positive_pct"), 1.0)
        self.assertEqual(eff.get("falsePositivePct"), 1.5)
        self.assertEqual(eff.get("contradiction_rate_pct"), 0.5)
        self.assertNotIn("qualitative_note", eff)

    def test_handles_non_dict_input(self):
        self.assertEqual(fed._sanitize_item(None), {})
        self.assertEqual(fed._sanitize_item("not a dict"), {})
        self.assertEqual(fed._sanitize_item(42), {})

    def test_handles_non_dict_effectiveness(self):
        item = {"type": "t", "effectiveness": "not a dict"}
        safe = fed._sanitize_item(item)
        self.assertNotIn("effectiveness", safe)


class TestEmptyAndEdgeCases(unittest.TestCase):
    """Backwards compat + edge cases."""

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.td, ignore_errors=True))
        self.rd = Path(self.td) / "var" / "www" / "clawforge"
        for sub in ("memory-patterns", "forge-adjustments", "dojo-learnings",
                    "pattern-effectiveness", "profiles"):
            (self.rd / sub).mkdir(parents=True, exist_ok=True)

    def _compute(self):
        with mock.patch.object(fed, "REGISTRY_DIR", type(fed.REGISTRY_DIR)(str(self.rd))):
            return fed.compute_stats(fed._read_profiles())

    def test_all_empty_registries(self):
        """Empty registries → empty but valid output."""
        (self.rd / "memory-patterns" / "INDEX.json").write_text("[]")
        (self.rd / "forge-adjustments" / "INDEX.json").write_text("[]")
        (self.rd / "dojo-learnings" / "INDEX.json").write_text("[]")
        (self.rd / "pattern-effectiveness" / "INDEX.json").write_text(json.dumps({
            "schema_version": 1, "total_patterns": 0, "promoted_count": 0,
            "candidate_count": 0, "unvalidated_count": 0, "patterns": [],
        }))
        (self.rd / "profiles" / "PROFILES.json").write_text(json.dumps({"instances": {}}))
        payload = self._compute()
        self.assertEqual(payload["totals"]["instances"], 0)
        self.assertEqual(payload["totals"]["submissions"], 0)
        self.assertEqual(payload["patterns"], [])
        self.assertEqual(payload["instance_health"], [])
        self.assertEqual(payload["pattern_quality_leaderboard"], [])

    def test_missing_registries_treated_as_empty(self):
        """Registries that don't exist yet → no crash, empty result."""
        # Don't create any INDEX.json files
        (self.rd / "profiles" / "PROFILES.json").write_text(json.dumps({"instances": {}}))
        payload = self._compute()
        self.assertEqual(payload["totals"]["instances"], 0)
        self.assertEqual(payload["totals"]["submissions"], 0)

    def test_missing_profiles_falls_back_to_instance_id(self):
        """No PROFILES.json → display_name = instance_id for all."""
        (self.rd / "memory-patterns" / "INDEX.json").write_text(json.dumps([{
            "instance_id": "abc123def456",
            "patterns": [{"type": "t", "effectiveness": {"improvement_pct": 5.0}}],
        }]))
        # No pattern-effectiveness
        (self.rd / "pattern-effectiveness" / "INDEX.json").write_text(json.dumps({
            "total_patterns": 0, "promoted_count": 0, "candidate_count": 0,
            "unvalidated_count": 0, "patterns": [],
        }))
        # No profiles
        payload = self._compute()
        ih = payload["instance_health"]
        self.assertEqual(len(ih), 1)
        self.assertEqual(ih[0]["display_name"], "abc123def456")

    def test_malformed_registry_doesnt_crash(self):
        """A registry with invalid JSON is treated as empty (warning logged)."""
        (self.rd / "memory-patterns" / "INDEX.json").write_text("not valid json {")
        (self.rd / "forge-adjustments" / "INDEX.json").write_text("[]")
        (self.rd / "dojo-learnings" / "INDEX.json").write_text("[]")
        (self.rd / "pattern-effectiveness" / "INDEX.json").write_text(json.dumps({
            "total_patterns": 0, "promoted_count": 0, "candidate_count": 0,
            "unvalidated_count": 0, "patterns": [],
        }))
        (self.rd / "profiles" / "PROFILES.json").write_text(json.dumps({"instances": {}}))
        # Should not raise
        payload = self._compute()
        self.assertEqual(payload["totals"]["submissions"], 0)

    def test_output_schema_has_required_keys(self):
        """The output must always include the top-level schema keys."""
        payload = self._compute()
        required = {
            "schema_version", "updated_at", "totals",
            "by_source", "cross_instance_benchmarks", "patterns",
            "instance_health", "pattern_quality_leaderboard", "_privacy",
        }
        self.assertEqual(set(payload.keys()), required)

    def test_atomic_write_creates_index_json(self):
        """run() writes INDEX.json to the federation/ subdir."""
        (self.rd / "memory-patterns" / "INDEX.json").write_text("[]")
        (self.rd / "forge-adjustments" / "INDEX.json").write_text("[]")
        (self.rd / "dojo-learnings" / "INDEX.json").write_text("[]")
        (self.rd / "pattern-effectiveness" / "INDEX.json").write_text(json.dumps({
            "total_patterns": 0, "promoted_count": 0, "candidate_count": 0,
            "unvalidated_count": 0, "patterns": [],
        }))
        (self.rd / "profiles" / "PROFILES.json").write_text(json.dumps({"instances": {}}))
        with mock.patch.object(fed, "REGISTRY_DIR", type(fed.REGISTRY_DIR)(str(self.rd))):
            fed.run()
        out = self.rd / "federation" / "INDEX.json"
        self.assertTrue(out.exists(), f"missing output: {out}")
        data = json.loads(out.read_text())
        self.assertEqual(data["schema_version"], 1)


class TestAtHomeRelay7(unittest.TestCase):
    """End-to-end against the REAL relay-7 data (if accessible).

    These tests are skipped if the daemon can't access /var/www/clawforge.
    They serve as a live integration check that the synthetic test
    fixtures accurately model the real shape.
    """

    @classmethod
    def setUpClass(cls):
        cls.real_dir = Path("/var/www/clawforge")
        cls.accessible = (
            cls.real_dir.exists()
            and (cls.real_dir / "forge-adjustments" / "INDEX.json").exists()
        )

    def setUp(self):
        if not self.accessible:
            self.skipTest("real /var/www/clawforge not accessible")

    def test_runs_against_real_data(self):
        """compute_stats works on real relay-7 registries."""
        payload = fed.compute_stats(fed._read_profiles())
        # Basic sanity: at least 1 instance, 1 submission
        self.assertGreaterEqual(payload["totals"]["instances"], 1)
        self.assertGreaterEqual(payload["totals"]["submissions"], 1)
        # No leakage
        blob = json.dumps(payload)
        # The real data has source_systems, instance_ids, etc. — but no
        # patch content. Quick spot check: the real patch from
        # pattern-effectiveness (synthetic from earlier smoke) was null,
        # so we shouldn't see "patch": <dict> anywhere.
        for p in payload["patterns"]:
            self.assertNotIn("patch", p)


if __name__ == "__main__":
    unittest.main()
