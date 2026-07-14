"""Contract tests for the Phase 0B claim embedding endpoint.

The tests inject a deterministic provider so they verify the public contract
without downloading a model or depending on network access. Production first
uses the cached BGE-small embedder and retains a deterministic local fallback
when that optional package is unavailable.
"""

from lib.ichor import vector_backend
from lib.ichor.vector_backend import get_embedding


class DeterministicProvider:
    """Tiny provider double implementing the provider-agnostic protocol."""

    def embed_one(self, text: str) -> list[float]:
        seed = float(sum(text.encode("utf-8")) % 97)
        return [seed, float(len(text)), 1.0]


def test_get_embedding_returns_stable_float_vector() -> None:
    provider = DeterministicProvider()

    first = get_embedding("Pantheon uses SQLite memory.", provider=provider)
    second = get_embedding("Pantheon uses SQLite memory.", provider=provider)

    assert first == second
    assert first
    assert all(isinstance(value, float) for value in first)


def test_get_embedding_accepts_claim_length_text() -> None:
    text = "Ichor stores evidence-backed claims. " * 12

    vector = get_embedding(text, provider=DeterministicProvider())

    assert 50 <= len(text) <= 500
    assert vector[1] == float(len(text))


def test_get_embedding_rejects_blank_text() -> None:
    try:
        get_embedding("   ", provider=DeterministicProvider())
    except ValueError as exc:
        assert "non-empty" in str(exc)
    else:
        raise AssertionError("blank text must not reach an embedding provider")


def test_get_embedding_rejects_empty_provider_result() -> None:
    class EmptyProvider:
        def embed_one(self, text: str) -> list[float]:
            return []

    try:
        get_embedding("valid claim", provider=EmptyProvider())
    except RuntimeError as exc:
        assert "empty vector" in str(exc)
    else:
        raise AssertionError("an empty vector cannot be used for tension scoring")


def test_default_provider_has_deterministic_local_fallback(monkeypatch) -> None:
    """A missing optional BGE package must not disable tension scoring."""
    monkeypatch.setattr(
        vector_backend._BGEEmbeddingProvider,
        "embed_one",
        lambda _self, _text: None,
    )

    first = get_embedding("Postgres listens on port 5432")
    second = get_embedding("Postgres listens on port 5432")

    assert first == second
    assert len(first) == 384
    assert any(value != 0.0 for value in first)