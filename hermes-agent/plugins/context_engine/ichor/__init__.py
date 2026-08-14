"""Default-off Ichor precision context engine prototype.

This engine implements the first bounded per-turn selector shape from
``docs/specs/ichor-precision-context-engine.md``. It is only selected when
``context.engine: ichor`` is configured; the default remains the built-in
compressor.

By default the prototype keeps raw-turn ingestion in process memory. When an
explicit RawTurnStore is provided by tests or future default-off wiring, it also
persists exact turns to Ichor SQLite. Either way it avoids live profile mutation,
re-enabling hermes-lcm, rotating sessions, or calling an LLM/API in the hot path.
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from agent.context_engine import ContextEngine

try:
    from lib.ichor.context_pack import build_context_pack, _needs_memory_context
except Exception:  # pragma: no cover - import failure is handled at runtime
    build_context_pack = None
    _needs_memory_context = None

try:
    from lib.ichor.raw_turns import RawTurnStore
except Exception:  # pragma: no cover - optional persistence stays default-off
    RawTurnStore = None


_DEFAULT_METRICS = {
    "llm_calls": 0,
    "api_calls": 0,
    "db_reads": 0,
    "db_writes": 0,
    "tokens_estimated": 0,
}


def _estimate_text_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4) if text else 0


def _estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    return sum(_estimate_text_tokens(str(message.get("content", ""))) for message in messages)


def _latest_user_message(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content", ""))
    return ""


def _safe_message_copy(message: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(message)


class IchorContextEngine(ContextEngine):
    """Bounded per-turn context selector backed by Ichor context packs.

    This v0 is a default-off prototype. It validates the ContextEngine seam and
    per-turn economy benchmark before any fleet/profile promotion.
    """

    @property
    def name(self) -> str:
        return "ichor"

    def __init__(
        self,
        *,
        fresh_tail_turns: int = 8,
        max_pack_tokens: int = 900,
        max_pack_items: int = 8,
        max_pack_ms: int = 120,
        max_expand_chars: int = 12_000,
        raw_turn_store: Any = None,
        context_length: int = 128_000,
        threshold_percent: float = 0.50,
    ) -> None:
        self.fresh_tail_turns = max(1, int(fresh_tail_turns))
        self.max_pack_tokens = max(1, int(max_pack_tokens))
        self.max_pack_items = max(1, int(max_pack_items))
        self.max_pack_ms = max(1, int(max_pack_ms))
        self.max_expand_chars = max(1_000, int(max_expand_chars))
        self.threshold_percent = threshold_percent
        self.context_length = int(context_length)
        self.threshold_tokens = int(self.context_length * self.threshold_percent)
        self.compression_count = 0
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.last_total_tokens = 0
        self.session_id = ""
        self.platform = ""
        self.raw_turn_store = raw_turn_store
        self._raw_turns_by_session: dict[str, list[dict[str, Any]]] = {}
        self._raw_turn_store_result: dict[str, Any] | None = None
        self._raw_turn_store_error = ""
        self._last_selected_source_links: list[dict[str, str]] = []
        self._last_pack_metrics: dict[str, int] = dict(_DEFAULT_METRICS)
        self._last_assembled_tokens = 0
        self._last_original_tokens = 0
        self._last_injected = False

    def is_available(self) -> bool:
        return build_context_pack is not None

    def update_model(
        self,
        model: str,
        context_length: int,
        base_url: str = "",
        api_key: str = "",
        provider: str = "",
        api_mode: str = "",
    ) -> None:
        del model, base_url, api_key, provider, api_mode
        if context_length is not None:
            self.context_length = int(context_length)
        self.threshold_tokens = int(self.context_length * self.threshold_percent)

    def update_from_response(self, usage: dict[str, Any]) -> None:
        self.last_prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        self.last_completion_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        self.last_total_tokens = int(usage.get("total_tokens") or (self.last_prompt_tokens + self.last_completion_tokens))

    def should_compress(self, prompt_tokens: int = None) -> bool:
        tokens = self.last_prompt_tokens if prompt_tokens is None else int(prompt_tokens or 0)
        return tokens >= self.threshold_tokens

    def should_compress_preflight(self, messages: list[dict[str, Any]]) -> bool:
        return self.has_content_to_compress(messages)

    def has_content_to_compress(self, messages: list[dict[str, Any]]) -> bool:
        non_system = [m for m in messages if m.get("role") != "system"]
        return len(non_system) > self.fresh_tail_turns

    def on_session_start(self, session_id: str, **kwargs: Any) -> None:
        self.session_id = session_id or self.session_id or "ichor-session"
        self.platform = str(kwargs.get("platform") or self.platform or "")
        self._raw_turns_by_session.setdefault(self.session_id, [])

    def on_session_reset(self) -> None:
        super().on_session_reset()
        self._last_selected_source_links = []
        self._last_pack_metrics = dict(_DEFAULT_METRICS)
        self._last_assembled_tokens = 0
        self._last_original_tokens = 0
        self._last_injected = False

    def compress(
        self,
        messages: list[dict[str, Any]],
        current_tokens: int = None,
        focus_topic: str = None,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        # `force` is accepted for ContextCompressor compatibility. Ichor v0 is
        # always a bounded selector: it drops pre-tail prompt cargo from the
        # returned live message list while retaining exact raw turns for
        # expansion handles. It does not mean lossy summarization.
        del force
        session_id = self.session_id or "ichor-session"
        self._ingest_raw_turns(session_id, messages)
        query = focus_topic or _latest_user_message(messages)
        systems = [_safe_message_copy(m) for m in messages if m.get("role") == "system"]
        non_system = [_safe_message_copy(m) for m in messages if m.get("role") != "system"]
        fresh_tail = non_system[-self.fresh_tail_turns:]

        context_message = self._context_message_for(query)
        handles_message = self._handles_message_for(session_id, messages, fresh_tail)

        assembled: list[dict[str, Any]] = []
        assembled.extend(systems)
        if context_message is not None:
            assembled.append(context_message)
        if handles_message is not None:
            assembled.append(handles_message)
        assembled.extend(fresh_tail)

        self.compression_count += 1
        self._last_original_tokens = int(current_tokens or _estimate_messages_tokens(messages))
        self._last_assembled_tokens = _estimate_messages_tokens(assembled)
        self.last_prompt_tokens = self._last_assembled_tokens
        return assembled

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "ichor_status",
                "description": "Inspect the active Ichor context engine frontier and last selected context metrics.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
            {
                "name": "ichor_expand",
                "description": "Expand exact raw-turn context by source_id handle such as raw_turns:<session>:seq:1-3.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source_id": {"type": "string", "description": "Raw turn range or source handle to expand."}
                    },
                    "required": ["source_id"],
                    "additionalProperties": False,
                },
            },
        ]

    def handle_tool_call(self, name: str, args: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        if name == "ichor_status":
            return json.dumps({"ok": True, "status": self.get_status()})
        if name == "ichor_expand":
            return json.dumps(self._expand_source(str(args.get("source_id", ""))))
        return json.dumps({"ok": False, "error": f"Unknown Ichor context engine tool: {name}"})

    def get_status(self) -> dict[str, Any]:
        base = super().get_status()
        raw_store_status: dict[str, Any]
        if self.raw_turn_store is None:
            raw_store_status = {"configured": False}
        else:
            frontier = None
            if self.session_id and hasattr(self.raw_turn_store, "get_frontier"):
                try:
                    frontier = self.raw_turn_store.get_frontier(self.session_id)
                except Exception as exc:
                    self._raw_turn_store_error = exc.__class__.__name__
            raw_store_status = {
                "configured": True,
                "last_result": self._raw_turn_store_result,
                "last_error": self._raw_turn_store_error,
                "frontier": frontier,
            }
        base.update({
            "mode": "default_off_plugin",
            "session_id": self.session_id,
            "fresh_tail_turns": self.fresh_tail_turns,
            "max_pack_tokens": self.max_pack_tokens,
            "last_original_tokens": self._last_original_tokens,
            "last_assembled_tokens": self._last_assembled_tokens,
            "last_injected": self._last_injected,
            "last_pack_metrics": dict(self._last_pack_metrics),
            "last_source_links": list(self._last_selected_source_links),
            "raw_turn_store": raw_store_status,
        })
        return base

    def _ingest_raw_turns(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        self._raw_turns_by_session[session_id] = [
            {"seq": idx, "message": _safe_message_copy(message)}
            for idx, message in enumerate(messages)
        ]
        if self.raw_turn_store is None:
            return
        try:
            active_tail_start_seq = max(0, len(messages) - self.fresh_tail_turns)
            self._raw_turn_store_result = self.raw_turn_store.ingest_messages(
                session_id,
                [_safe_message_copy(message) for message in messages],
                source="context_engine",
                active_tail_start_seq=active_tail_start_seq,
            )
            self._raw_turn_store_error = ""
        except Exception as exc:
            self._raw_turn_store_result = None
            self._raw_turn_store_error = exc.__class__.__name__

    def _context_message_for(self, query: str) -> dict[str, str] | None:
        self._last_injected = False
        self._last_selected_source_links = []
        self._last_pack_metrics = dict(_DEFAULT_METRICS)
        if not self._needs_context(query):
            return None
        try:
            pack = self._build_context_pack(query=query)
        except Exception as exc:
            self._last_pack_metrics = dict(_DEFAULT_METRICS)
            return {
                "role": "system",
                "content": f"<ichor-context status=\"unavailable\" error=\"{exc.__class__.__name__}\" />",
            }
        metrics = dict(_DEFAULT_METRICS)
        metrics.update({key: int(value or 0) for key, value in (pack.get("metrics") or {}).items() if key in metrics})
        self._last_pack_metrics = metrics
        self._last_selected_source_links = list(pack.get("source_links") or [])
        context = str(pack.get("injectable_context") or "").strip()
        if not context:
            return None
        self._last_injected = True
        return {"role": "system", "content": context}

    def _build_context_pack(self, *, query: str) -> dict[str, Any]:
        if build_context_pack is None:
            raise RuntimeError("Ichor context pack builder unavailable")
        return build_context_pack(
            query,
            god_name="hermes",
            phase="context-engine",
            task_type="context",
            max_items=self.max_pack_items,
            max_tokens=self.max_pack_tokens,
            max_ms=self.max_pack_ms,
            include_graph=False,
            dry_run=True,
        )

    def _needs_context(self, query: str) -> bool:
        if build_context_pack is None:
            return False
        lowered = (query or "").lower()
        explicit_markers = (
            "ichor",
            "context",
            "compress",
            "benchmark",
            "frontier",
            "recall",
            "expand",
        )
        if any(marker in lowered for marker in explicit_markers):
            return True
        if _needs_memory_context is None:
            return False
        return bool(_needs_memory_context(query, "hermes", "context-engine", ""))

    def _handles_message_for(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        fresh_tail: list[dict[str, Any]],
    ) -> dict[str, str] | None:
        omitted_count = max(0, len([m for m in messages if m.get("role") != "system"]) - len(fresh_tail))
        if omitted_count <= 0:
            return None
        last_omitted_seq = max(0, len(messages) - len(fresh_tail) - 1)
        source_id = f"raw_turns:{session_id}:seq:1-{last_omitted_seq}"
        source_lines = [
            "Available Ichor expansions:",
            f"- {source_id} — exact raw turns omitted from the live prompt frontier",
        ]
        for link in self._last_selected_source_links[:4]:
            source_lines.append(
                "- source:{path}#{sid} — {title}".format(
                    path=link.get("source_path", ""),
                    sid=link.get("source_id", ""),
                    title=link.get("title", "Ichor source"),
                )
            )
        return {"role": "system", "content": "\n".join(source_lines)}

    def _expand_source(self, source_id: str) -> dict[str, Any]:
        match = re.fullmatch(r"raw_turns:([^:]+):seq:(\d+)-(\d+)", source_id)
        if not match:
            return {"ok": False, "error": "unsupported_source_id", "source_id": source_id}
        session_id, start_text, end_text = match.groups()
        start = int(start_text)
        end = int(end_text)
        rows = self._raw_turns_by_session.get(session_id, [])
        selected = [row for row in rows if start <= int(row.get("seq", -1)) <= end]
        source = "in_memory"
        if selected:
            full_content = "\n".join(
                f"[{row['seq']}] {row['message'].get('role')}: {row['message'].get('content', '')}"
                for row in selected
            )
        elif self.raw_turn_store is not None and hasattr(self.raw_turn_store, "fetch_range"):
            try:
                persisted = self.raw_turn_store.fetch_range(session_id, start, end)
                selected = [{"seq": row.seq, "message": {"role": row.role, "content": row.content}} for row in persisted]
                full_content = "\n".join(
                    f"[{row.seq}] {row.role}: {row.content}"
                    for row in persisted
                )
                source = "persistent_store"
            except Exception as exc:
                return {"ok": False, "error": exc.__class__.__name__, "source_id": source_id}
        else:
            full_content = ""
        truncated = len(full_content) > self.max_expand_chars
        content = full_content[: self.max_expand_chars]
        return {
            "ok": bool(selected),
            "source_id": source_id,
            "count": len(selected),
            "content": content,
            "source": source,
            "truncated": truncated,
            "omitted_chars": max(0, len(full_content) - len(content)),
        }


def register(ctx: Any) -> None:
    ctx.register_context_engine(IchorContextEngine())
