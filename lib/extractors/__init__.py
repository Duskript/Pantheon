"""Ichor extraction adapters.

This package contains higher-level ingestion components that transform raw
session events into the typed contracts under ``lib.ichor``. Extractors own
prompting and normalization; lifecycle policy remains in the tension gate and
persistence remains in ``ClaimStore``.

Phase 0C exposes the claim-aware LLM adapter while preserving compatibility
with the established entity/relationship extractor. Phase 0D adds the
deterministic structural extractor for boring infrastructure facts.
"""

from lib.extractors.llm_extractor import LLMClaimExtractor, build_claim_prompt
from lib.extractors.structural_extractor import (
    DEFAULT_CONFIDENCE,
    DEFAULT_EXTRACTED_BY,
    StructuralClaimCandidate,
    extract_from_bundle,
    extract_from_source_file,
    extract_structural_candidates,
    load_source_bundle,
    persist_candidates,
    run,
)

__all__ = [
    "LLMClaimExtractor",
    "build_claim_prompt",
    "StructuralClaimCandidate",
    "DEFAULT_CONFIDENCE",
    "DEFAULT_EXTRACTED_BY",
    "extract_structural_candidates",
    "extract_from_bundle",
    "extract_from_source_file",
    "load_source_bundle",
    "persist_candidates",
    "run",
]
