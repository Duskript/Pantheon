"""RED tests for the default-off IchorContextEngine prototype.

The target is not another sidecar context-pack gate. These tests define the
minimum compressor-replacement surface from docs/specs/ichor-precision-context-engine.md:
lossless turn ingestion, bounded per-turn assembly, exact recall handles, no-op
cleanliness, and no LLM/API calls on the hot path.
"""
from __future__ import annotations

import importlib
import json
import sqlite3
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


def test_ichor_context_engine_unavailable_when_pack_builder_missing(monkeypatch) -> None:
    module = importlib.import_module("plugins.context_engine.ichor")
    monkeypatch.setattr(module, "build_context_pack", None)
    monkeypatch.setattr(module, "_needs_memory_context", None)
    engine = module.IchorContextEngine(fresh_tail_turns=4, max_pack_tokens=220)
    engine.on_session_start("session-missing-pack")

    assert engine.is_available() is False
    assembled = engine.compress(_long_messages("Build Ichor context engine."))
    joined = "\n".join(str(m.get("content", "")) for m in assembled)
    assert "status=\"unavailable\"" not in joined
    assert engine.get_status()["last_pack_metrics"]["db_reads"] == 0


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


def test_ichor_expand_caps_large_raw_turn_output() -> None:
    module = importlib.import_module("plugins.context_engine.ichor")
    engine = module.IchorContextEngine(fresh_tail_turns=2, max_expand_chars=1200)
    engine.on_session_start("session-cap")
    messages = _long_messages("Compare PR #138 tokens per turn.")
    engine.compress(messages, current_tokens=_estimate_tokens(messages))

    result = json.loads(engine.handle_tool_call(
        "ichor_expand",
        {"source_id": "raw_turns:session-cap:seq:1-40"},
    ))
    assert result["ok"] is True
    assert result["truncated"] is True
    assert result["omitted_chars"] > 0
    assert len(result["content"]) <= 1200


def test_ichor_context_engine_persists_raw_turns_when_store_configured(tmp_path: Path) -> None:
    module = importlib.import_module("plugins.context_engine.ichor")
    from lib.ichor.raw_turns import RawTurnStore

    store = RawTurnStore(tmp_path / "ichor.db")
    engine = module.IchorContextEngine(fresh_tail_turns=2, raw_turn_store=store)
    engine.on_session_start("session-persisted")
    messages = _long_messages("Persist these turns exactly.")

    engine.compress(messages, current_tokens=_estimate_tokens(messages))
    status = engine.get_status()

    assert status["raw_turn_store"]["configured"] is True
    assert status["raw_turn_store"]["last_result"]["inserted"] == len(messages)
    assert status["raw_turn_store"]["frontier"]["last_ingested_seq"] == len(messages) - 1
    persisted = store.fetch_range("session-persisted", 1, 3)
    assert persisted[0].content == "Original project goal: reduce context tokens."


def test_ichor_context_engine_expands_from_persisted_store_after_memory_loss(tmp_path: Path) -> None:
    module = importlib.import_module("plugins.context_engine.ichor")
    from lib.ichor.raw_turns import RawTurnStore

    store = RawTurnStore(tmp_path / "ichor.db")
    engine = module.IchorContextEngine(fresh_tail_turns=2, raw_turn_store=store)
    engine.on_session_start("session-store-expand")
    messages = _long_messages("Persist then expand from store.")
    engine.compress(messages, current_tokens=_estimate_tokens(messages))
    engine._raw_turns_by_session.clear()

    result = json.loads(engine.handle_tool_call(
        "ichor_expand",
        {"source_id": "raw_turns:session-store-expand:seq:1-3"},
    ))

    assert result["ok"] is True
    assert result["source"] == "persistent_store"
    assert "Original project goal" in result["content"]


def test_ichor_context_engine_default_has_no_persistent_store() -> None:
    module = importlib.import_module("plugins.context_engine.ichor")
    engine = module.IchorContextEngine(fresh_tail_turns=2)
    engine.on_session_start("session-default-no-store")
    messages = _long_messages("No live DB mutation by default.")

    engine.compress(messages, current_tokens=_estimate_tokens(messages))

    assert engine.get_status()["raw_turn_store"] == {"configured": False}


def test_ichor_context_engine_persistent_store_failure_is_prompt_quiet() -> None:
    module = importlib.import_module("plugins.context_engine.ichor")

    class BrokenStore:
        def ingest_messages(self, *_args, **_kwargs):
            raise sqlite3.OperationalError("read only")

        def get_frontier(self, _session_id):
            raise sqlite3.OperationalError("read only")

    engine = module.IchorContextEngine(fresh_tail_turns=2, raw_turn_store=BrokenStore())
    engine.on_session_start("session-broken-store")
    messages = _long_messages("ok")

    assembled = engine.compress(messages, current_tokens=_estimate_tokens(messages))
    joined = "\n".join(str(m.get("content", "")) for m in assembled)
    status = engine.get_status()["raw_turn_store"]

    assert "read only" not in joined
    assert status["configured"] is True
    assert status["last_result"] is None
    assert status["last_error"] == "OperationalError"
    result = json.loads(engine.handle_tool_call(
        "ichor_expand",
        {"source_id": "raw_turns:session-broken-store:seq:1-3"},
    ))
    assert result["ok"] is True
    assert result["source"] == "in_memory"
