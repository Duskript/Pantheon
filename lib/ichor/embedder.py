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
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

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


# Query-embedding cache. The same query text recurs constantly: a follow-up turn
# re-asks the same thing, and the weight tuner scores one query set under a dozen
# configurations. A CPU embedding costs 40-120 ms and buys nothing the second
# time. Bounded by entry count (vectors are deterministic for a given model), so
# the cache cannot grow without limit in a long-lived process.
_QUERY_CACHE: "OrderedDict[str, Tuple[float, ...]]" = OrderedDict()
_QUERY_CACHE_MAX = 512
_QUERY_CACHE_LOCK = threading.Lock()
_QUERY_CACHE_HITS = 0
_QUERY_CACHE_MISSES = 0


def embed_one(text: str, *, use_cache: bool = True) -> Optional[List[float]]:
    """Convenience: embed a single text. Returns None on failure.

    Memoised by stripped query text (see `_QUERY_CACHE`). Pass
    `use_cache=False` when measuring true embedding cost.
    """
    if not text or not text.strip():
        return None
    key = text.strip()

    global _QUERY_CACHE_HITS, _QUERY_CACHE_MISSES
    if use_cache:
        with _QUERY_CACHE_LOCK:
            cached = _QUERY_CACHE.get(key)
            if cached is not None:
                _QUERY_CACHE.move_to_end(key)
                _QUERY_CACHE_HITS += 1
                return list(cached)
            _QUERY_CACHE_MISSES += 1

    results = embed([key])
    vector = results[0] if results else None
    if vector is not None and use_cache:
        with _QUERY_CACHE_LOCK:
            _QUERY_CACHE[key] = tuple(vector)
            _QUERY_CACHE.move_to_end(key)
            while len(_QUERY_CACHE) > _QUERY_CACHE_MAX:
                _QUERY_CACHE.popitem(last=False)
    return vector


def query_cache_stats() -> Dict[str, int]:
    """Cache telemetry: entries, hits, misses (for eval reports and ops)."""
    with _QUERY_CACHE_LOCK:
        return {
            "entries": len(_QUERY_CACHE),
            "max_entries": _QUERY_CACHE_MAX,
            "hits": _QUERY_CACHE_HITS,
            "misses": _QUERY_CACHE_MISSES,
        }


def query_cache_clear() -> None:
    """Drop cached query vectors (tests, and after a model swap)."""
    global _QUERY_CACHE_HITS, _QUERY_CACHE_MISSES
    with _QUERY_CACHE_LOCK:
        _QUERY_CACHE.clear()
        _QUERY_CACHE_HITS = 0
        _QUERY_CACHE_MISSES = 0


def is_available() -> bool:
    """True if fastembed is importable and the model can be loaded."""
    try:
        _load_model()
        return True
    except Exception:
        return False