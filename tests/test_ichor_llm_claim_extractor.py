"""Phase 0C tests for claim-aware L2 extraction.

The suite uses canned LLM JSON and a real temporary SQLite schema. It verifies
prompt shape, claim persistence with evidence/entity links, and compatibility
with the pre-existing entity-only extractor response.
"""

import sqlite3
from pathlib import Path

import sqlite_vec

from lib.extractors.llm_extractor import LLMClaimExtractor, build_claim_prompt
from lib.ichor import ClaimStore, schema_v2


def _store(tmp_path: Path) -> ClaimStore:
    db_path = tmp_path / "ichor.db"
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.executescript(schema_v2.SCHEMA_SQL)
    conn.close()
    return ClaimStore(db_path)


def test_prompt_requests_structured_claims_and_entity_roles() -> None:
    prompt = build_claim_prompt([(42, "Pantheon uses SQLite for Ichor.")])

    assert '"claims"' in prompt
    assert '"text"' in prompt
    assert '"type"' in prompt
    assert '"entities"' in prompt
    assert '"role"' in prompt
    assert '"source_event_id"' in prompt
    assert "Pantheon uses SQLite for Ichor." in prompt


def test_extractor_writes_claim_evidence_and_entities(tmp_path: Path) -> None:
    store = _store(tmp_path)
    response = """{
      "claims": [{
        "text": "Pantheon uses SQLite for Ichor memory.",
        "type": "fact",
        "confidence": 0.91,
        "source_event_id": 42,
        "entities": [{"name": "Ichor", "type": "project", "role": "subject"}]
      }],
      "entities": [], "relationships": [], "relationship_types": []
    }"""
    extractor = LLMClaimExtractor(store, call_fn=lambda prompt, cfg, **kwargs: response)

    result = extractor.extract(
        [(42, "Pantheon uses SQLite for Ichor memory.")],
        session_id="session-123",
        provider_cfg={"provider": "stub"},
    )

    assert result["claims_created"] == 1
    claim = store.get_claim(result["claim_ids"][0])
    assert claim is not None
    assert claim.extracted_by == "llm"
    assert claim.confidence == 0.91
    assert store.list_evidence(claim.id)[0].source_event_id == 42
    assert store.list_entities(claim.id)[0].entity_name == "Ichor"


def test_entity_only_response_uses_legacy_fallback(tmp_path: Path) -> None:
    store = _store(tmp_path)
    response = '{"entities": [{"name": "Ichor", "type": "project"}]}'
    fallback_calls = []

    def fallback(texts, provider_cfg, **kwargs):
        fallback_calls.append(texts)
        return {"entities": [{"name": "Ichor", "type": "project"}], "relationships": []}

    extractor = LLMClaimExtractor(
        store,
        call_fn=lambda prompt, cfg, **kwargs: response,
        fallback_fn=fallback,
    )
    result = extractor.extract(
        [(9, "Ichor is a project")],
        session_id="legacy-session",
        provider_cfg={"provider": "stub"},
    )

    assert result["fallback_used"] is True
    assert result["claims_created"] == 0
    assert result["legacy"]["entities"][0]["name"] == "Ichor"
    assert fallback_calls == [["Ichor is a project"]]