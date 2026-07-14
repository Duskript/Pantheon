"""Claim-aware wrapper around Ichor's existing L2 entity extractor.

Phase 0C enriches the established entity/relationship pipeline rather than
replacing it. The primary prompt requests evidence-backed claims with typed
entity roles. Valid claims are written through ``ClaimStore`` and linked to the
source event and session. If an older model emits only the legacy entity shape,
the wrapper delegates to ``entities.l2_llm.extract_batch`` unchanged.

This separation keeps rollback simple: downstream entity extraction remains
available even when a provider has not yet learned the richer claim schema.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Iterable, Optional

from lib.ichor.contracts import Claim, ClaimEntity, ClaimStore, Evidence
from lib.ichor.vector_backend import get_embedding


CLAIM_PROMPT_TEMPLATE = """You extract durable claims and knowledge-graph entities.

For each supported factual statement, decision, preference, commitment, blocker,
or correction, return one claim. Preserve the event id that supports it. Entity
roles should describe how each entity participates in the claim.

Output ONLY valid JSON with this shape:
{{
  "claims": [
    {{
      "text": "Pantheon uses SQLite for Ichor memory.",
      "type": "fact",
      "confidence": 0.92,
      "source_event_id": 42,
      "entities": [
        {{"name": "Ichor", "type": "project", "role": "subject"}}
      ]
    }}
  ],
  "entities": [],
  "relationships": [],
  "relationship_types": []
}}

Do not invent claims. Confidence must be between 0 and 1. Use only event ids
present in the input. If no durable claim exists, return an empty claims array.

Events:
{events_json}

JSON:"""


def build_claim_prompt(events: Iterable[tuple[int, str]]) -> str:
    """Build a bounded structured-claim prompt from ``(event_id, text)`` rows."""
    payload = [
        {"source_event_id": int(event_id), "text": str(text).strip()[:1500]}
        for event_id, text in events
        if text and str(text).strip()
    ]
    return CLAIM_PROMPT_TEMPLATE.format(
        events_json=json.dumps(payload, ensure_ascii=False, indent=2)
    )


def _json_object(raw: str) -> dict[str, Any]:
    """Extract the outer JSON object from a fenced or prose-wrapped response."""
    if not isinstance(raw, str):
        return {}
    candidate = raw.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        candidate = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        parsed = json.loads(candidate[start:end + 1])
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _default_call(
    prompt: str,
    provider_cfg: dict[str, Any],
    **kwargs: Any,
) -> str:
    """Call the same OpenAI-compatible helper used by the legacy L2 path."""
    from lib.ichor.entities.l2_llm import _default_call_llm

    return _default_call_llm(prompt, provider_cfg, **kwargs)


class LLMClaimExtractor:
    """Extract and persist claims while retaining entity-only compatibility."""

    def __init__(
        self,
        store: ClaimStore,
        *,
        call_fn: Optional[Callable[..., str]] = None,
        fallback_fn: Optional[Callable[..., dict[str, Any]]] = None,
    ) -> None:
        self.store = store
        self.call_fn = call_fn or _default_call
        if fallback_fn is None:
            from lib.ichor.entities.l2_llm import extract_batch

            fallback_fn = extract_batch
        self.fallback_fn = fallback_fn

    def extract(
        self,
        events: Iterable[tuple[int, str]],
        *,
        session_id: str,
        provider_cfg: dict[str, Any],
        model: Optional[str] = None,
        timeout: float = 180.0,
    ) -> dict[str, Any]:
        """Extract claims from events and atomically persist each claim bundle."""
        event_rows = list(events)
        texts = [text for _, text in event_rows]
        valid_event_ids = {int(event_id) for event_id, _ in event_rows}
        prompt = build_claim_prompt(event_rows)
        raw = self.call_fn(prompt, provider_cfg, model=model, timeout=timeout)
        parsed = _json_object(raw)

        if "claims" not in parsed:
            legacy = self.fallback_fn(
                texts,
                provider_cfg,
                model=model,
                call_fn=self.call_fn,
                timeout=timeout,
            )
            return {
                "claims_created": 0,
                "claim_ids": [],
                "fallback_used": True,
                "legacy": legacy,
                "parse_warnings": ["claim array absent; used entity-only fallback"],
            }

        claim_ids: list[int] = []
        warnings: list[str] = []
        claims = parsed.get("claims")
        if not isinstance(claims, list):
            claims = []
            warnings.append("claims was not an array")

        for item in claims:
            normalized = self._normalize_claim(item, valid_event_ids, session_id, warnings)
            if normalized is None:
                continue
            claim, evidence, entities = normalized
            claim_ids.append(
                self.store.insert_claim(claim, evidence=[evidence], entities=entities)
            )

        return {
            "claims_created": len(claim_ids),
            "claim_ids": claim_ids,
            "fallback_used": False,
            "legacy": {
                "entities": parsed.get("entities", []),
                "relationships": parsed.get("relationships", []),
                "relationship_types": parsed.get("relationship_types", []),
            },
            "parse_warnings": warnings,
        }

    @staticmethod
    def _normalize_claim(
        item: Any,
        valid_event_ids: set[int],
        session_id: str,
        warnings: list[str],
    ) -> Optional[tuple[Claim, Evidence, list[ClaimEntity]]]:
        if not isinstance(item, dict) or not str(item.get("text", "")).strip():
            warnings.append("skipped claim without text")
            return None
        try:
            source_event_id = int(item.get("source_event_id"))
        except (TypeError, ValueError):
            warnings.append("skipped claim without valid source_event_id")
            return None
        if source_event_id not in valid_event_ids:
            warnings.append(f"skipped claim with unknown source_event_id {source_event_id}")
            return None

        try:
            confidence = float(item.get("confidence", 0.7))
        except (TypeError, ValueError):
            confidence = 0.7
        confidence = max(0.0, min(1.0, confidence))
        text = str(item["text"]).strip()
        embedding = get_embedding(text)
        entities: list[ClaimEntity] = []
        raw_entities = item.get("entities", [])
        if isinstance(raw_entities, list):
            for entity in raw_entities:
                if not isinstance(entity, dict) or not str(entity.get("name", "")).strip():
                    continue
                entities.append(
                    ClaimEntity(
                        entity_name=str(entity["name"]).strip(),
                        role=str(entity.get("role") or "subject").strip(),
                        embedding=embedding,
                    )
                )

        return (
            Claim(
                text=text,
                type=str(item.get("type") or "fact").strip(),
                confidence=confidence,
                extracted_by="llm",
                source_session_id=session_id,
            ),
            Evidence(source_event_id=source_event_id, source_session_id=session_id),
            entities,
        )
