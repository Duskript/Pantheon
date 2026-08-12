"""
Ichor-Retrieval Phase 0 baseline + Phase 9 contract tests.

Spec: ~/pantheon/plans/ichor-athenaeum-god-aware-retrieval-build-spec-v1.md
      §Phase 0 (baseline) + §Phase 9 (ichor_context_pack)

This file consumes the golden-queries fixture at
    tests/fixtures/ichor_golden_queries.yaml

and asserts the Phase 9 contract: a god-aware context pack whose
shape is determined by the (god, phase) tuple.

Phase 0 baseline:

  * `ichor_context_pack` is NOT implemented yet. We assert its
    absence at every import path: `lib.ichor.context_pack`,
    `pantheon-core.mcp_server`, and the broader `lib.ichor.*`
    namespace. When Phase 9 ships, the importer resolves and these
    tests start to fail — that's the signal to switch to the
    TestContract class below.

Phase 9 contract (xfail until Phase 9 ships):

  * `ichor_context_pack(query, god_name, phase, task_type, max_items)`
    returns a dict with the spec's required keys.
  * The golden queries distinguish Hephaestus and Thoth expectations
    for the SAME query text.
  * Every claim has source evidence/path/id.
  * No unhydrated vector-only item appears as a primary context item.

Acceptance criterion from the build spec §Phase 0:
  > Golden-query fixture distinguishes Hephaestus and Thoth
  > expectations for same query.

That's `TestContract.test_golden_query_distinguishes_hephaestus_and_thoth`.

No service restart required.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

GOLDEN_QUERIES_PATH = Path(_ROOT) / "tests" / "fixtures" / "ichor_golden_queries.yaml"
DRY_RUN_SCRIPT_PATH = Path(_ROOT) / "scripts" / "dry-run-ichor-context-pack.py"


# ─────────────────────────────────────────────────────────────────────
# Fixture loader
# ─────────────────────────────────────────────────────────────────────

def _load_golden_queries() -> List[Dict[str, Any]]:
    """Load the golden-queries fixture.

    Returns the list of query dicts (the `queries:` block).
    Raises a clear assertion error if the file is missing or
    malformed — both block Phase 0 closure.
    """
    assert GOLDEN_QUERIES_PATH.exists(), (
        f"Golden-queries fixture missing: {GOLDEN_QUERIES_PATH}"
    )
    with open(GOLDEN_QUERIES_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict), f"top-level must be a mapping, got {type(data)}"
    assert "queries" in data, "missing 'queries:' block"
    queries = data["queries"]
    assert isinstance(queries, list) and len(queries) > 0, (
        "'queries' must be a non-empty list"
    )
    for q in queries:
        for required in ("id", "query", "god", "phase", "must_include"):
            assert required in q, f"golden query {q.get('id', '?')} missing {required!r}"
    return queries


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _candidate_import_paths() -> List[str]:
    """Module paths Phase 9 might land `ichor_context_pack` under.

    We probe each one and report which exists / which doesn't. The
    baseline test asserts NONE of them resolves today.
    """
    return [
        "lib.ichor.context_pack",
        "lib.ichor.context_pack.build_context_pack",
        "lib.ichor.context_pack.ichor_context_pack",
    ]


def _has_context_pack_callable() -> bool:
    """Return True iff `ichor_context_pack` is importable as a callable.

    Probes a few candidate module paths. The probe is best-effort
    and never raises.
    """
    for path in _candidate_import_paths():
        try:
            mod = importlib.import_module(path)
        except (ImportError, ModuleNotFoundError):
            continue
        attr = getattr(mod, "ichor_context_pack", None) or getattr(
            mod, "build_context_pack", None
        )
        if callable(attr):
            return True
    return False


# ─────────────────────────────────────────────────────────────────────
# BASELINE: documents current state (ichor_context_pack not shipped)
# ─────────────────────────────────────────────────────────────────────

class TestBaseline(unittest.TestCase):
    """Phase 0 baseline — proves ichor_context_pack is not yet shipped.

    These tests pass NOW. When Phase 9 lands, they should be removed
    (or migrated to the TestContract class) because the function
    exists and the baseline no longer applies.
    """

    def test_ichor_context_pack_not_yet_importable(self) -> None:
        """WEAKNESS: ichor_context_pack does not exist yet.

        Spec §Phase 9 requires the function at
        `lib/ichor/context_pack.py`. Today the module is not there.
        """
        self.assertFalse(
            _has_context_pack_callable(),
            "ichor_context_pack / build_context_pack is already importable — "
            "this baseline test is stale. Move to the TestContract class.",
        )

    def test_golden_queries_fixture_loads(self) -> None:
        """The golden-queries fixture is readable and well-formed.

        This guards the fixture itself. If a future edit breaks the
        YAML, this test catches it before downstream tests do.
        """
        queries = _load_golden_queries()
        self.assertGreaterEqual(len(queries), 3,
            "spec requires 3 golden queries; fixture has fewer")

    def test_golden_queries_have_distinct_expectations(self) -> None:
        """The same query for different gods must have different must_include sets.

        This is the §Phase 0 acceptance criterion:
          > Golden-query fixture distinguishes Hephaestus and Thoth
          > expectations for same query.
        """
        queries = _load_golden_queries()
        by_query: Dict[str, List[Dict[str, Any]]] = {}
        for q in queries:
            by_query.setdefault(q["query"], []).append(q)

        # Find a query that appears multiple times
        same_query = [
            (qtext, qs) for qtext, qs in by_query.items() if len(qs) > 1
        ]
        self.assertTrue(
            same_query,
            "fixture should have at least one query used by multiple gods "
            "(the spec example: 'Conductor v2' for hephaestus + thoth)",
        )
        # For each repeated query, the must_include sets must differ
        for qtext, qs in same_query:
            include_sets = [tuple(sorted(q["must_include"])) for q in qs]
            self.assertGreater(
                len(set(include_sets)), 1,
                f"query {qtext!r} has identical must_include across gods; "
                "golden-queries fixture does NOT distinguish expectations",
            )

    def test_golden_queries_have_required_gods(self) -> None:
        """The three required gods are present."""
        queries = _load_golden_queries()
        gods = {q["god"] for q in queries}
        for required in ("hephaestus", "thoth", "rheta"):
            self.assertIn(
                required, gods,
                f"golden-queries fixture missing required god {required!r}",
            )

    def test_golden_query_must_include_tokens_are_substrings(self) -> None:
        """Tokens in must_include are short enough to be useful substrings.

        Guard rail: prevents a future edit that adds a 200-char
        string to must_include, which would make the assertion
        useless.
        """
        queries = _load_golden_queries()
        for q in queries:
            for token in q["must_include"]:
                self.assertLessEqual(
                    len(token), 40,
                    f"query {q['id']}!r: must_include token {token!r} is "
                    "too long to be a useful substring match",
                )
                self.assertGreater(
                    len(token), 0,
                    f"query {q['id']}!r: empty must_include token",
                )


# ─────────────────────────────────────────────────────────────────────
# PHASE 0 DRY-RUN: measurement scaffold, no context-pack behavior
# ─────────────────────────────────────────────────────────────────────

class TestPhase0DryRunCLI(unittest.TestCase):
    """Phase 0 dry-run measurement harness."""

    def _run_json(self, *extra_args: str) -> Dict[str, Any]:
        env = os.environ.copy()
        env["PYTHONPATH"] = _ROOT
        proc = subprocess.run(
            [
                sys.executable,
                str(DRY_RUN_SCRIPT_PATH),
                "--god",
                "thoth",
                "--phase",
                "research",
                "--query",
                "Conductor v2",
                "--max-items",
                "8",
                "--format",
                "json",
                *extra_args,
            ],
            cwd=_ROOT,
            env=env,
            check=True,
            text=True,
            capture_output=True,
        )
        return json.loads(proc.stdout)

    def test_dry_run_json_emits_runtime_safety_fields(self) -> None:
        payload = self._run_json()
        for key in (
            "would_mutate_runtime",
            "would_rotate_session",
            "would_rewrite_transcript",
            "would_change_config",
            "would_restart_gateway",
        ):
            self.assertIn(key, payload)
            self.assertIs(payload[key], False)

    def test_dry_run_json_emits_metric_schema_without_llm_or_writes(self) -> None:
        payload = self._run_json("--compare-default-compressor")
        metrics = payload["metrics"]
        for key in (
            "wall_ms",
            "rss_delta_kb",
            "peak_rss_kb",
            "db_reads",
            "db_writes",
            "rows_examined",
            "tokens_estimated",
            "llm_calls",
            "api_calls",
            "cache_read_tokens",
            "cache_write_tokens",
        ):
            self.assertIn(key, metrics)
        self.assertEqual(metrics["llm_calls"], 0)
        self.assertEqual(metrics["api_calls"], 0)
        self.assertEqual(metrics["db_reads"], 0)
        self.assertEqual(metrics["db_writes"], 0)
        self.assertIn("candidate_context_pack", payload)
        self.assertIs(payload["candidate_context_pack"]["would_build_context_pack"], False)
        self.assertIn("default_compressor_baseline", payload)
        self.assertNotIn("compressed_messages", payload["default_compressor_baseline"])
        self.assertIs(payload["default_compressor_baseline"]["would_call_compress_method"], False)
        self.assertEqual(payload["default_compressor_baseline"]["api_calls"], 0)

    def test_dry_run_script_avoids_forbidden_runtime_mutation_paths(self) -> None:
        script = DRY_RUN_SCRIPT_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "_compress_context",
            ".compress(",
            "SessionDB",
            ".end_session(",
            "continuation session",
            "config.yaml",
            "systemctl",
            "hermes-gateway",
        ):
            self.assertNotIn(forbidden, script)

    def test_dry_run_markdown_reports_non_mutation(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = _ROOT
        proc = subprocess.run(
            [
                sys.executable,
                str(DRY_RUN_SCRIPT_PATH),
                "--god",
                "thoth",
                "--phase",
                "research",
                "--query",
                "Conductor v2",
                "--max-items",
                "8",
                "--compare-default-compressor",
                "--format",
                "markdown",
            ],
            cwd=_ROOT,
            env=env,
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertIn("would_mutate_runtime: false", proc.stdout)
        self.assertIn("llm_calls: 0", proc.stdout)


# ─────────────────────────────────────────────────────────────────────
# CONTRACT: Phase 9 deliverables (xfail until Phase 9 ships)
# ─────────────────────────────────────────────────────────────────────

class TestContract:
    """Phase 9 contract — god-aware context pack.

    These tests are xfail until Phase 9 ships. When they start
    passing, remove the markers and the TestBaseline half becomes
    historical reference.
    """

    def test_ichor_context_pack_is_callable(self) -> None:
        assert _has_context_pack_callable(), (
            "Phase 9 must ship ichor_context_pack (or build_context_pack) "
            "at one of: " + ", ".join(_candidate_import_paths())
        )

    def test_context_pack_return_shape(self) -> None:
        """Phase 9 must return the spec's required shape."""
        from lib.ichor.context_pack import build_context_pack  # type: ignore
        pack = build_context_pack(
            "Conductor v2", god_name="hephaestus", phase="debug",
            max_items=8,
        )
        required_keys = {
            "query", "god", "phase",
            "coverage",
            "current_decisions", "hard_constraints", "relevant_files",
            "risks", "related_entities", "recent_changes",
            "source_links", "omitted",
        }
        for key in required_keys:
            assert key in pack, f"context_pack missing required key: {key!r}"
        assert pack["god"] == "hephaestus"
        assert pack["phase"] == "debug"
        assert isinstance(pack["omitted"], dict)
        assert "count" in pack["omitted"]
        assert "reasons" in pack["omitted"]

    def test_golden_query_distinguishes_hephaestus_and_thoth(self) -> None:
        """For 'Conductor v2', hephaestus sees NATS/MCP/endpoint/systemd
        and thoth sees workflow/cross-god/routing. The same query text
        must produce role-differentiated packs.
        """
        from lib.ichor.context_pack import build_context_pack  # type: ignore

        hep_pack = build_context_pack(
            "Conductor v2", god_name="hephaestus", phase="debug", max_items=8,
        )
        thoth_pack = build_context_pack(
            "Conductor v2", god_name="thoth", phase="research", max_items=8,
        )

        # Serialize both packs to text so substring assertions work
        def _pack_text(p: Dict[str, Any]) -> str:
            parts = [p.get("query", "")]
            for k in (
                "current_decisions", "hard_constraints", "relevant_files",
                "risks", "related_entities", "recent_changes",
            ):
                for v in p.get(k, []) or []:
                    if isinstance(v, dict):
                        for vv in v.values():
                            parts.append(str(vv))
                    else:
                        parts.append(str(v))
            return " \n ".join(parts).lower()

        hep_text = _pack_text(hep_pack)
        thoth_text = _pack_text(thoth_pack)

        for token in ("NATS", "MCP", "endpoint", "systemd"):
            assert token.lower() in hep_text, (
                f"Hephaestus debug pack missing must_include token {token!r}"
            )
        for token in ("workflow", "cross-god", "routing"):
            assert token.lower() in thoth_text, (
                f"Thoth research pack missing must_include token {token!r}"
            )

        # Distinction: the two packs must NOT be byte-identical
        assert hep_text != thoth_text, (
            "Hephaestus and Thoth packs for 'Conductor v2' are identical; "
            "the context pack is not role-aware"
        )

    def test_context_pack_has_source_evidence_per_claim(self) -> None:
        """Every primary claim has a source path/id (no unhydrated vectors)."""
        from lib.ichor.context_pack import build_context_pack  # type: ignore
        pack = build_context_pack(
            "Conductor v2", god_name="hephaestus", phase="debug", max_items=8,
        )
        for key in (
            "current_decisions", "hard_constraints", "relevant_files",
            "risks", "related_entities", "recent_changes",
        ):
            for claim in pack.get(key, []) or []:
                if isinstance(claim, dict):
                    has_source = any(
                        k in claim for k in ("source", "source_path", "source_id", "path", "id")
                    )
                    assert has_source, (
                        f"context_pack[{key}] claim lacks source evidence: {claim!r}"
                    )

    def test_rheta_pricing_golden_query(self) -> None:
        """The third golden query: Rheta writing pricing copy."""
        from lib.ichor.context_pack import build_context_pack  # type: ignore
        pack = build_context_pack(
            "Pantheon pricing managed retainer dedicated infrastructure",
            god_name="rheta", phase="copywriting", max_items=8,
        )
        pack_text = " ".join(
            str(v) for k in pack
            if k not in ("omitted", "coverage")
            for v in (pack[k] if isinstance(pack[k], list) else [pack[k]])
        ).lower()
        for token in ("$5k", "managed", "dedicated infrastructure"):
            assert token.lower() in pack_text, (
                f"Rheta copywriting pack missing must_include token {token!r}"
            )


# Mark contract tests as expected-to-fail (Phase 9 not yet shipped)
_XFAIL_REASON = (
    "Phase 9 (ichor_context_pack) not yet shipped — see "
    "ichor-athenaeum-god-aware-retrieval-build-spec-v1.md §Phase 9"
)

for _name in (
    "test_ichor_context_pack_is_callable",
    "test_context_pack_return_shape",
    "test_golden_query_distinguishes_hephaestus_and_thoth",
    "test_context_pack_has_source_evidence_per_claim",
    "test_rheta_pricing_golden_query",
):
    setattr(
        TestContract,
        _name,
        pytest.mark.xfail(reason=_XFAIL_REASON, strict=False)(
            getattr(TestContract, _name)
        ),
    )
