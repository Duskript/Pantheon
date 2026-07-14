"""Hades distillation phase.

Phase 3 of the pipeline. For each Codex, walks `codex/sessions/*.md`
and writes a distilled summary into `codex/distilled/`. The
distillation is **pattern-based, not LLM-based** — it extracts:

  - Topics (markdown headers)
  - Decisions (lines after "Decision:" / "Conclusion:" / etc.)
  - Key terms (bold spans)
  - Code blocks (with language tag)
  - Notes (first ~25 bullet points)

The May 23 pipeline overhaul (decision 2026-05-23--058) added an
LLM-enhanced distillation path, but the current code is the
pattern-based version. The LLM path is not implemented in `hades.py`
and lives in `hermes-agent/scripts/distill_sessions` instead — that's
the step the cron calls separately.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from .paths import (
    DISTILLED_DIR_NAME,
    KNOWN_CODEXES,
    SESSIONS_DIR_NAME,
    ATHENAEUM_ROOT,
)

logger = logging.getLogger(__name__)


def distill_sessions(codex_name: str, codex_root: Path) -> Dict[str, int]:
    """Extract distilled knowledge from session logs.

    For each session file in codex/sessions/, extracts:
    - Distinct topics mentioned (from markdown headers, bold terms, bullet points)
    - Code blocks
    - Decisions and conclusions (lines after "Decision:", "Conclusion:", etc.)

    Writes a distilled summary to codex/distilled/.
    """
    sessions_dir = codex_root / SESSIONS_DIR_NAME
    distilled_dir = codex_root / DISTILLED_DIR_NAME
    distilled_dir.mkdir(parents=True, exist_ok=True)

    sessions = sorted(sessions_dir.glob("*.md")) if sessions_dir.is_dir() else []
    files_written = 0

    # Known signal patterns for extraction
    topic_pattern = re.compile(r"^#{1,3}\s+(.+)", re.MULTILINE)
    decision_pattern = re.compile(r"^\s*(?:Decision|Conclusion|Result|Outcome|Resolution)\s*[:\-–—]\s*(.+)", re.IGNORECASE | re.MULTILINE)
    bullet_pattern = re.compile(r"^\s*[-*+]\s+(.+)", re.MULTILINE)
    bold_pattern = re.compile(r"\*\*(.+?)\*\*")
    code_block_pattern = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)

    for session_path in sessions:
        try:
            content = session_path.read_text(encoding="utf-8")
        except Exception:
            continue

        if len(content.strip()) < 200:
            continue  # Skip empty or near-empty sessions

        # Extract metadata from frontmatter
        metadata: Dict[str, str] = {}
        fm_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if fm_match:
            for line in fm_match.group(1).strip().split("\n"):
                if ":" in line:
                    k, _, v = line.partition(":")
                    metadata[k.strip()] = v.strip()
            content = content[fm_match.end():]

        # Extract topics (headers)
        topics: list = []
        for m in topic_pattern.finditer(content):
            t = m.group(1).strip()
            if t and t not in topics:
                topics.append(t)

        # Extract decisions
        decisions = [m.group(1).strip() for m in decision_pattern.finditer(content) if m.group(1).strip()]

        # Extract bold/key terms
        key_terms = list(set(m.group(1) for m in bold_pattern.finditer(content) if m.group(1)))

        # Extract code blocks
        code_blocks = []
        for m in code_block_pattern.finditer(content):
            lang = m.group(1) or "text"
            snippet = m.group(2).strip()
            if snippet:
                code_blocks.append({"language": lang, "content": snippet[:500]})

        # Extract bullet points (first ~20)
        bullets = [m.group(1).strip() for m in bullet_pattern.finditer(content) if m.group(1).strip()][:25]

        if not topics and not decisions and not bullets:
            continue  # Nothing substantive to distill

        # Build distilled document
        session_id = session_path.stem
        lines = [
            f"# Distilled: {session_id}",
            "",
            f"Source: `{codex_name}/{SESSIONS_DIR_NAME}/{session_path.name}`",
            f"Distilled at: {datetime.now(timezone.utc).isoformat()}",
            "",
        ]

        if metadata:
            lines.append("## Metadata")
            for k, v in metadata.items():
                lines.append(f"- **{k}**: {v}")
            lines.append("")

        if topics:
            lines.append(f"## Topics ({len(topics)})")
            for t in topics[:15]:
                lines.append(f"- {t}")
            lines.append("")

        if decisions:
            lines.append(f"## Decisions / Conclusions ({len(decisions)})")
            for d in decisions:
                lines.append(f"- {d}")
            lines.append("")

        if key_terms:
            lines.append(f"## Key Terms ({len(key_terms)})")
            for t in sorted(key_terms)[:20]:
                lines.append(f"- {t}")
            lines.append("")

        if code_blocks:
            lines.append("## Code / Data")
            for cb in code_blocks[:5]:
                lines.append(f"```{cb['language']}")
                lines.append(cb['content'])
                lines.append("```")
                lines.append("")

        if bullets:
            lines.append(f"## Notes ({len(bullets)})")
            for b in bullets[:20]:
                lines.append(f"- {b}")
            lines.append("")

        # Write distilled file
        distilled_name = f"{session_id}--distilled.md"
        distilled_path = distilled_dir / distilled_name
        distilled_path.write_text("\n".join(lines), encoding="utf-8")
        files_written += 1

    return {
        "sessions_processed": len(sessions),
        "distilled_files_written": files_written,
    }


def run_distillation() -> Dict[str, Any]:
    """Run distillation across all Codices with sessions."""
    results: Dict[str, Any] = {
        "sessions_processed": 0,
        "distilled_files_written": 0,
        "by_codex": {},
    }

    for codex_name in KNOWN_CODEXES:
        codex_dir = ATHENAEUM_ROOT / codex_name
        if not codex_dir.is_dir():
            continue

        codex_result = distill_sessions(codex_name, codex_dir)
        results["sessions_processed"] += codex_result.get("sessions_processed", 0)
        results["distilled_files_written"] += codex_result.get("distilled_files_written", 0)
        results["by_codex"][codex_name] = codex_result

    return results
