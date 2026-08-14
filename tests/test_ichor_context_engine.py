"""RED tests for the default-off IchorContextEngine prototype.

The target is not another sidecar context-pack gate. These tests define the
minimum compressor-replacement surface from docs/specs/ichor-precision-context-engine.md:
lossless turn ingestion, bounded per-turn assembly, exact recall handles, no-op
cleanliness, and no LLM/API calls on the hot path.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERMES_AGENT = ROOT / "hermes-agent"
for candidate in (str(ROOT), str(HERMES_AGENT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)
# Pantheon also has a top-level `plugins` package. These tests target Hermes'
# context-engine plugin loader, so evict any already-imported sibling package
# and force the hermes-agent path to win.
for loaded in list(sys.modules):
    if loaded == "plugins" or loaded.startswith("plugins.context_engine"):
        del sys.modules[loaded]
if str(HERMES_AGENT) in sys.path:
    sys.path.remove(str(HERMES_AGENT))
sys.path.insert(0, str(HERMES_AGENT))


def _long_messages(current_user: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [
        {"role": "system", "content": "You are Hermes."},
        {"role": "user", "content": "Original project goal: reduce context tokens."},
        {"role": "assistant", "content": "Acknowledged."},
    ]
    for idx in range(24):
        messages.append({
            "role": "user",
            "content": (
                f"Stale middle user turn {idx}: old canary mechanics, gateway routing, "
                "token rotation, and verbose logs that should not be pasted each turn. " * 8
            ),
        })
        messages.append({
            "role": "assistant",
            "content": (
                f"Stale middle assistant turn {idx}: implementation detail dump. "
                "This text exists to make the transcript large and should become recallable, "
                "not live prompt cargo. " * 8
            ),
        })
    messages.extend([
        {"role": "user", "content": "Fresh tail: PR #138 benchmark is ready."},
        {"role": "assistant", "content": "Fresh tail: benchmark is source-backed and default-off."},
        {"role": "user", "content": current_user},
    ])
    return messages


def _estimate_tokens(messages: list[dict[str, str]]) -> int:
    return sum(max(1, (len(str(m.get("content", ""))) + 3) // 4) for m in messages)


def test_ichor_context_engine_plugin_loads_default_off() -> None:
    from plugins.context_engine import discover_context_engines, load_context_engine

    discovered = {name for name, _description, available in discover_context_engines() if available}
    assert "ichor" in discovered

    engine = load_context_engine("ichor")
    assert engine is not None
    assert engine.name == "ichor"
    assert engine.get_status()["mode"] == "default_off_plugin"


def test_ichor_context_engine_assembles_bounded_relevant_context(monkeypatch) -> None:
    module = importlib.import_module("plugins.context_engine.ichor")
    engine = module.IchorContextEngine(fresh_tail_turns=4, max_pack_tokens=220)
    engine.on_session_start("session-1", platform="discord")

    def fake_pack(**kwargs):
        assert kwargs["query"] == "Build the default-off IchorContextEngine prototype."
        return {
            "injectable_context": "<ichor-context>source-backed engine target</ichor-context>",
            "source_links": [
                {"title": "precision context design", "source_path": "docs/specs/ichor-precision-context-engine.md", "source_id": "target"}
            ],
            "metrics": {"llm_calls": 0, "api_calls": 0, "db_reads": 1, "db_writes": 0, "tokens_estimated": 13},
            "coverage": {"returned": 1, "warnings": []},
        }

    monkeypatch.setattr(engine, "_build_context_pack", fake_pack)
    original = _long_messages("Build the default-off IchorContextEngine prototype.")

    assembled = engine.compress(original, current_tokens=_estimate_tokens(original))
    joined = "\n".join(str(m.get("content", "")) for m in assembled)

    assert _estimate_tokens(assembled) < _estimate_tokens(original) * 0.35
    assert assembled[0] == original[0]
    assert "source-backed engine target" in joined
    assert "Available Ichor expansions" in joined
    assert "raw_turns:session-1" in joined
    assert "Fresh tail: PR #138 benchmark is ready." in joined
    assert "Stale middle user turn 3" not in joined
    assert engine.get_status()["last_pack_metrics"]["llm_calls"] == 0
    assert engine.get_status()["last_pack_metrics"]["api_calls"] == 0


def test_ichor_context_engine_noop_turn_injects_no_pack_and_reads_nothing(monkeypatch) -> None:
    module = importlib.import_module("plugins.context_engine.ichor")
    engine = module.IchorContextEngine(fresh_tail_turns=4, max_pack_tokens=220)
    engine.on_session_start("session-noop")

    def forbidden_pack(**_kwargs):
        raise AssertionError("no-op turn should not read/build Ichor context")

    monkeypatch.setattr(engine, "_build_context_pack", forbidden_pack)
    original = _long_messages("ok")

    assembled = engine.compress(original, current_tokens=_estimate_tokens(original))
    joined = "\n".join(str(m.get("content", "")) for m in assembled)

    assert "<ichor-context" not in joined
    assert "Available Ichor expansions" in joined
    assert engine.get_status()["last_pack_metrics"] == {
        "llm_calls": 0,
        "api_calls": 0,
        "db_reads": 0,
        "db_writes": 0,
        "tokens_estimated": 0,
    }


def test_ichor_context_engine_tools_expand_stored_raw_turns() -> None:
    module = importlib.import_module("plugins.context_engine.ichor")
    engine = module.IchorContextEngine(fresh_tail_turns=2)
    engine.on_session_start("session-tools")
    messages = _long_messages("Compare PR #138 tokens per turn.")
    engine.compress(messages, current_tokens=_estimate_tokens(messages))

    schemas = {schema["name"] for schema in engine.get_tool_schemas()}
    assert {"ichor_status", "ichor_expand"}.issubset(schemas)

    result = json.loads(engine.handle_tool_call(
        "ichor_expand",
        {"source_id": "raw_turns:session-tools:seq:1-3"},
    ))
    assert result["ok"] is True
    assert "Original project goal" in result["content"]
