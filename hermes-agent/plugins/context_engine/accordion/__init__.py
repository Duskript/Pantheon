"""Accordion context engine.

Phase C of the unified-upgrade plan.

This engine keeps the most recent working tail of the conversation in full
fidelity and folds older turns into Ichor ``episodic_folds`` records. The
fold index is persisted per session so the Phase B hook layer can rehydrate
old context on demand when the user references a folded topic.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from dataclasses import dataclass
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:  # optional at import-time in minimal environments
    import yaml
except Exception:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

# Make repo-root imports available when loaded by Hermes' directory-based
# plugin loader. We need both the hermes-agent repo (agent/, plugins/) and the
# parent Pantheon repo (lib/). First try walking up from the file (works in the
# repo source layout), then check known locations (works from vendored runtime).
_HERMES_ROOT = Path(__file__).resolve()
while _HERMES_ROOT.parent != _HERMES_ROOT:
    if (_HERMES_ROOT / "lib" / "ichor_mcp.py").exists():
        break
    _HERMES_ROOT = _HERMES_ROOT.parent
if not (_HERMES_ROOT / "lib" / "ichor_mcp.py").exists():
    # Fallback: check known locations
    for _candidate in (Path.home() / "pantheon", Path("/home/konan/pantheon")):
        if _candidate.is_dir() and (_candidate / "lib" / "ichor_mcp.py").exists():
            _HERMES_ROOT = _candidate
            break
if str(_HERMES_ROOT) not in sys.path:
    sys.path.insert(0, str(_HERMES_ROOT))

from agent.context_engine import ContextEngine
from agent.context_compressor import SUMMARY_PREFIX
from lib.ichor_mcp import ichor_expand, ichor_fold

logger = logging.getLogger(__name__)

PLUGIN_NAME = "accordion"
DEFAULT_WORKING_TAIL = 7
DEFAULT_THRESHOLD_PERCENT = 0.75
DEFAULT_CONTEXT_LENGTH = 200_000

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")


@dataclass
class FoldRecord:
    fold_id: int
    summary: str
    keywords: list[str]
    token_count: int
    created_at: str
    cluster_id: int = 0


@dataclass
class ClusterRecord:
    cluster_id: int
    fold_ids: list[int]
    summary: str
    keywords: list[str]
    created_at: str
    updated_at: str


class TopicClusterer:
    """Groups related fold records by topic and time proximity."""

    def __init__(self, window_minutes: int = 30):
        self.window_minutes = window_minutes

    def cluster(self, folds: list[FoldRecord]) -> list[ClusterRecord]:
        if not folds:
            return []
        ordered = sorted(folds, key=lambda f: (f.created_at, f.fold_id))
        clusters: list[list[FoldRecord]] = []
        for fold in ordered:
            if not clusters:
                clusters.append([fold])
                continue
            if self._same_topic(clusters[-1], fold):
                clusters[-1].append(fold)
            else:
                clusters.append([fold])
        records: list[ClusterRecord] = []
        for idx, cluster in enumerate(clusters, start=1):
            keywords = self._cluster_keywords(cluster)
            records.append(
                ClusterRecord(
                    cluster_id=idx,
                    fold_ids=[f.fold_id for f in cluster],
                    summary=self._cluster_summary(cluster, keywords),
                    keywords=keywords,
                    created_at=cluster[0].created_at,
                    updated_at=cluster[-1].created_at,
                )
            )
        return records

    def _same_topic(self, cluster: list[FoldRecord], fold: FoldRecord) -> bool:
        prev = cluster[-1]
        if self._minutes_between(prev.created_at, fold.created_at) > self.window_minutes:
            return False
        return bool(set(prev.keywords) & set(fold.keywords))

    def _minutes_between(self, a: str, b: str) -> float:
        try:
            da = datetime.fromisoformat(a.replace("Z", "+00:00"))
            db = datetime.fromisoformat(b.replace("Z", "+00:00"))
            return abs((db - da).total_seconds()) / 60.0
        except Exception:
            return 0.0

    def _cluster_keywords(self, cluster: list[FoldRecord]) -> list[str]:
        counts: Counter[str] = Counter()
        for fold in cluster:
            counts.update(fold.keywords)
        return [kw for kw, _count in counts.most_common(12) if kw]

    def _cluster_summary(self, cluster: list[FoldRecord], keywords: list[str]) -> str:
        if not cluster:
            return "Empty cluster"
        if keywords:
            focus = ", ".join(keywords[:4])
            return f"Topic cluster ({len(cluster)} fold(s)): {focus}"
        return f"Topic cluster ({len(cluster)} fold(s))"


class AccordionEngine(ContextEngine):
    """ContextEngine that folds old turns into Ichor episodic storage."""

    def __init__(self, config: Optional[dict[str, Any]] = None):
        cfg = self._load_config()
        engine_cfg = self._coerce_dict(cfg.get("context", {})).get("accordion", {})
        config = self._coerce_dict(config or {})
        engine_cfg = self._coerce_dict(engine_cfg)

        self.working_tail = int(
            config.get("working_tail", engine_cfg.get("working_tail", DEFAULT_WORKING_TAIL))
        )
        self.threshold_percent = float(
            config.get("threshold_percent", engine_cfg.get("threshold_percent", DEFAULT_THRESHOLD_PERCENT))
        )
        self.context_length = int(
            config.get("context_length", engine_cfg.get("context_length", DEFAULT_CONTEXT_LENGTH))
        )
        self.threshold_tokens = int(self.context_length * self.threshold_percent)
        self.protect_first_n = int(config.get("protect_first_n", engine_cfg.get("protect_first_n", 3)))
        self.protect_last_n = int(config.get("protect_last_n", engine_cfg.get("protect_last_n", self.working_tail)))
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.last_total_tokens = 0
        self.compression_count = 0
        self._session_id = ""
        self._session_home = self._hermes_home()
        self._fold_index: list[FoldRecord] = []
        self._cluster_index: list[ClusterRecord] = []
        self._fold_index_path: Optional[Path] = None
        self._cluster_index_path: Optional[Path] = None
        self._clusterer = TopicClusterer()

    # ------------------------------------------------------------------
    # Identity / state
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return PLUGIN_NAME

    def update_from_response(self, usage: Dict[str, Any]) -> None:
        self.last_prompt_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
        self.last_completion_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
        self.last_total_tokens = int(usage.get("total_tokens", 0) or 0)

    def should_compress(self, prompt_tokens: int = None) -> bool:
        tokens = int(prompt_tokens if prompt_tokens is not None else self.last_prompt_tokens or 0)
        if self.threshold_tokens <= 0:
            return False
        return tokens >= self.threshold_tokens

    def has_content_to_compress(self, messages: List[Dict[str, Any]]) -> bool:
        _leading, turns = self._partition_messages(messages)
        return len(turns) > self.working_tail

    def on_session_start(self, session_id: str, **kwargs) -> None:
        self._session_id = session_id or ""
        hermes_home = kwargs.get("hermes_home")
        if hermes_home:
            self._session_home = Path(str(hermes_home)).expanduser()
        base = self._session_home / "accordion"
        self._fold_index_path = base / "fold-index" / f"{self._session_id or 'session'}.json"
        self._cluster_index_path = base / "cluster-index" / f"{self._session_id or 'session'}.json"
        self._load_fold_index()
        self._load_cluster_index()
        self._persist_fold_index()
        self._persist_cluster_index()

    def on_session_end(self, session_id: str, messages: List[Dict[str, Any]]) -> None:
        self._persist_fold_index()

    def on_session_reset(self) -> None:
        super().on_session_reset()
        self.compression_count = 0
        self._session_id = ""
        self._fold_index = []
        self._cluster_index = []
        self._persist_fold_index()
        self._persist_cluster_index()

    def update_model(
        self,
        model: str,
        context_length: int,
        base_url: str = "",
        api_key: str = "",
        provider: str = "",
        api_mode: str = "",
    ) -> None:
        super().update_model(model, context_length, base_url=base_url, api_key=api_key, provider=provider, api_mode=api_mode)
        self.threshold_tokens = int(self.context_length * self.threshold_percent)

    def get_status(self) -> Dict[str, Any]:
        status = super().get_status()
        status.update(
            {
                "engine": self.name,
                "working_tail": self.working_tail,
                "fold_count": len(self._fold_index),
                "cluster_count": len(self._cluster_index),
                "session_id": self._session_id,
            }
        )
        return status

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "accordion_expand",
                "description": "Expand folded accordion context for a query.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Reference or question to resolve."},
                    },
                    "required": ["query"],
                },
            }
        ]

    def handle_tool_call(self, name: str, args: Dict[str, Any], **kwargs) -> str:
        if name != "accordion_expand":
            return json.dumps({"error": f"Unknown context engine tool: {name}"}, ensure_ascii=False)
        query = str(args.get("query") or "")
        result = self.expand_for_message(query)
        if result is None:
            return json.dumps({"expanded": False, "context": ""}, ensure_ascii=False)
        return json.dumps(result, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Main compression / expansion logic
    # ------------------------------------------------------------------

    def compress(
        self,
        messages: List[Dict[str, Any]],
        current_tokens: int = None,
        focus_topic: str = None,
        force: bool = False,
    ) -> List[Dict[str, Any]]:
        if not messages:
            return messages

        leading, turns = self._partition_messages(messages)
        if not turns:
            return messages

        if not force and not self.has_content_to_compress(messages):
            return messages

        if len(turns) <= self.working_tail:
            return messages

        folded_turns = turns[:-self.working_tail]
        tail_turns = turns[-self.working_tail :]
        folded_messages = [msg for turn in folded_turns for msg in turn]
        summary = self._build_summary(folded_turns, focus_topic=focus_topic)
        token_count = int(current_tokens or self.last_prompt_tokens or self._estimate_tokens(messages))
        full_content = json.dumps(folded_messages, ensure_ascii=False)

        fold_result = self._call_ichor_fold(full_content, summary, token_count)
        fold_id = self._extract_fold_id(fold_result)
        if fold_id is not None:
            self._fold_index.append(
                FoldRecord(
                    fold_id=fold_id,
                    summary=summary,
                    keywords=self._keywords(summary, focus_topic),
                    token_count=token_count,
                    created_at=self._now(),
                )
            )
            self._rebuild_clusters()
            self._persist_fold_index()
            self._persist_cluster_index()

        summary_message = {
            "role": "assistant",
            "content": f"{SUMMARY_PREFIX}\n{summary}",
            "_compressed_summary": True,
        }
        self.compression_count += 1
        return leading + [summary_message] + [msg for turn in tail_turns for msg in turn]

    def expand_for_message(self, query: str) -> Optional[dict[str, Any]]:
        query = self._normalize_text(query)
        if not query:
            return None
        self._load_fold_index()
        if not self._fold_index:
            return None

        query_words = set(self._keywords(query))
        if not self._cluster_index:
            self._rebuild_clusters()

        best_cluster: Optional[ClusterRecord] = None
        best_cluster_score = 0
        for cluster in reversed(self._cluster_index):
            score = len(query_words & set(cluster.keywords))
            if score > best_cluster_score:
                best_cluster = cluster
                best_cluster_score = score

        if best_cluster is None or best_cluster_score <= 0:
            return None

        cluster_fold_ids = set(best_cluster.fold_ids)
        best: Optional[FoldRecord] = None
        best_score = 0
        for record in reversed(self._fold_index):
            if record.fold_id not in cluster_fold_ids:
                continue
            score = len(query_words & set(record.keywords))
            if score > best_score:
                best = record
                best_score = score

        if best is None or best_score <= 0:
            return None

        expanded = self._call_ichor_expand(best.fold_id)
        fold = expanded.get("fold") if isinstance(expanded, dict) else None
        if not isinstance(fold, dict):
            return None

        transcript = self._format_full_content(fold.get("full_content"))
        context = f"{SUMMARY_PREFIX}\n{fold.get('summary', best.summary)}\n\n{transcript}".strip()
        return {
            "expanded": True,
            "fold_id": best.fold_id,
            "summary": fold.get("summary", best.summary),
            "context": context,
            "source": PLUGIN_NAME,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _call_ichor_fold(self, content: str, summary: str, token_count: int) -> dict[str, Any]:
        raw = ichor_fold(
            self._session_id or "",
            content,
            summary,
            token_count,
            fold_type="turn",
            parent_fold_id=None,
        )
        return self._json_loads(raw)

    def _call_ichor_expand(self, fold_id: int) -> dict[str, Any]:
        raw = ichor_expand(int(fold_id))
        return self._json_loads(raw)

    def _extract_fold_id(self, payload: dict[str, Any]) -> Optional[int]:
        fold = payload.get("fold") if isinstance(payload, dict) else None
        if isinstance(fold, dict) and fold.get("id") is not None:
            try:
                return int(fold.get("id"))
            except Exception:
                return None
        return None

    def _build_summary(self, folded_turns: list[list[dict[str, Any]]], focus_topic: Optional[str] = None) -> str:
        snippets: list[str] = []
        if focus_topic:
            snippets.append(f"Focus: {self._normalize_text(focus_topic)}")
        snippets.append(f"Folded {len(folded_turns)} older turn(s).")
        first_turn = folded_turns[0] if folded_turns else []
        last_turn = folded_turns[-1] if folded_turns else []
        if first_turn:
            snippets.append(f"Start: {self._turn_preview(first_turn)}")
        if last_turn and last_turn is not first_turn:
            snippets.append(f"End: {self._turn_preview(last_turn)}")
        return "\n".join(snippets)

    def _turn_preview(self, turn: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for msg in turn:
            text = self._content_text(msg.get("content"))
            if not text:
                continue
            role = str(msg.get("role", "message"))
            parts.append(f"{role}: {self._normalize_text(text)[:160]}")
        return " | ".join(parts)

    def _format_full_content(self, full_content: Any) -> str:
        if isinstance(full_content, str):
            try:
                parsed = json.loads(full_content)
            except Exception:
                return full_content
        else:
            parsed = full_content
        if not isinstance(parsed, list):
            return self._content_text(parsed)
        lines: list[str] = []
        for msg in parsed:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role", "message")).upper()
            text = self._content_text(msg.get("content"))
            if text:
                lines.append(f"{role}: {text}")
        return "\n".join(lines)

    def _partition_messages(self, messages: List[Dict[str, Any]]) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]:
        leading: list[dict[str, Any]] = []
        turns: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        seen_user = False
        for msg in messages:
            if self._is_summary_message(msg):
                if not seen_user and not current and not turns:
                    leading.append(msg)
                else:
                    if current:
                        turns.append(current)
                        current = []
                    leading.append(msg)
                continue
            role = str(msg.get("role", "")).strip().lower()
            if role == "system" and not seen_user and not turns and not current:
                leading.append(msg)
                continue
            if role == "user":
                seen_user = True
                if current:
                    turns.append(current)
                current = [msg]
                continue
            if not current:
                current = []
            current.append(msg)
        if current:
            turns.append(current)
        return leading, turns

    def _is_summary_message(self, message: Dict[str, Any]) -> bool:
        text = self._normalize_text(self._content_text(message.get("content")))
        return text.startswith(SUMMARY_PREFIX)

    def _persist_fold_index(self) -> None:
        if self._fold_index_path is None:
            return
        self._fold_index_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "session_id": self._session_id,
            "updated_at": self._now(),
            "folds": [
                {
                    "fold_id": record.fold_id,
                    "summary": record.summary,
                    "keywords": record.keywords,
                    "token_count": record.token_count,
                    "created_at": record.created_at,
                    "cluster_id": record.cluster_id,
                }
                for record in self._fold_index
            ],
        }
        self._fold_index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_fold_index(self) -> None:
        if self._fold_index_path is None or not self._fold_index_path.exists():
            return
        try:
            raw = json.loads(self._fold_index_path.read_text(encoding="utf-8"))
            folds = raw.get("folds") if isinstance(raw, dict) else []
            if not isinstance(folds, list):
                return
            loaded: list[FoldRecord] = []
            for entry in folds:
                if not isinstance(entry, dict):
                    continue
                try:
                    loaded.append(
                        FoldRecord(
                            fold_id=int(entry.get("fold_id")),
                            summary=str(entry.get("summary") or ""),
                            keywords=[str(item) for item in entry.get("keywords") or []],
                            token_count=int(entry.get("token_count") or 0),
                            created_at=str(entry.get("created_at") or self._now()),
                            cluster_id=int(entry.get("cluster_id") or 0),
                        )
                    )
                except Exception:
                    continue
            self._fold_index = loaded
        except Exception as exc:
            logger.debug("accordion fold index load failed: %s", exc)

    def _persist_cluster_index(self) -> None:
        if self._cluster_index_path is None:
            return
        self._cluster_index_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "session_id": self._session_id,
            "updated_at": self._now(),
            "clusters": [
                {
                    "cluster_id": cluster.cluster_id,
                    "fold_ids": cluster.fold_ids,
                    "summary": cluster.summary,
                    "keywords": cluster.keywords,
                    "created_at": cluster.created_at,
                    "updated_at": cluster.updated_at,
                }
                for cluster in self._cluster_index
            ],
        }
        self._cluster_index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_cluster_index(self) -> None:
        if self._cluster_index_path is None or not self._cluster_index_path.exists():
            return
        try:
            raw = json.loads(self._cluster_index_path.read_text(encoding="utf-8"))
            clusters = raw.get("clusters") if isinstance(raw, dict) else []
            if not isinstance(clusters, list):
                return
            loaded: list[ClusterRecord] = []
            for entry in clusters:
                if not isinstance(entry, dict):
                    continue
                try:
                    loaded.append(
                        ClusterRecord(
                            cluster_id=int(entry.get("cluster_id")),
                            fold_ids=[int(item) for item in entry.get("fold_ids") or []],
                            summary=str(entry.get("summary") or ""),
                            keywords=[str(item) for item in entry.get("keywords") or []],
                            created_at=str(entry.get("created_at") or self._now()),
                            updated_at=str(entry.get("updated_at") or self._now()),
                        )
                    )
                except Exception:
                    continue
            self._cluster_index = loaded
        except Exception as exc:
            logger.debug("accordion cluster index load failed: %s", exc)

    def _rebuild_clusters(self) -> None:
        self._cluster_index = self._clusterer.cluster(self._fold_index)
        cluster_by_fold = {fold_id: cluster.cluster_id for cluster in self._cluster_index for fold_id in cluster.fold_ids}
        rebuilt: list[FoldRecord] = []
        for record in self._fold_index:
            rebuilt.append(
                FoldRecord(
                    fold_id=record.fold_id,
                    summary=record.summary,
                    keywords=record.keywords,
                    token_count=record.token_count,
                    created_at=record.created_at,
                    cluster_id=cluster_by_fold.get(record.fold_id, record.cluster_id),
                )
            )
        self._fold_index = rebuilt

    def _estimate_tokens(self, messages: List[Dict[str, Any]]) -> int:
        total = 0
        for msg in messages:
            total += max(1, len(self._content_text(msg.get("content"))) // 4)
        return total

    def _keywords(self, *parts: Optional[str]) -> list[str]:
        words: list[str] = []
        for part in parts:
            if not part:
                continue
            for match in _WORD_RE.findall(self._normalize_text(part).lower()):
                if len(match) >= 4 and match not in words:
                    words.append(match)
        return words[:12]

    def _normalize_text(self, value: Any) -> str:
        return " ".join(self._content_text(value).split()).strip()

    def _content_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts: list[str] = []
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or item.get("value") or ""))
                else:
                    parts.append(str(item))
            return " ".join(part for part in parts if part)
        if isinstance(value, dict):
            return str(value.get("text") or value.get("content") or value.get("value") or value)
        return str(value)

    def _json_loads(self, raw: str) -> dict[str, Any]:
        try:
            parsed = json.loads(raw)
        except Exception:
            return {"error": raw}
        return parsed if isinstance(parsed, dict) else {"value": parsed}

    def _coerce_dict(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _hermes_home(self) -> Path:
        home = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
        return Path(home).expanduser()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _load_config(self) -> dict[str, Any]:
        cfg_path = self._hermes_home() / "config.yaml"
        try:
            if yaml is None or not cfg_path.exists():
                return {}
            loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            return loaded if isinstance(loaded, dict) else {}
        except Exception as exc:
            logger.debug("accordion config load failed: %s", exc)
            return {}


# Hermes' loader accepts either register(ctx) or a top-level ContextEngine.
# We provide both: a concrete engine class and a register() shim.

def register(ctx) -> None:
    engine = AccordionEngine()
    ctx.register_context_engine(engine)
