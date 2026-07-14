"""BGE-small embedder wrapper for Ichor.

Thin wrapper around fastembed.TextEmbedding. Model is loaded lazily on
first call to embed() and cached at module level. Single-threaded by
design — the ChromaDB-era parallelism was the source of OOM kills on
this hardware. For batch backfill, the calling script batches input
chunks itself and calls embed() with the full batch.

Configuration:
    BGE-small-en-v1.5 (default) — 33M params, 384 dim, 120MB on disk
    all-MiniLM-L6-v2          — 22M params, 384 dim, similar quality
    BGE-base-en-v1.5          — 109M params, 768 dim, too slow (8h for 107K)

Spike (2026-06-20, Beelink i3-5005U):
    BGE-small: 12-14 texts/sec at ~150 tokens
    107,019 events → 2.4h one-time backfill
    Model download: 3.8s first run
"""

from __future__ import annotations

import logging
import os
import threading
from typing import List, Optional

logger = logging.getLogger("ichor.embedder")

# Module-level cache — loaded once per process
_MODEL = None
_MODEL_LOCK = threading.Lock()
_MODEL_NAME = os.environ.get("ICHOR_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
_EXPECTED_DIM = 384  # BGE-small output dim. Verified at load time.


class EmbedderUnavailable(Exception):
    """Raised when fastembed is not importable."""


def _load_model():
    """Lazy-load fastembed model. Thread-safe."""
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    with _MODEL_LOCK:
        if _MODEL is not None:  # double-check after lock
            return _MODEL
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise EmbedderUnavailable(
                "fastembed not installed. pip install fastembed"
            ) from exc
        logger.info("Loading embedder model %s...", _MODEL_NAME)
        _MODEL = TextEmbedding(model_name=_MODEL_NAME)
        # Verify dim matches expectation
        probe = list(_MODEL.embed(["test"]))
        actual_dim = len(probe[0])
        if actual_dim != _EXPECTED_DIM:
            raise RuntimeError(
                f"Embedder dim mismatch: expected {_EXPECTED_DIM}, got {actual_dim} "
                f"for model {_MODEL_NAME}. Update _EXPECTED_DIM or ICHOR_EMBED_MODEL."
            )
        logger.info("Embedder loaded (dim=%d)", actual_dim)
        return _MODEL


def embed(texts: List[str]) -> List[List[float]]:
    """Embed a batch of texts. Returns list of 384-dim vectors.

    Returns empty list (not raises) on transient failure. Caller treats
    empty as "no semantic signal" and falls back to FTS5.

    Args:
        texts: list of strings. Empty list returns empty list.

    Returns:
        list of float lists, each length 384. Same length as input.
    """
    if not texts:
        return []
    try:
        model = _load_model()
        results = list(model.embed(texts, batch_size=32))
        return [list(r) for r in results]
    except EmbedderUnavailable:
        logger.warning("Embedder unavailable — returning empty list (FTS5 fallback)")
        return []
    except Exception as exc:
        logger.warning("Embedder failed on batch of %d: %s", len(texts), exc)
        return []


def embed_one(text: str) -> Optional[List[float]]:
    """Convenience: embed a single text. Returns None on failure."""
    if not text or not text.strip():
        return None
    results = embed([text])
    return results[0] if results else None


def is_available() -> bool:
    """True if fastembed is importable and the model can be loaded."""
    try:
        _load_model()
        return True
    except Exception:
        return False