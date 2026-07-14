"""Pantheon Core — the Phase B Hermes plugin.

This plugin registers the full lifecycle hook surface required by the
unified-upgrade plan. All hooks are no-op by default. Comparison mode writes
JSONL audit lines under ``$HERMES_HOME/hooks/pantheon-core/comparison/`` so
we can validate behavior without changing the agent loop.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

try:  # optional at import-time in some minimal environments
    import yaml
except Exception:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

repo_root = Path(__file__).resolve().parents[3]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

PLUGIN_NAME = "pantheon-core"
PLUGIN_VERSION = "1.0.0"

_CONFIG_CACHE: dict[str, Any] = {"key": None, "value": {}}
_GATES: Any = None
_READ_CACHE: Any = None


# ---------------------------------------------------------------------------
# Paths / config
# ---------------------------------------------------------------------------


def _hermes_home() -> Path:
    val = (os.environ.get("HERMES_HOME") or "").strip()
    if val:
        return Path(val).expanduser()
    return Path.home() / ".hermes"


def _config_path() -> Path:
    return _hermes_home() / "config.yaml"


def _load_config() -> dict[str, Any]:
    path = _config_path()
    try:
        stat = path.stat()
    except FileNotFoundError:
        _CONFIG_CACHE["key"] = (str(path), None)
        _CONFIG_CACHE["value"] = {}
        return {}
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if _CONFIG_CACHE.get("key") == key:
        return copy.deepcopy(_CONFIG_CACHE["value"])
    if yaml is None:
        cfg: dict[str, Any] = {}
    else:
        try:
            cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(cfg, dict):
                cfg = {}
        except Exception as exc:
            logger.debug("pantheon-core: config load failed: %s", exc)
            cfg = {}
    _CONFIG_CACHE["key"] = key
    _CONFIG_CACHE["value"] = cfg
    return copy.deepcopy(cfg)


def _cfg_get(*path: str, default: Any = None) -> Any:
    cur: Any = _load_config()
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur if cur is not None else default


def _flag(*path: str, default: bool = False) -> bool:
    value = _cfg_get(*path, default=default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _comparison_mode() -> bool:
    return _flag("hooks", "comparison_mode")


def _memory_injection_enabled() -> bool:
    return _flag("hooks", "memory_injection")


def _gates_enabled() -> bool:
    return _flag("hooks", "gates")


def _inbox_enabled() -> bool:
    return _flag("hooks", "inbox_check")


def _session_finalize_enabled() -> bool:
    return _flag("hooks", "session_finalize")


def _outcome_capture_enabled() -> bool:
    return _flag("hooks", "outcome_capture")


def _reconcile_memory_enabled() -> bool:
    return _flag("hooks", "reconcile_memory")


def _compact_enabled() -> bool:
    return _flag("hooks", "compaction")


def _comparison_dir() -> Path:
    path = _hermes_home() / "hooks" / PLUGIN_NAME / "comparison"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _episodes_dir() -> Path:
    path = _hermes_home() / "hooks" / PLUGIN_NAME / "episodes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _digests_dir() -> Path:
    path = _hermes_home() / "hooks" / PLUGIN_NAME / "digests"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _json_line(payload: dict[str, Any]) -> str:
    return json.dumps(_jsonable(payload), sort_keys=True, ensure_ascii=False, default=str)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(_json_line(payload))
        fh.write("\n")


def _comparison_log(hook: str, payload: dict[str, Any]) -> None:
    _append_jsonl(_comparison_dir() / f"{hook}.jsonl", payload)


def _summarize_text(text: str, limit: int = 600) -> str:
    clean = " ".join(str(text).split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1] + "…"


def _resolve_user_message(kwargs: dict[str, Any]) -> str:
    for key in ("user_message", "message", "prompt", "input", "content"):
        val = kwargs.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    history = kwargs.get("conversation_history") or kwargs.get("messages") or []
    if isinstance(history, list) and history:
        bits: list[str] = []
        for item in history[-6:]:
            if isinstance(item, dict):
                role = str(item.get("role", "")).strip()
                content = str(item.get("content", "")).strip()
                if content:
                    bits.append(f"{role}: {content}" if role else content)
        return "\n".join(bits)
    return ""


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Ichor-backed helpers
# ---------------------------------------------------------------------------


def _memory_trait():
    from lib.ichor_hybrid import MemoryTrait  # type: ignore[import-untyped]

    return MemoryTrait()


def _gate_pipeline():
    global _GATES, _READ_CACHE
    if _GATES is not None:
        return _GATES

    from lib.ichor_gates import (  # type: ignore[import-untyped]
        GatePipeline,
        LogicGate,
        PhaseDetectionGate,
        ReadCache,
        StateGate,
    )

    pipeline = GatePipeline()
    _READ_CACHE = pipeline.read_cache or ReadCache()
    pipeline.read_cache = _READ_CACHE
    pipeline.register(StateGate(_READ_CACHE))
    pipeline.register(LogicGate())
    pipeline.register(PhaseDetectionGate())
    _GATES = pipeline
    return _GATES


def _note_comparison(hook: str, payload: dict[str, Any]) -> None:
    if _comparison_mode():
        _comparison_log(hook, payload)


def _evaluate_pre_tool_call(tool_name: str, args: Any, context: dict[str, Any]):
    _gate_pipeline()
    from lib.ichor_gates import LogicGate, PhaseDetectionGate, StateGate  # type: ignore[import-untyped]

    gates = [StateGate(_READ_CACHE), LogicGate(), PhaseDetectionGate()]
    for gate in gates:
        result = gate.pre_call(tool_name, args or {}, context)
        if result is not None:
            return result
    return None


def _evaluate_post_tool_call(tool_name: str, args: Any, result: Any, context: dict[str, Any]):
    _gate_pipeline()
    from lib.ichor_gates import LogicGate  # type: ignore[import-untyped]

    gate = LogicGate()
    return gate.post_call(tool_name, args or {}, result, context)


def _build_memory_context(user_message: str, session_id: str = "", god_name: str = "") -> dict[str, Any]:
    trait = _memory_trait()
    active_god = god_name or str(_cfg_get("agent", "default_god", default="") or "")
    result = trait.retrieve(
        query=user_message,
        limit=5,
        backends="fts5,vector,graph,events,reference",
        active_god=active_god,
    )
    results = list(result.get("results") or []) if isinstance(result, dict) else []
    lines: list[str] = []
    for item in results[:5]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("subject") or item.get("name") or "memory")
        snippet = str(item.get("snippet") or item.get("content") or item.get("text") or item.get("raw_text") or "")
        score = item.get("score")
        prefix = f"- {title}"
        if score is not None:
            prefix += f" ({score})"
        if snippet:
            prefix += f": {_summarize_text(snippet, 220)}"
        lines.append(prefix)
    context = "\n".join(lines).strip()
    payload = {
        "hook": "pre_llm_call",
        "session_id": session_id,
        "user_message": _summarize_text(user_message, 300),
        "result_count": len(results),
        "context": context,
        "would_inject": bool(context),
        "comparison_mode": _comparison_mode(),
    }
    _note_comparison("pre_llm_call", payload)
    return {"context": context, "source": "pantheon-core", "result_count": len(results)}


def _accordion_expand_stub(**kwargs: Any) -> Optional[dict[str, Any]]:
    if not _flag("hooks", "accordion_expand"):
        return None
    payload = {
        "hook": "accordion_expand",
        "session_id": kwargs.get("session_id", ""),
        "comparison_mode": _comparison_mode(),
        "would_expand": True,
    }
    _note_comparison("accordion_expand", payload)
    return None


def _reconcile_post_tool_memory(tool_name: str, args: Any, result: Any, context: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not _reconcile_memory_enabled() and not _comparison_mode():
        return None
    try:
        from lib.ichor_hybrid import detect_contradiction  # type: ignore[import-untyped]
    except Exception as exc:
        logger.debug("pantheon-core: reconcile import failed: %s", exc)
        return None

    result_text = _summarize_text(json.dumps(_jsonable(result), ensure_ascii=False, default=str), 1200).strip()
    if not result_text:
        return None

    arg_hint = ""
    if isinstance(args, dict):
        for key in ("query", "subject", "name", "title", "text"):
            value = args.get(key)
            if value:
                arg_hint = str(value)
                break

    query = " ".join(part for part in [tool_name, arg_hint, context.get("user_message", ""), result_text] if part).strip()
    active_god = str(context.get("god_name") or _cfg_get("agent", "default_god", default="") or "")
    trait = _memory_trait()
    retrieved = trait.retrieve(
        query=query,
        limit=5,
        backends="fts5,vector,events,reference",
        active_god=active_god or None,
    )
    results = list(retrieved.get("results") or []) if isinstance(retrieved, dict) else []
    for candidate in results:
        if not isinstance(candidate, dict):
            continue
        old_text = str(
            candidate.get("snippet")
            or candidate.get("content")
            or candidate.get("raw_text")
            or candidate.get("text")
            or candidate.get("title")
            or ""
        ).strip()
        if not old_text:
            continue
        if detect_contradiction(old_text, result_text):
            session_id = str(context.get("session_id") or "")
            key = f"{session_id or 'session'}:{tool_name}:reconcile"
            content = (
                f"Tool {tool_name} result contradicts memory. "
                f"new={result_text} | prior={old_text}"
            )
            store_result = trait.store(
                namespace=PLUGIN_NAME,
                key=key,
                content=content,
                category="correction",
                session_id=session_id,
                god_name=active_god,
            )
            payload = {
                "hook": "post_tool_call_reconcile",
                "tool_name": tool_name,
                "session_id": session_id,
                "god_name": active_god,
                "query": query,
                "candidate": {
                    "title": candidate.get("title", ""),
                    "snippet": old_text,
                },
                "store_result": store_result,
                "comparison_mode": _comparison_mode(),
            }
            _note_comparison("post_tool_call_reconcile", payload)
            return payload
    return None


def _accordion_context(user_message: str, session_id: str = "", platform: str = "", model: str = "") -> Optional[dict[str, Any]]:
    engine_name = str(_cfg_get("context", "engine", default="compressor") or "compressor")
    if engine_name != "accordion":
        return None
    try:
        from plugins.context_engine import load_context_engine
    except Exception as exc:
        logger.debug("accordion hook load failed: %s", exc)
        return None

    engine = load_context_engine("accordion")
    if engine is None:
        return None
    try:
        engine.on_session_start(
            session_id or "",
            hermes_home=str(_hermes_home()),
            platform=platform,
            model=model,
        )
    except Exception as exc:
        logger.debug("accordion on_session_start failed: %s", exc)
    try:
        result = engine.expand_for_message(user_message)
    except Exception as exc:
        logger.debug("accordion expand failed: %s", exc)
        result = None
    if not isinstance(result, dict):
        return None
    context = str(result.get("context") or "").strip()
    if not context:
        return None
    payload = {
        "hook": "pre_llm_call",
        "session_id": session_id,
        "context": _summarize_text(context, 300),
        "source": "accordion",
        "comparison_mode": _comparison_mode(),
    }
    _note_comparison("pre_llm_call", payload)
    return {"context": context, "source": "accordion", "fold_id": result.get("fold_id")}


def _check_inbox(session_id: str = "", platform: str = "", **kwargs: Any) -> dict[str, Any]:
    roots = [
        _hermes_home() / "inbox",
        _hermes_home() / "messages" / "inbox",
        _hermes_home() / "notifications" / "inbox",
    ]
    hits: list[dict[str, Any]] = []
    total = 0
    for root in roots:
        if not root.exists():
            continue
        count = 0
        for child in root.rglob("*"):
            if child.is_file():
                count += 1
        if count:
            total += count
            hits.append({"path": str(root), "count": count})
    payload = {
        "hook": "on_session_start",
        "session_id": session_id,
        "platform": platform,
        "inbox_count": total,
        "roots": hits,
        "comparison_mode": _comparison_mode(),
    }
    _note_comparison("on_session_start", payload)
    return payload


def _write_digest(session_id: str = "", model: str = "", platform: str = "", completed: bool = False, interrupted: bool = False, **kwargs: Any) -> dict[str, Any]:
    digest = {
        "timestamp": _now(),
        "plugin": PLUGIN_NAME,
        "session_id": session_id,
        "model": model,
        "platform": platform,
        "completed": bool(completed),
        "interrupted": bool(interrupted),
        "summary": _summarize_text(str(kwargs.get("summary") or kwargs.get("final_message") or kwargs.get("digest") or ""), 1000),
    }
    path = _digests_dir() / f"{session_id or 'session'}.json"
    path.write_text(_json_line(digest) + "\n", encoding="utf-8")
    payload = {"hook": "on_session_finalize", "digest_path": str(path), "digest": digest, "comparison_mode": _comparison_mode()}
    _note_comparison("on_session_finalize", payload)
    return payload


def _store_episode(tool_name: str, args: Any, result: Any, **kwargs: Any) -> dict[str, Any]:
    payload = {
        "timestamp": _now(),
        "hook": "post_tool_call",
        "tool_name": tool_name,
        "session_id": kwargs.get("session_id", ""),
        "model": kwargs.get("model", ""),
        "args": _jsonable(args),
        "result": _jsonable(result),
    }
    _append_jsonl(_episodes_dir() / "episodes.jsonl", payload)
    _note_comparison("post_tool_call", {**payload, "stored": True})
    return payload


# ---------------------------------------------------------------------------
# Lifecycle hooks
# ---------------------------------------------------------------------------


def _on_pre_llm_call(**kwargs: Any) -> Optional[dict[str, Any]]:
    active_engine = str(_cfg_get("context", "engine", default="compressor") or "compressor")
    if not _memory_injection_enabled() and not _comparison_mode() and not _flag("hooks", "accordion_expand") and active_engine != "accordion":
        return None

    user_message = _resolve_user_message(kwargs)
    session_id = str(kwargs.get("session_id", "") or "")
    platform = str(kwargs.get("platform", "") or "")
    model = str(kwargs.get("model", "") or "")
    god_name = str(kwargs.get("god_name", "") or kwargs.get("plugin_name", "") or "")

    context_parts: list[str] = []
    source_parts: list[str] = []

    if _memory_injection_enabled():
        memory_payload = _build_memory_context(user_message, session_id=session_id, god_name=god_name)
        memory_context = str(memory_payload.get("context", "") or "").strip()
        if memory_context:
            context_parts.append(memory_context)
            source_parts.append("pantheon-core")

    accordion_payload = _accordion_context(user_message, session_id=session_id, platform=platform, model=model)
    if accordion_payload:
        accordion_context = str(accordion_payload.get("context", "") or "").strip()
        if accordion_context:
            context_parts.append(accordion_context)
            source_parts.append("accordion")

    if not context_parts:
        if _comparison_mode() or _flag("hooks", "accordion_expand"):
            _accordion_expand_stub(**kwargs)
        return None

    if _flag("hooks", "accordion_expand"):
        _accordion_expand_stub(**kwargs)

    return {
        "context": "\n\n".join(context_parts).strip(),
        "source": ",".join(source_parts) if source_parts else PLUGIN_NAME,
    }


def _on_pre_tool_call(tool_name: str = "", args: Any = None, **kwargs: Any) -> Optional[dict[str, str]]:
    if not _gates_enabled() and not _comparison_mode():
        return None
    context = {
        "user_message": _resolve_user_message(kwargs),
        "session_id": kwargs.get("session_id", ""),
        "god_name": kwargs.get("god_name", ""),
    }
    result = _evaluate_pre_tool_call(tool_name, args or {}, context)
    payload = {
        "hook": "pre_tool_call",
        "tool_name": tool_name,
        "args": _jsonable(args or {}),
        "comparison_mode": _comparison_mode(),
        "enabled": _gates_enabled(),
        "result": None if result is None else {
            "gate_name": result.gate_name,
            "passed": result.passed,
            "intervention": result.intervention,
            "message": result.message,
            "recovery_hint": result.recovery_hint,
        },
    }
    _note_comparison("pre_tool_call", payload)
    if result is None or result.passed or not _gates_enabled():
        return None
    return {"action": "block", "message": result.message or result.recovery_hint or "Blocked by Pantheon Core"}


def _on_post_tool_call(tool_name: str = "", args: Any = None, result: Any = None, **kwargs: Any) -> None:
    if not _outcome_capture_enabled() and not _comparison_mode() and not _gates_enabled() and not _reconcile_memory_enabled():
        return None
    context = {
        "session_id": kwargs.get("session_id", ""),
        "god_name": kwargs.get("god_name", ""),
        "user_message": _resolve_user_message(kwargs),
    }
    gate_results = []
    if _outcome_capture_enabled() or _gates_enabled() or _comparison_mode():
        gate_results = _evaluate_post_tool_call(tool_name, args or {}, result, context) or []
    gate_payloads = []
    if isinstance(gate_results, list):
        for gr in gate_results:
            if getattr(gr, 'passed', True) is False:
                gate_payloads.append({
                    "gate_name": getattr(gr, 'gate_name', ''),
                    "passed": getattr(gr, 'passed', True),
                    "intervention": getattr(gr, 'intervention', False),
                    "message": getattr(gr, 'message', ''),
                    "recovery_hint": getattr(gr, 'recovery_hint', ''),
                })
    elif gate_results is not None and hasattr(gate_results, 'gate_name'):
        gate_payloads.append({
            "gate_name": getattr(gate_results, 'gate_name', ''),
            "passed": getattr(gate_results, 'passed', True),
            "intervention": getattr(gate_results, 'intervention', False),
            "message": getattr(gate_results, 'message', ''),
            "recovery_hint": getattr(gate_results, 'recovery_hint', ''),
        })
    payload = {
        "hook": "post_tool_call",
        "tool_name": tool_name,
        "args": _jsonable(args or {}),
        "result": _summarize_text(json.dumps(_jsonable(result), ensure_ascii=False, default=str), 1000),
        "comparison_mode": _comparison_mode(),
        "enabled": _outcome_capture_enabled(),
        "gates": gate_payloads,
    }
    _note_comparison("post_tool_call", payload)
    if _outcome_capture_enabled():
        _store_episode(tool_name, args or {}, result, **kwargs)
    _reconcile_post_tool_memory(tool_name, args or {}, result, context)


def _on_session_start(**kwargs: Any) -> Optional[dict[str, Any]]:
    payload = _check_inbox(
        session_id=str(kwargs.get("session_id", "") or ""),
        platform=str(kwargs.get("platform", "") or ""),
    )
    if _inbox_enabled() or _comparison_mode():
        return {"context": f"{payload['inbox_count']} inbox item(s) pending"}
    return None


def _on_session_finalize(**kwargs: Any) -> None:
    if not _session_finalize_enabled() and not _comparison_mode() and not _compact_enabled():
        return None
    payload = {
        "timestamp": _now(),
        "plugin": PLUGIN_NAME,
        "session_id": kwargs.get("session_id", ""),
        "model": kwargs.get("model", ""),
        "platform": kwargs.get("platform", ""),
        "completed": bool(kwargs.get("completed", False)),
        "interrupted": bool(kwargs.get("interrupted", False)),
        "summary": _summarize_text(str(kwargs.get("summary") or kwargs.get("final_message") or kwargs.get("digest") or ""), 1000),
    }
    if _comparison_mode():
        _note_comparison("on_session_finalize", {"hook": "on_session_finalize", "comparison_only": True, **payload})
        return None
    if _session_finalize_enabled():
        _write_digest(
            session_id=str(kwargs.get("session_id", "") or ""),
            model=str(kwargs.get("model", "") or ""),
            platform=str(kwargs.get("platform", "") or ""),
            completed=bool(kwargs.get("completed", False)),
            interrupted=bool(kwargs.get("interrupted", False)),
            summary=kwargs.get("summary") or kwargs.get("final_message") or kwargs.get("digest") or "",
        )
    if _compact_enabled():
        compact = {
            "timestamp": _now(),
            "session_id": kwargs.get("session_id", ""),
            "model": kwargs.get("model", ""),
            "platform": kwargs.get("platform", ""),
            "completed": bool(kwargs.get("completed", False)),
            "interrupted": bool(kwargs.get("interrupted", False)),
            "note": "compact_session placeholder for Phase C",
        }
        _append_jsonl(_hermes_home() / "hooks" / PLUGIN_NAME / "compaction.jsonl", compact)


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------


def register(ctx) -> None:
    """Register all Pantheon lifecycle hooks."""
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    ctx.register_hook("on_session_start", _on_session_start)
    ctx.register_hook("on_session_finalize", _on_session_finalize)
    logger.info("%s v%s registered 5 hooks", PLUGIN_NAME, PLUGIN_VERSION)
