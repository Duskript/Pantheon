"""
Hades embed module — gutted in P4a (ChromaDB removed).

This module used to provide the embedding pipeline (Ollama nomic-embed-text
→ ChromaDB). With ChromaDB gone, embedding is no longer needed:
  - Retrieval now uses FTS5 keyword search (see athenaeum_search MCP tool)
  - ichor_score.compute_score() handles ranking

Public API preserved as no-ops so callers (hades/__init__.py, scripts/) don't
crash. These functions will be removed in a later phase once all callers
are confirmed to be unused.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


# Reference to old ChromaDB directory — kept for diagnostic logging only
CHROMA_DIR = Path.home() / ".hermes" / "pantheon" / "chroma"  # no longer used


def _get_chroma_client():  # type: ignore[no-untyped-def]
    """No-op stub. Always returns None. Use FTS5-based retrieval instead."""
    return None


def _partition_for(codex: str) -> str:
    """No-op stub. Returns the codex name lowercased (matches old format)."""
    return f"pantheon_{codex.lower().replace('-', '_')}"


def _embed_file(file_path: str, content: str, codex_hint: str = "") -> bool:  # noqa: ARG001
    """No-op stub. ChromaDB embedding removed in P4a."""
    return False


def _recheck_embedded_counts(report: Any) -> None:  # noqa: ARG001
    """No-op stub. ChromaDB counts no longer relevant."""
    pass


def embed_missing_files(max_files: int | None = None) -> Dict[str, Any]:  # noqa: ARG001
    """No-op stub. Embedding pipeline removed in P4a.

    Returns an empty report dict for backward compatibility with callers.
    """
    return {
        "checked": 0,
        "embedded": 0,
        "errors": [],
        "note": "embed_missing_files is a no-op since P4a (ChromaDB removed). "
                 "Retrieval is now FTS5-based.",
    }


# _Embedder class kept as a no-op stub for backward compat (e.g. hades/__init__.py
# re-exports it as `_Embedder`).
class _Embedder:
    """No-op stub. ChromaDB embedding removed in P4a."""

    def __init__(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        pass

    def is_available(self) -> bool:
        return False

    def embed(self, text: str, *_args, **_kwargs):  # type: ignore[no-untyped-def, no-untyped-def]
        return None
