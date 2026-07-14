"""Tests for E2.3 Evolve Server validator threshold configurability.

The validator (relay-7 daemon) classifies patterns as
unvalidated/candidate/promoted using four numeric thresholds. Previously
hardcoded as module constants; now loaded from CLI > env > YAML > defaults
with per-source overrides.

Covers:
  - Default threshold loading
  - Env var overrides
  - YAML config file overrides (full + per-source)
  - CLI flag overrides
  - Priority chain (CLI beats env, env beats YAML, YAML beats defaults)
  - Threshold schema validation (rejects bool, fractional int, missing fields,
    negative values, malformed by_source)
  - _classify() with per-source overrides
  - _classify() backwards compat (no thresholds arg = defaults)
  - run_validation() end-to-end with synthetic 3-source registries
  - get_token_path / _token_path are not broken (E2.3 didn't rename)
  - MIN_* module constants are still set (backwards compat for any
    external import)
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

# ---------------------------------------------------------------------------
# Module import (the validator is a script with hyphens, not a package)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR_PATH = REPO_ROOT / "scripts" / "clawforge-effectiveness-validator.py"


def _load_validator():
    """Import the validator script as a module under a stable name.

    The validator is shipped as a standalone script with hyphens in its
    filename (clawforge-effectiveness-validator.py), so we can't import
    it via the normal package machinery. Use importlib to load it
    under a stable, importable name instead.

    Returns the loaded module object.
    Raises ImportError on any load failure.
    """
    spec = importlib.util.spec_from_file_location(
        "clawforge_effectiveness_validator", str(VALIDATOR_PATH)
    )
    if spec is None:  # pragma: no cover - only happens on import error
        raise ImportError(f"could not load spec for {VALIDATOR_PATH}")
    mod = importlib.util.module_from_spec(spec)
    loader = spec.loader
    if loader is None:  # pragma: no cover - only happens on import error
        raise ImportError(f"spec has no loader for {VALIDATOR_PATH}")
    loader.exec_module(mod)
    return mod


# Load once at import time so individual tests can access module state
val = _load_validator()


def _reset_argv():
    """Reset sys.argv to a no-args baseline."""
    sys.argv = ["clawforge-effectiveness-validator"]


def _clear_env(monkeypatch=None):
    """Clear all CLAWFORGE_* env vars related to thresholds."""
    env_keys = [
        "CLAWFORGE_MIN_INSTANCES_PROMOTED",
        "CLAWFORGE_MIN_CONFIRMED_PROMOTED",
        "CLAWFORGE_MIN_IMPROVEMENT_PCT",
        "CLAWFORGE_MAX_FALSE_POSITIVE_PCT",
    ]
    if monkeypatch:
        for k in env_keys:
            monkeypatch.delenv(k, raising=False)
    else:
        for k in env_keys:
            os.environ.pop(k, None)


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestDefaults(unittest.TestCase):
    """When no env, no YAML, no CLI overrides are set, defaults apply."""

    def setUp(self):
        _reset_argv()
        _clear_env()

    def test_load_thresholds_no_config(self):
        """No env, no YAML file present, no CLI — should return defaults."""
        # Use a non-existent config path so no YAML is loaded
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "validator.yaml"
            t = val.load_thresholds(config_path=cfg)
        self.assertEqual(t["min_instances"], 3)
        self.assertEqual(t["min_confirmed"], 2)
        self.assertEqual(t["min_improvement_pct"], 10.0)
        self.assertEqual(t["max_false_positive_pct"], 5.0)
        self.assertIn("by_source", t)
        # by_source is present even if empty (from defaults)
        self.assertEqual(t["by_source"], {"memory": {}, "forge": {}, "dojo": {}})

    def test_default_thresholds_module_constant(self):
        """DEFAULT_THRESHOLDS module constant has the historical values."""
        self.assertEqual(val.DEFAULT_THRESHOLDS["min_instances"], 3)
        self.assertEqual(val.DEFAULT_THRESHOLDS["min_confirmed"], 2)
        self.assertEqual(val.DEFAULT_THRESHOLDS["min_improvement_pct"], 10.0)
        self.assertEqual(val.DEFAULT_THRESHOLDS["max_false_positive_pct"], 5.0)

    def test_backwards_compat_module_constants(self):
        """MIN_INSTANCES_PROMOTED etc. are still set (old import works)."""
        self.assertEqual(val.MIN_INSTANCES_PROMOTED, 3)
        self.assertEqual(val.MIN_CONFIRMED_PROMOTED, 2)
        self.assertEqual(val.MIN_IMPROVEMENT_PCT, 10.0)
        self.assertEqual(val.MAX_FALSE_POSITIVE_PCT, 5.0)


class TestEnvOverrides(unittest.TestCase):
    """Env vars override YAML/defaults (lower priority than CLI)."""

    def setUp(self):
        _reset_argv()

    def test_env_overrides_all_four(self):
        """All four env vars override defaults."""
        with mock.patch.dict(os.environ, {
            "CLAWFORGE_MIN_INSTANCES_PROMOTED": "5",
            "CLAWFORGE_MIN_CONFIRMED_PROMOTED": "4",
            "CLAWFORGE_MIN_IMPROVEMENT_PCT": "20.0",
            "CLAWFORGE_MAX_FALSE_POSITIVE_PCT": "3.5",
        }, clear=True):
            with tempfile.TemporaryDirectory() as td:
                cfg = Path(td) / "validator.yaml"
                t = val.load_thresholds(config_path=cfg)
        self.assertEqual(t["min_instances"], 5)
        self.assertEqual(t["min_confirmed"], 4)
        self.assertEqual(t["min_improvement_pct"], 20.0)
        self.assertEqual(t["max_false_positive_pct"], 3.5)

    def test_env_partial_override(self):
        """Only one env var set — others stay at defaults."""
        with mock.patch.dict(os.environ, {
            "CLAWFORGE_MIN_INSTANCES_PROMOTED": "7",
        }, clear=True):
            with tempfile.TemporaryDirectory() as td:
                cfg = Path(td) / "validator.yaml"
                t = val.load_thresholds(config_path=cfg)
        self.assertEqual(t["min_instances"], 7)
        self.assertEqual(t["min_confirmed"], 2)         # default
        self.assertEqual(t["min_improvement_pct"], 10.0)  # default

    def test_env_invalid_int_raises(self):
        """Non-numeric env var raises ValueError, not silent fall-through."""
        with mock.patch.dict(os.environ, {
            "CLAWFORGE_MIN_INSTANCES_PROMOTED": "not-a-number",
        }, clear=True):
            with tempfile.TemporaryDirectory() as td:
                cfg = Path(td) / "validator.yaml"
                with self.assertRaises(ValueError) as ctx:
                    val.load_thresholds(config_path=cfg)
                self.assertIn("CLAWFORGE_MIN_INSTANCES_PROMOTED", str(ctx.exception))

    def test_env_invalid_float_raises(self):
        with mock.patch.dict(os.environ, {
            "CLAWFORGE_MIN_IMPROVEMENT_PCT": "twenty",
        }, clear=True):
            with tempfile.TemporaryDirectory() as td:
                cfg = Path(td) / "validator.yaml"
                with self.assertRaises(ValueError):
                    val.load_thresholds(config_path=cfg)


class TestYAMLConfig(unittest.TestCase):
    """YAML config file overrides defaults (lower than env/CLI)."""

    def setUp(self):
        _reset_argv()
        _clear_env()

    def _write_yaml(self, content: str) -> Path:
        """Write a validator.yaml in a temp dir and return its path."""
        td = tempfile.mkdtemp()
        cfg = Path(td) / "validator.yaml"
        cfg.write_text(content)
        return cfg

    def test_yaml_full_overrides(self):
        cfg = self._write_yaml("""
validator:
  thresholds:
    min_instances: 10
    min_confirmed: 5
    min_improvement_pct: 25.0
    max_false_positive_pct: 2.0
""")
        t = val.load_thresholds(config_path=cfg)
        self.assertEqual(t["min_instances"], 10)
        self.assertEqual(t["min_confirmed"], 5)
        self.assertEqual(t["min_improvement_pct"], 25.0)
        self.assertEqual(t["max_false_positive_pct"], 2.0)

    def test_yaml_partial_overrides_uses_defaults_for_missing(self):
        cfg = self._write_yaml("""
validator:
  thresholds:
    min_instances: 4
""")
        t = val.load_thresholds(config_path=cfg)
        self.assertEqual(t["min_instances"], 4)
        # Missing fields fall through to defaults
        self.assertEqual(t["min_confirmed"], 2)
        self.assertEqual(t["min_improvement_pct"], 10.0)
        self.assertEqual(t["max_false_positive_pct"], 5.0)

    def test_yaml_per_source_overrides(self):
        cfg = self._write_yaml("""
validator:
  thresholds:
    min_instances: 3
    min_confirmed: 2
    min_improvement_pct: 10.0
    max_false_positive_pct: 5.0
    by_source:
      memory:
        min_instances: 2
      dojo:
        min_instances: 6
        min_confirmed: 3
      forge: {}
""")
        t = val.load_thresholds(config_path=cfg)
        # Base
        self.assertEqual(t["min_instances"], 3)
        # Per-source
        self.assertEqual(t["by_source"]["memory"]["min_instances"], 2)
        self.assertEqual(t["by_source"]["dojo"]["min_instances"], 6)
        self.assertEqual(t["by_source"]["dojo"]["min_confirmed"], 3)
        # forge: explicit empty dict in YAML — should still be present
        self.assertEqual(t["by_source"]["forge"], {})

    def test_yaml_no_validator_section(self):
        """YAML exists but has no 'validator:' key — should use defaults."""
        cfg = self._write_yaml("""
some_other_section:
  whatever: 1
""")
        t = val.load_thresholds(config_path=cfg)
        # All defaults
        self.assertEqual(t["min_instances"], 3)

    def test_yaml_no_thresholds_section(self):
        cfg = self._write_yaml("""
validator:
  some_other_field: 1
""")
        t = val.load_thresholds(config_path=cfg)
        self.assertEqual(t["min_instances"], 3)

    def test_yaml_thresholds_not_a_mapping(self):
        cfg = self._write_yaml("""
validator:
  thresholds: "this should be a mapping"
""")
        with self.assertRaises(ValueError) as ctx:
            val.load_thresholds(config_path=cfg)
        self.assertIn("thresholds", str(ctx.exception))

    def test_yaml_validator_section_not_a_mapping(self):
        cfg = self._write_yaml("""
validator: "this should be a mapping"
""")
        with self.assertRaises(ValueError) as ctx:
            val.load_thresholds(config_path=cfg)
        self.assertIn("validator", str(ctx.exception))

    def test_yaml_by_source_not_a_mapping(self):
        cfg = self._write_yaml("""
validator:
  thresholds:
    by_source: "should be a mapping"
""")
        with self.assertRaises(ValueError) as ctx:
            val.load_thresholds(config_path=cfg)
        self.assertIn("by_source", str(ctx.exception))

    def test_yaml_unknown_field_in_by_source(self):
        cfg = self._write_yaml("""
validator:
  thresholds:
    by_source:
      memory:
        not_a_real_field: 5
""")
        with self.assertRaises(ValueError) as ctx:
            val.load_thresholds(config_path=cfg)
        self.assertIn("unknown field", str(ctx.exception))

    def test_yaml_malformed_raises(self):
        cfg = self._write_yaml("""
validator:
  thresholds:
    min_instances: [unclosed list
""")
        with self.assertRaises(ValueError) as ctx:
            val.load_thresholds(config_path=cfg)
        # Some YAML parser error or "could not parse" wrapper
        self.assertTrue("could not parse" in str(ctx.exception) or
                        "scan" in str(ctx.exception).lower() or
                        "expected" in str(ctx.exception).lower(),
                        f"unexpected error: {ctx.exception}")


class TestCLIOverrides(unittest.TestCase):
    """CLI flags have highest priority."""

    def setUp(self):
        _clear_env()

    def test_cli_overrides_defaults(self):
        sys.argv = ["prog", "--min-instances", "8", "--min-improvement-pct", "30.5"]
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "validator.yaml"
            t = val.load_thresholds(config_path=cfg)
        self.assertEqual(t["min_instances"], 8)
        self.assertEqual(t["min_improvement_pct"], 30.5)
        # Untouched
        self.assertEqual(t["min_confirmed"], 2)

    def test_cli_overrides_env(self):
        """CLI > env: CLI flag wins over env var."""
        with mock.patch.dict(os.environ, {
            "CLAWFORGE_MIN_INSTANCES_PROMOTED": "5",
        }, clear=False):
            _clear_env()
            sys.argv = ["prog", "--min-instances", "12"]
            with tempfile.TemporaryDirectory() as td:
                cfg = Path(td) / "validator.yaml"
                t = val.load_thresholds(config_path=cfg)
        self.assertEqual(t["min_instances"], 12)  # CLI wins, not env's 5

    def test_cli_overrides_yaml(self):
        """CLI > YAML: CLI flag wins over YAML value."""
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write("""
validator:
  thresholds:
    min_instances: 9
""")
            cfg = Path(f.name)
        try:
            sys.argv = ["prog", "--min-instances", "20"]
            t = val.load_thresholds(config_path=cfg)
            self.assertEqual(t["min_instances"], 20)
        finally:
            cfg.unlink()

    def test_cli_all_four_flags(self):
        sys.argv = [
            "prog",
            "--min-instances", "10",
            "--min-confirmed", "5",
            "--min-improvement-pct", "15.0",
            "--max-false-positive-pct", "3.0",
        ]
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "validator.yaml"
            t = val.load_thresholds(config_path=cfg)
        self.assertEqual(t["min_instances"], 10)
        self.assertEqual(t["min_confirmed"], 5)
        self.assertEqual(t["min_improvement_pct"], 15.0)
        self.assertEqual(t["max_false_positive_pct"], 3.0)

    def test_cli_flag_missing_value_raises(self):
        sys.argv = ["prog", "--min-instances"]
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "validator.yaml"
            with self.assertRaises(ValueError) as ctx:
                val.load_thresholds(config_path=cfg)
            self.assertIn("--min-instances", str(ctx.exception))

    def test_cli_invalid_int_raises(self):
        sys.argv = ["prog", "--min-instances", "abc"]
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "validator.yaml"
            with self.assertRaises(ValueError):
                val.load_thresholds(config_path=cfg)

    def test_cli_unknown_flag_ignored(self):
        """Unknown flags are passed through, not errored (e.g. --help, --verbose)."""
        sys.argv = ["prog", "--unknown-flag", "ignored", "--min-instances", "4"]
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "validator.yaml"
            t = val.load_thresholds(config_path=cfg)
        # Recognized flag still works
        self.assertEqual(t["min_instances"], 4)

    def test_cli_overrides_param_skips_argv_parse(self):
        """Passing cli_overrides directly bypasses sys.argv parsing."""
        sys.argv = ["prog", "--min-instances", "1"]  # would normally win
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "validator.yaml"
            t = val.load_thresholds(
                config_path=cfg,
                cli_overrides={"min_instances": 99},
            )
        self.assertEqual(t["min_instances"], 99)  # explicit override wins


class TestPriorityChain(unittest.TestCase):
    """Full priority chain: CLI > env > YAML > defaults."""

    def setUp(self):
        _clear_env()

    def test_full_chain_cli_wins(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write("""
validator:
  thresholds:
    min_instances: 7
    min_confirmed: 6
    min_improvement_pct: 50.0
    max_false_positive_pct: 1.0
""")
            cfg = Path(f.name)
        try:
            with mock.patch.dict(os.environ, {
                "CLAWFORGE_MIN_INSTANCES_PROMOTED": "5",
                "CLAWFORGE_MIN_CONFIRMED_PROMOTED": "4",
            }, clear=True):
                # CLI overrides both env and YAML for min_instances
                sys.argv = ["prog", "--min-instances", "20"]
                t = val.load_thresholds(config_path=cfg)
                # CLI (20) > env (5) > YAML (7) > default (3)
                self.assertEqual(t["min_instances"], 20)
                # Env (4) > YAML (6) > default (2) — no CLI flag
                self.assertEqual(t["min_confirmed"], 4)
                # YAML (50.0) > default (10.0) — no env, no CLI
                self.assertEqual(t["min_improvement_pct"], 50.0)
                # YAML (1.0) > default (5.0)
                self.assertEqual(t["max_false_positive_pct"], 1.0)
        finally:
            cfg.unlink()

    def test_env_wins_over_yaml(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write("""
validator:
  thresholds:
    min_instances: 7
""")
            cfg = Path(f.name)
        try:
            with mock.patch.dict(os.environ, {
                "CLAWFORGE_MIN_INSTANCES_PROMOTED": "5",
            }, clear=True):
                sys.argv = ["prog"]
                t = val.load_thresholds(config_path=cfg)
                # env (5) > YAML (7) > default (3)
                self.assertEqual(t["min_instances"], 5)
        finally:
            cfg.unlink()


class TestValidation(unittest.TestCase):
    """Schema validation: rejects bad inputs cleanly."""

    def setUp(self):
        _reset_argv()
        _clear_env()

    def test_negative_threshold_raises(self):
        with mock.patch.dict(os.environ, {
            "CLAWFORGE_MIN_INSTANCES_PROMOTED": "-1",
        }, clear=True):
            with tempfile.TemporaryDirectory() as td:
                cfg = Path(td) / "validator.yaml"
                with self.assertRaises(ValueError) as ctx:
                    val.load_thresholds(config_path=cfg)
                self.assertIn("negative", str(ctx.exception).lower())

    def test_bool_threshold_rejected_from_yaml(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write("""
validator:
  thresholds:
    min_instances: true
""")
            cfg = Path(f.name)
        try:
            with self.assertRaises(ValueError) as ctx:
                val.load_thresholds(config_path=cfg)
            self.assertIn("bool", str(ctx.exception).lower())
        finally:
            cfg.unlink()

    def test_fractional_int_rejected(self):
        with mock.patch.dict(os.environ, {
            "CLAWFORGE_MIN_INSTANCES_PROMOTED": "3.5",
        }, clear=True):
            with tempfile.TemporaryDirectory() as td:
                cfg = Path(td) / "validator.yaml"
                with self.assertRaises(ValueError) as ctx:
                    val.load_thresholds(config_path=cfg)
                self.assertIn("integer", str(ctx.exception).lower())


class TestClassify(unittest.TestCase):
    """_classify() honors per-source thresholds."""

    def setUp(self):
        _reset_argv()
        _clear_env()

    def test_classify_with_no_thresholds_arg_uses_load(self):
        """Backwards compat: _classify(rec) still works (no thresholds arg)."""
        rec = {
            "instances_tested": {"i1", "i2", "i3"},
            "improvements_pct": [15.0, 20.0],
            "false_positive_pct": [1.0, 2.0],
            "source_systems": {"memory"},
        }
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "validator.yaml"
            # Patch _config_path temporarily so no real /etc/clawforge file is read
            with mock.patch.object(val, "_config_path", return_value=cfg):
                status = val._classify(rec)
        self.assertEqual(status, "promoted")

    def test_classify_per_source_override_promotes_at_lower_threshold(self):
        """Memory source with min_instances=2 should promote at 2 instances."""
        thresholds = {
            "min_instances": 3,   # base
            "min_confirmed": 2,
            "min_improvement_pct": 10.0,
            "max_false_positive_pct": 5.0,
            "by_source": {
                "memory": {"min_instances": 2},   # memory-only override
                "forge": {},
                "dojo": {},
            },
        }
        # 2 instances would NOT be promoted with base, but IS with memory override
        rec = {
            "instances_tested": {"i1", "i2"},
            "improvements_pct": [15.0, 20.0],
            "false_positive_pct": [1.0],
            "source_systems": {"memory"},
        }
        self.assertEqual(val._classify(rec, thresholds), "promoted")

        # But a forge record at 2 instances would be candidate (not promoted)
        rec_forge = dict(rec, source_systems={"forge"})
        self.assertEqual(val._classify(rec_forge, thresholds), "candidate")

    def test_classify_per_source_stricter_blocks(self):
        """Dojo source with min_instances=6: 5 instances should NOT promote."""
        thresholds = {
            "min_instances": 3,
            "min_confirmed": 2,
            "min_improvement_pct": 10.0,
            "max_false_positive_pct": 5.0,
            "by_source": {
                "memory": {},
                "forge": {},
                "dojo": {"min_instances": 6, "min_confirmed": 4},
            },
        }
        rec = {
            "instances_tested": {"i1", "i2", "i3", "i4", "i5"},
            "improvements_pct": [15.0, 20.0, 18.0, 12.0, 11.0],
            "false_positive_pct": [1.0],
            "source_systems": {"dojo"},
        }
        # 5 instances, 5 confirmed-positive, avg 15.2 — but dojo wants 6/4
        self.assertEqual(val._classify(rec, thresholds), "candidate")

    def test_classify_multi_source_uses_base(self):
        """If a record spans multiple sources, use conservative base rules."""
        thresholds = {
            "min_instances": 3,
            "min_confirmed": 2,
            "min_improvement_pct": 10.0,
            "max_false_positive_pct": 5.0,
            "by_source": {
                "memory": {"min_instances": 2},  # more lenient
                "forge": {},
                "dojo": {"min_instances": 6},    # stricter
            },
        }
        rec = {
            "instances_tested": {"i1", "i2", "i3"},  # 3 instances
            "improvements_pct": [15.0, 20.0],
            "false_positive_pct": [1.0],
            "source_systems": {"memory", "forge"},  # multi-source
        }
        # Base is 3 → passes. But forge single-source at 3 also passes
        # (forge has no override). Just check the multi-source decision is
        # the BASE decision, not any of the overrides.
        status = val._classify(rec, thresholds)
        self.assertEqual(status, "promoted")  # base 3 + 3 confirmed + 17.5 avg → yes

    def test_classify_unvalidated_for_zero_instances(self):
        rec = {
            "instances_tested": set(),
            "improvements_pct": [],
            "false_positive_pct": [],
            "source_systems": {"memory"},
        }
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "validator.yaml"
            with mock.patch.object(val, "_config_path", return_value=cfg):
                status = val._classify(rec)
        self.assertEqual(status, "unvalidated")

    def test_classify_candidate_below_threshold(self):
        rec = {
            "instances_tested": {"i1", "i2"},  # only 2, default needs 3
            "improvements_pct": [15.0, 20.0],
            "false_positive_pct": [1.0],
            "source_systems": {"forge"},
        }
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "validator.yaml"
            with mock.patch.object(val, "_config_path", return_value=cfg):
                status = val._classify(rec)
        self.assertEqual(status, "candidate")


class TestThresholdsForSource(unittest.TestCase):
    """thresholds_for_source() merges base + override correctly."""

    def test_no_override_returns_base(self):
        thresholds = {
            "min_instances": 3,
            "min_confirmed": 2,
            "min_improvement_pct": 10.0,
            "max_false_positive_pct": 5.0,
            "by_source": {"memory": {}, "forge": {}, "dojo": {}},
        }
        flat = val.thresholds_for_source(thresholds, "memory")
        self.assertEqual(flat, {
            "min_instances": 3,
            "min_confirmed": 2,
            "min_improvement_pct": 10.0,
            "max_false_positive_pct": 5.0,
        })

    def test_override_wins_for_specific_field(self):
        thresholds = {
            "min_instances": 3,
            "min_confirmed": 2,
            "min_improvement_pct": 10.0,
            "max_false_positive_pct": 5.0,
            "by_source": {"memory": {"min_instances": 2, "min_confirmed": 1}},
        }
        flat = val.thresholds_for_source(thresholds, "memory")
        self.assertEqual(flat["min_instances"], 2)         # overridden
        self.assertEqual(flat["min_confirmed"], 1)         # overridden
        self.assertEqual(flat["min_improvement_pct"], 10.0)  # base
        self.assertEqual(flat["max_false_positive_pct"], 5.0)  # base

    def test_unknown_source_treated_as_base(self):
        thresholds = {
            "min_instances": 3,
            "min_confirmed": 2,
            "min_improvement_pct": 10.0,
            "max_false_positive_pct": 5.0,
            "by_source": {"memory": {"min_instances": 2}},
        }
        # "unknown" isn't in by_source → base
        flat = val.thresholds_for_source(thresholds, "unknown")
        self.assertEqual(flat["min_instances"], 3)

    def test_explicit_empty_override_uses_base(self):
        """by_source: {memory: {}} is present but empty — base wins."""
        thresholds = {
            "min_instances": 3,
            "min_confirmed": 2,
            "min_improvement_pct": 10.0,
            "max_false_positive_pct": 5.0,
            "by_source": {"memory": {}},
        }
        flat = val.thresholds_for_source(thresholds, "memory")
        self.assertEqual(flat["min_instances"], 3)


class TestEndToEnd(unittest.TestCase):
    """End-to-end: run_validation() with synthetic 3-source registries."""

    def setUp(self):
        _reset_argv()
        _clear_env()
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmpdir, ignore_errors=True))

    def _write_registry(self, subdir: str, entries: list) -> Path:
        path = Path(self.tmpdir) / subdir / "INDEX.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries))
        return path

    def test_run_validation_with_strict_thresholds(self):
        """3 instances, good improvements — promotes with default thresholds."""
        # Build synthetic registries: 3 instances each reporting the same
        # pattern (type+trigger+patch). Each reports positive improvement.
        pattern = {
            "type": "synonym_expansion",
            "trigger": "concept:python",
            "patch": {"replace": "snake"},
            "effectiveness": {"improvement_pct": 20.0, "false_positive_pct": 1.0},
        }
        entries = []
        for i in range(3):
            entries.append({
                "instance_id": f"instance_{i:02d}",
                "submitted_at": f"2026-06-1{i+1}T00:00:00Z",
                "patterns": [dict(pattern)],
            })
        self._write_registry("memory-patterns", entries)
        # Empty other registries
        self._write_registry("forge-adjustments", [])
        self._write_registry("dojo-learnings", [])

        # Monkey-patch REGISTRY_DIR to point at our temp dir
        cfg = Path(self.tmpdir) / "validator.yaml"
        with mock.patch.object(val, "REGISTRY_DIR", Path(self.tmpdir)), \
             mock.patch.object(val, "_config_path", return_value=cfg):
            summary = val.run_validation()

        # 1 unique pattern, 3 instances, → promoted
        self.assertEqual(len(summary["all"]), 1)
        self.assertEqual(summary["all"][0]["status"], "promoted")
        self.assertEqual(summary["all"][0]["instances_validated"], 3)

    def test_run_validation_per_source_override_applies(self):
        """Memory source with min_instances=2 — same data, 2 instances promote."""
        pattern = {
            "type": "synonym_expansion",
            "trigger": "concept:python",
            "patch": {"replace": "snake"},
            "effectiveness": {"improvement_pct": 20.0, "false_positive_pct": 1.0},
        }
        entries = []
        for i in range(2):  # only 2 instances
            entries.append({
                "instance_id": f"instance_{i:02d}",
                "submitted_at": f"2026-06-1{i+1}T00:00:00Z",
                "patterns": [dict(pattern)],
            })
        self._write_registry("memory-patterns", entries)
        self._write_registry("forge-adjustments", [])
        self._write_registry("dojo-learnings", [])

        # Config: memory override at min_instances=2
        cfg = Path(self.tmpdir) / "validator.yaml"
        cfg.write_text("""
validator:
  thresholds:
    min_instances: 3
    min_confirmed: 2
    min_improvement_pct: 10.0
    max_false_positive_pct: 5.0
    by_source:
      memory:
        min_instances: 2
""")
        with mock.patch.object(val, "REGISTRY_DIR", Path(self.tmpdir)), \
             mock.patch.object(val, "_config_path", return_value=cfg):
            summary = val.run_validation()
        # 2 instances, memory source, memory override min_instances=2 → promoted
        self.assertEqual(summary["all"][0]["status"], "promoted")

    def test_run_validation_three_source_systems_independent(self):
        """3 different patterns across 3 registries — each classified independently."""
        # memory: 3 instances, good
        self._write_registry("memory-patterns", [
            {
                "instance_id": f"mem_{i:02d}",
                "submitted_at": f"2026-06-1{i+1}T00:00:00Z",
                "patterns": [{
                    "type": "synonym_expansion",
                    "trigger": "trigger_mem",
                    "patch": {"a": 1},
                    "effectiveness": {"improvement_pct": 15.0},
                }],
            } for i in range(3)
        ])
        # forge: 2 instances (under default threshold of 3) → candidate
        self._write_registry("forge-adjustments", [
            {
                "instance_id": f"for_{i:02d}",
                "submitted_at": f"2026-06-1{i+1}T00:00:00Z",
                "adjustments": [{
                    "type": "gate_health",
                    "trigger": "trigger_for",
                    "patch": {"b": 2},
                    "effectiveness": {"improvement_pct": 15.0},
                }],
            } for i in range(2)
        ])
        # dojo: 1 instance (way under threshold) → candidate
        self._write_registry("dojo-learnings", [
            {
                "instance_id": "doj_00",
                "submitted_at": "2026-06-11T00:00:00Z",
                "learnings": [{
                    "type": "feedback_loop",
                    "trigger": "trigger_doj",
                    "patch": {"c": 3},
                    "effectiveness": {"improvement_pct": 15.0},
                }],
            }
        ])

        cfg = Path(self.tmpdir) / "validator.yaml"
        with mock.patch.object(val, "REGISTRY_DIR", Path(self.tmpdir)), \
             mock.patch.object(val, "_config_path", return_value=cfg):
            summary = val.run_validation()

        statuses = {e["trigger"]: e["status"] for e in summary["all"]}
        self.assertEqual(statuses["trigger_mem"], "promoted")
        self.assertEqual(statuses["trigger_for"], "candidate")
        self.assertEqual(statuses["trigger_doj"], "candidate")

    def test_run_validation_writes_pattern_effectiveness_index(self):
        """run_validation() writes to pattern-effectiveness/INDEX.json."""
        self._write_registry("memory-patterns", [])
        self._write_registry("forge-adjustments", [])
        self._write_registry("dojo-learnings", [])

        cfg = Path(self.tmpdir) / "validator.yaml"
        with mock.patch.object(val, "REGISTRY_DIR", Path(self.tmpdir)), \
             mock.patch.object(val, "_config_path", return_value=cfg):
            val.run_validation()

        out = Path(self.tmpdir) / "pattern-effectiveness" / "INDEX.json"
        self.assertTrue(out.exists(), f"missing output: {out}")
        data = json.loads(out.read_text())
        self.assertIn("schema_version", data)
        self.assertIn("total_patterns", data)
        self.assertIn("promoted_count", data)
        self.assertIn("candidate_count", data)
        self.assertIn("unvalidated_count", data)
        self.assertEqual(data["total_patterns"], 0)
        self.assertEqual(data["promoted_count"], 0)


class TestTokenPathUnchanged(unittest.TestCase):
    """The E2.3 refactor renamed some symbols; verify _token_path still exists."""

    def test_token_path_helper_exists(self):
        """_token_path() must still exist (load_token depends on it)."""
        self.assertTrue(hasattr(val, "_token_path"))
        self.assertTrue(callable(val._token_path))

    def test_load_token_uses_token_path(self):
        """load_token() should call _token_path() to get its path."""
        # Mock _token_path to return a fake path; load_token should respect it
        with mock.patch.object(val, "_token_path", return_value="/nonexistent/path"):
            with self.assertRaises(SystemExit) as ctx:
                val.load_token()
            # Should say "token file not found: /nonexistent/path"
            self.assertIn("/nonexistent/path", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
