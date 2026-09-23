"""Regression tests for the ichor-tick visibility fixes (2026-09-22).

The governing rule: a tick that cannot do its job must say so, and must not
exit 0. The unit stayed green through a 26-day L2 extraction outage, so these
tests guard the honesty gate, the declared no-op, and pool-first credential
resolution.

They exercise real production functions (`_degraded_steps`, `_step_extract`,
`_step_export`, `resolve_provider_credentials`) — not reconstructions of them.
"""
from __future__ import annotations

from lib import ichor_tick as t
from lib.ichor.llm import resolve_provider_credentials

OK_STEPS = {
    "gather": {"new_events": 1},
    "extract": {"events_processed": 5},
    "finalize": {"entities_flipped": 1},
    "analyze": {"forge_findings": 2},
}


# ── the honesty gate ───────────────────────────────────────────────────────

def test_gate_passes_when_core_steps_work():
    assert t._degraded_steps(OK_STEPS) == {}


def test_gate_flags_a_skipped_core_step():
    steps = dict(OK_STEPS)
    steps["extract"] = {"skipped": "no_credential_for_opencode-go", "status": "degraded"}
    assert t._degraded_steps(steps) == {"extract": "no_credential_for_opencode-go"}


def test_gate_flags_an_errored_core_step():
    steps = dict(OK_STEPS)
    steps["analyze"] = {"error": "boom"}
    assert t._degraded_steps(steps) == {"analyze": "boom"}


def test_gate_flags_a_core_step_that_did_not_run():
    steps = dict(OK_STEPS)
    del steps["finalize"]
    assert t._degraded_steps(steps) == {"finalize": "step did not run"}


def test_non_core_steps_cannot_fail_the_tick():
    """improve/brief/export/verify are declared no-ops or read-only."""
    steps = dict(OK_STEPS)
    steps["brief"] = {"status": "inert", "inert_reason": "0/11 delivered"}
    steps["export"] = {"status": "inert"}
    steps["improve"] = {"drift_applied": {}}
    steps["verify"] = {"benchmark": {"recall_at_5": 1.0}}
    assert t._degraded_steps(steps) == {}


def test_core_step_list_is_pinned():
    """A shrinking core list would silently disable the gate."""
    assert t._CORE_STEPS == ("gather", "extract", "finalize", "analyze")


# ── extract reports degradation instead of a quiet skip ─────────────────────

def test_extract_without_a_credential_is_degraded(monkeypatch):
    # _step_extract imports these inside the function, so patch the source
    # module — patching the tick's namespace would not intercept.
    monkeypatch.setattr("lib.ichor.llm.resolve_provider_credentials",
                        lambda name: ("", ""))
    monkeypatch.setattr("lib.ichor.llm._resolve_llm_provider",
                        lambda god: {"name": "opencode-go"})
    res = t._step_extract(dry_run=False)
    assert res["status"] == "degraded"
    assert res["degraded_reason"] == "no_credential_for_opencode-go"
    assert res["skipped"] == res["degraded_reason"], "back-compat key must survive"


def test_degraded_extract_helper_is_machine_readable():
    res = t._degraded_extract("no_api_key_for_X", 42)
    assert res["status"] == "degraded"
    assert res["degraded_reason"] == "no_api_key_for_X"
    assert res["cursor"] == 42


# ── export declares itself a no-op ─────────────────────────────────────────

def test_export_is_declared_inert():
    res = t._step_export(dry_run=False)
    assert res["status"] == "inert"
    assert res["submitted"] == 0
    assert "clawforge-pattern-export-forge.timer" in res["inert_reason"]


# ── pool-first credential resolution ───────────────────────────────────────

def test_pool_resolves_a_real_opencode_go_token():
    token, base_url = resolve_provider_credentials("opencode-go")
    assert len(token) > 10, "expected a real token from ~/.hermes/auth.json"
    assert base_url.endswith("/v1")


def test_pool_normalises_provider_name_spelling():
    a, _ = resolve_provider_credentials("opencode-go")
    b, _ = resolve_provider_credentials("opencode_go")
    assert a and a == b


def test_unknown_provider_resolves_to_empty():
    assert resolve_provider_credentials("no-such-provider-xyzzy") == ("", "")


# ── end-to-end: the CLI entry point actually returns non-zero ───────────────
#
# Unit tests on _degraded_steps prove the RULE. This proves the WIRING: that
# main() surfaces it as the process exit code, which is the only thing systemd
# sees. Without this, the gate could be correct and still never fire.

def _stub_steps(extract_result):
    def ok(**kw):
        return {"status": "ok", "dry_run": kw.get("dry_run", False)}
    return {
        "gather": lambda **kw: {"status": "ok", "new_events": 1},
        "extract": lambda **kw: extract_result,
        "finalize": lambda **kw: {"status": "ok", "entities_flipped": 1},
        "analyze": lambda **kw: {"status": "ok", "forge_findings": 1},
        "improve": lambda **kw: {"status": "ok", "drift_applied": {}},
        "brief": lambda **kw: {"status": "ok"},
        "export": lambda **kw: {"status": "inert", "submitted": 0,
                                "inert_reason": "no-op by design"},
        "verify": lambda **kw: {"status": "ok", "benchmark": {"recall_at_5": 1.0}},
    }


def test_main_exits_zero_when_core_steps_are_healthy(monkeypatch, capsys):
    monkeypatch.setattr(t, "_STEP_FUNCS", _stub_steps({"status": "ok", "events_processed": 5}))
    monkeypatch.setattr("sys.argv", ["ichor_tick"])
    rc = t.main()
    out = capsys.readouterr().out
    assert rc == 0, f"expected exit 0, got {rc}"
    assert "DEGRADED" not in out


def test_main_exits_non_zero_when_extract_is_degraded(monkeypatch, capsys):
    """The 26-day outage signature: extract cannot run, unit must NOT read healthy."""
    degraded_extract = {"skipped": "no_credential_for_opencode-go",
                        "status": "degraded",
                        "degraded_reason": "no_credential_for_opencode-go"}
    monkeypatch.setattr(t, "_STEP_FUNCS", _stub_steps(degraded_extract))
    monkeypatch.setattr("sys.argv", ["ichor_tick"])
    rc = t.main()
    out = capsys.readouterr().out
    assert rc == 1, f"expected exit 1 on a degraded core step, got {rc}"
    assert "DEGRADED" in out
    assert "no_credential_for_opencode-go" in out
    assert "INERT" in out, "declared no-op should be labelled, not silently zero"


# ── the credential is resolved at the CALL site, not the pre-flight check ───
#
# _step_extract's api_key local was only ever an emptiness check; the header is
# built by _call_llm. An earlier revision of this fix injected the credential
# into the tick and left _call_llm env-only, so a stripped env var still
# produced HTTP 401. These tests pin the real site.

def test_call_llm_uses_pool_credential_when_config_has_none(monkeypatch):
    import json as _json
    import urllib.request as _u
    from lib.ichor import llm as L

    captured = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return _json.dumps(
                {"choices": [{"message": {"content": "PONG"}}]}
            ).encode()

    def fake_urlopen(req, timeout=None):
        captured["auth"] = req.get_header("Authorization")
        captured["url"] = req.full_url
        return FakeResp()

    monkeypatch.setattr(_u, "urlopen", fake_urlopen)
    monkeypatch.setattr(L, "resolve_provider_credentials",
                        lambda name: ("pool-token-abcdefghij", "https://pool.example/v1"))

    cfg = {"name": "opencode-go", "api_key": "", "api": "https://cfg.example/v1",
           "default_model": "m1"}
    out = L._call_llm("hello", cfg)

    assert out == "PONG"
    assert captured["auth"] == "Bearer pool-token-abcdefghij", captured
    assert captured["url"].startswith("https://cfg.example/v1")


def test_call_llm_prefers_explicit_config_key_over_the_pool(monkeypatch):
    import json as _json
    import urllib.request as _u
    from lib.ichor import llm as L

    captured = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return _json.dumps({"choices": [{"message": {"content": "PONG"}}]}).encode()

    def fake_urlopen(req, timeout=None):
        captured["auth"] = req.get_header("Authorization")
        return FakeResp()

    def boom(name):
        raise AssertionError("pool must not be consulted when config supplies a key")

    monkeypatch.setattr(_u, "urlopen", fake_urlopen)
    monkeypatch.setattr(L, "resolve_provider_credentials", boom)

    cfg = {"name": "p", "api_key": "explicit-key-xyz", "api": "https://x/v1",
           "default_model": "m"}
    L._call_llm("hi", cfg)
    assert captured["auth"] == "Bearer explicit-key-xyz"


def test_extract_degrades_on_a_mid_loop_failure(monkeypatch):
    """HTTP 401 mid-batch must not print a clean summary and exit 0."""
    monkeypatch.setattr("lib.ichor.llm._resolve_llm_provider",
                        lambda god: {"name": "opencode-go", "api": "https://x/v1",
                                     "default_model": "m"})
    monkeypatch.setattr("lib.ichor.llm.resolve_provider_credentials",
                        lambda name: ("k" * 20, ""))
    monkeypatch.setattr("lib.ichor.llm._load_provider_config",
                        lambda name: {"name": name, "api": "https://x/v1",
                                      "default_model": "m"})

    def boom(*a, **kw):
        raise RuntimeError("HTTP Error 401: Unauthorized")

    monkeypatch.setattr("lib.ichor.entities.extract_incremental", boom)

    res = t._step_extract(dry_run=False)
    assert res["status"] == "degraded", res
    assert "401" in res["degraded_reason"]
    assert res["events_processed"] == 0
    # and the gate must turn that into a non-zero exit
    assert "extract" in t._degraded_steps({
        "gather": {"status": "ok"}, "extract": res,
        "finalize": {"status": "ok"}, "analyze": {"status": "ok"}})


def test_aborted_early_is_not_a_success(monkeypatch, capsys):
    """A partial tick must not exit 0 just because the core steps that ran were ok."""
    import lib.ichor_tick as tick

    stubs = _stub_steps({"status": "ok", "events_processed": 5})

    def fake_run_tick(dry_run=True):
        return {"version": "1.0.0", "started_at": "x", "duration_seconds": 30.4,
                "dry_run": dry_run, "aborted_early": True,
                "steps": {k: f(dry_run=dry_run) for k, f in stubs.items()}}

    monkeypatch.setattr(tick, "run_tick", fake_run_tick)
    monkeypatch.setattr("sys.argv", ["ichor_tick"])
    rc = tick.main()
    assert rc == 1, f"aborted tick returned {rc}; a partial run is not a success"


def test_manual_default_time_cap_is_lower_than_the_unit_cap():
    """Guards the mismatch that makes aborting reachable in practice."""
    assert t.MAX_TICK_SECONDS <= 300.0
