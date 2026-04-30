"""Athenaeum ingestion pipeline.

Ingests URLs, local files, and bulk directories into the Athenaeum,
running rule matching, LLM classification, and auto-embedding.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .classifier import (
    ATHENAEUM_ROOT,
    IngestRule,
    build_metadata_content,
    build_target_path,
    classify_content,
    load_rules,
    match_rule,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class IngestResult:
    """Result of a single ingestion operation."""

    success: bool
    source: str  # original path or URL
    destination: str = ""  # relative path within Athenaeum
    codex: str = ""
    rule_name: str = ""
    error: str = ""
    suggested_codex: str = ""  # non-empty if classifier suggested a new Codex
    action: str = "ingested"  # ingested, skipped, suggested, failed


# ---------------------------------------------------------------------------
# Supported file type detection
# ---------------------------------------------------------------------------


AUDIO_EXTS = {".mp3", ".wav", ".flac", ".ogg", ".aiff", ".wma", ".m4a"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv"}
TEXT_EXTS = {".md", ".txt", ".rst", ".adoc", ".json", ".yaml", ".yml", ".xml", ".csv"}
PDF_EXTS = {".pdf"}
CODE_EXTS = {".py", ".js", ".ts", ".go", ".rs", ".sh", ".rb", ".java", ".c", ".cpp", ".h"}

ALL_KNOWN_EXTS = AUDIO_EXTS | IMAGE_EXTS | VIDEO_EXTS | TEXT_EXTS | PDF_EXTS | CODE_EXTS


def detect_file_type(path: Path) -> str:
    """Return a human-readable type label for a file."""
    ext = path.suffix.lower()
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in TEXT_EXTS:
        return "text"
    if ext in PDF_EXTS:
        return "pdf"
    if ext in CODE_EXTS:
        return "code"
    return "unknown"


# ---------------------------------------------------------------------------
# URL scraping
# ---------------------------------------------------------------------------


def scrape_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """Scrape a URL and return (title, text_content) or (None, None)."""
    try:
        import httpx
        from readability import Document  # readability-lxml
    except ImportError:
        logger.warning("readability-lxml not installed — falling back to raw HTML")
        return _scrape_url_fallback(url)

    try:
        resp = httpx.get(url, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
        doc = Document(resp.text)
        title = doc.title()
        # readability gives us the article body as HTML; strip tags roughly
        content = doc.summary()
        # Simple tag stripping for the classifier
        import re as _re

        text = _re.sub(r"<[^>]+>", " ", content)
        text = _re.sub(r"\s+", " ", text).strip()
        return title, text
    except Exception as exc:
        logger.warning("Failed to scrape URL %s: %s", url, exc)
        return None, None


def _scrape_url_fallback(url: str) -> Tuple[Optional[str], Optional[str]]:
    """Fallback URL scraping without readability."""
    try:
        import httpx

        resp = httpx.get(url, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
        text = resp.text
        # Try to extract <title>
        import re as _re

        title_match = _re.search(r"<title[^>]*>(.*?)</title>", text, _re.IGNORECASE | _re.DOTALL)
        title = title_match.group(1).strip() if title_match else None
        # Rough text extraction — strip tags
        text_clean = _re.sub(r"<[^>]+>", " ", text)
        text_clean = _re.sub(r"\s+", " ", text_clean).strip()[:5000]
        return title, text_clean
    except Exception as exc:
        logger.warning("Fallback scrape failed for %s: %s", url, exc)
        return None, None


# ---------------------------------------------------------------------------
# Audio metadata extraction
# ---------------------------------------------------------------------------


def extract_audio_metadata(path: Path) -> Dict[str, str]:
    """Extract ID3/audio metadata from a file.

    Returns dict with keys: title, artist, album, genre, year, song_name
    """
    metadata: Dict[str, str] = {
        "title": "",
        "artist": "",
        "album": "",
        "genre": "",
        "year": "",
        "song_name": "",
    }

    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(str(path))
        if audio is None:
            return metadata

        tags = audio.tags if hasattr(audio, "tags") else {}

        # Try common tag formats
        if tags:
            for key, map_key in [
                ("title", "title"),
                ("artist", "artist"),
                ("album", "album"),
                ("genre", "genre"),
                ("date", "year"),
            ]:
                tag_value = tags.get(key)
                if not tag_value:
                    tag_value = tags.get(key.upper())
                if not tag_value:
                    tag_value = tags.get(f"T{key.upper()}")
                if tag_value:
                    # mutagen returns a list of strings
                    if isinstance(tag_value, list):
                        tag_value = str(tag_value[0])
                    metadata[map_key] = str(tag_value)

    except ImportError:
        logger.debug("mutagen not installed — skipping audio metadata extraction")
    except Exception as exc:
        logger.debug("Audio metadata extraction failed for %s: %s", path, exc)

    # Use title as song name, fall back to filename stub
    metadata["song_name"] = metadata["title"] or path.stem
    return metadata


# ---------------------------------------------------------------------------
# Companion file detection
# ---------------------------------------------------------------------------


def find_companion_files(
    directory: Path,
    base_name: str,
    companion_exts: Optional[List[str]] = None,
) -> Dict[str, Path]:
    """Find companion files (lyrics .txt, style .md) for a given base name.

    Args:
        directory: Directory to search.
        base_name: Base name to match (without extension).
        companion_exts: Extensions to look for (default: .txt, .md).

    Returns:
        {extension: Path} for found companions.
    """
    if companion_exts is None:
        companion_exts = [".txt", ".md"]

    found: Dict[str, Path] = {}
    for ext in companion_exts:
        # Try exact match: BaseName.ext
        candidate = directory / f"{base_name}{ext}"
        if candidate.exists():
            found[ext] = candidate
            continue
        # Try BaseName--lyrics.txt, BaseName--lyrics.md
        for suffix in ["lyrics", "lyric", "style", "prompt", "metadata"]:
            candidate = directory / f"{base_name}--{suffix}{ext}"
            if candidate.exists():
                found[f"{ext}--{suffix}"] = candidate
                break

    return found


# ---------------------------------------------------------------------------
# Core: Ingest a single file
# ---------------------------------------------------------------------------


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def ingest_file(
    file_path: str,
    *,
    rules: Optional[List[IngestRule]] = None,
    classify: bool = True,
    skip_embed: bool = False,
    bulk_group: Optional[Dict[str, Any]] = None,
) -> IngestResult:
    """Ingest a single file into the Athenaeum.

    Args:
        file_path: Path to the file to ingest.
        rules: Pre-loaded rules (loads from file if None).
        classify: Whether to use LLM classification for unmatched content.
        skip_embed: Skip ChromaDB embedding (for bulk operations).
        bulk_group: Pre-grouped metadata from bulk import (song name, artist, etc.).

    Returns:
        IngestResult describing what happened.
    """
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return IngestResult(success=False, source=file_path, error="File not found")
    if not path.is_file():
        return IngestResult(success=False, source=file_path, error="Not a file")

    file_type = detect_file_type(path)
    if rules is None:
        rules = load_rules()

    # Step 1: Try rule matching
    rule = match_rule(path, rules)

    # Step 2: If no rule matched and it's text, try LLM classifier
    is_suggestion = False
    target_codex = None
    suggested_codex = ""

    if rule:
        target_codex = rule.target_codex
        if target_codex is None and classify:
            # Rule says "no direct codex — pass to classifier"
            content = _read_text_content(path)
            if content:
                target_codex, is_suggestion = classify_content(content, path.name)
                if is_suggestion:
                    suggested_codex = target_codex or ""
                    target_codex = "Codex-General"  # file in General for now
    elif classify and file_type in ("text", "code", "pdf"):
        content = _read_text_content(path)
        if content:
            target_codex, is_suggestion = classify_content(content, path.name)
            if is_suggestion:
                suggested_codex = target_codex or ""
                target_codex = "Codex-General"  # file in General for now

    # Step 3: Determine destination
    if not target_codex:
        if file_type == "audio":
            target_codex = "Codex-General"
        elif file_type in ("image", "video"):
            target_codex = "Codex-General"
        else:
            target_codex = "Codex-General"

    # Build the rule for target path
    if rule is None or rule.target_codex is None:
        # Create a synthetic rule for filing (uses target_codex from classifier if available)
        subfolder_map = {
            "audio": "audio",
            "image": "images",
            "video": "videos",
            "pdf": "documents",
        }
        structure_map = {
            "audio": "id3_artist",
        }
        _fake_subfolder = subfolder_map.get(file_type, "")
        _fake_structure = structure_map.get(file_type, "flat")
        _fake_meta = file_type in ("audio",)

        rule = type("FakeRule", (), {
            "target_codex": target_codex,
            "target_subfolder": _fake_subfolder,
            "target_structure": _fake_structure,
            "target_metadata": _fake_meta,
        })()

    # Step 4: Extract metadata (for audio especially)
    audio_meta: Dict[str, str] = {}
    if file_type == "audio":
        audio_meta = extract_audio_metadata(path)
        # Override with bulk group data if provided
        if bulk_group:
            audio_meta.update({k: v for k, v in bulk_group.items() if v})

    song_name = audio_meta.get("song_name", "") or bulk_group.get("song_name", "") if bulk_group else audio_meta.get("song_name", "")

    # Step 5: Build target directory
    target_dir = build_target_path(
        rule,
        path.name,
        song_name=song_name or path.stem,
        artist=audio_meta.get("artist", ""),
        album=audio_meta.get("album", ""),
    )
    target_dir.mkdir(parents=True, exist_ok=True)

    # Step 6: Copy file
    dest_path = target_dir / path.name
    try:
        if path.resolve() != dest_path.resolve():
            shutil.copy2(str(path), str(dest_path))
    except Exception as exc:
        return IngestResult(
            success=False,
            source=str(path),
            error=f"Failed to copy: {exc}",
        )

    # Step 7: Write metadata sidecar (for audio / metadata=True)
    if file_type == "audio" or getattr(rule, "target_metadata", False):
        style_prompt = ""
        lyrics_file = ""

        # Check for companion files in the source directory
        companions = find_companion_files(path.parent, path.stem)
        if companions:
            for comp_key, comp_path in companions.items():
                # Copy companion files to the target dir
                comp_dest = target_dir / comp_path.name
                try:
                    shutil.copy2(str(comp_path), str(comp_dest))
                except Exception:
                    pass
                if "lyric" in comp_key:
                    lyrics_file = comp_path.name
                if "style" in comp_key or "prompt" in comp_key:
                    style_prompt = comp_path.read_text(encoding="utf-8")[:2000]
                if comp_key in (".md",):
                    # Generic metadata markdown — read for style prompt
                    content = comp_path.read_text(encoding="utf-8")
                    if "style" in content.lower() or "prompt" in content.lower():
                        style_prompt = content[:2000]

        meta_content = build_metadata_content(
            rule,
            path,
            song_name=song_name or path.stem,
            artist=audio_meta.get("artist", ""),
            album=audio_meta.get("album", ""),
            genre=audio_meta.get("genre", ""),
            year=audio_meta.get("year", ""),
            style_prompt=style_prompt,
            lyrics_file=lyrics_file,
        )
        meta_path = target_dir / f"{path.stem}--metadata.md"
        meta_path.write_text(meta_content, encoding="utf-8")

    relative_dest = str(dest_path.relative_to(ATHENAEUM_ROOT))

    # Step 8: Embed into ChromaDB
    if not skip_embed:
        _embed_into_chroma(str(dest_path), target_codex)

    action = "suggested" if suggested_codex else "ingested"

    return IngestResult(
        success=True,
        source=str(path),
        destination=relative_dest,
        codex=target_codex,
        rule_name=getattr(rule, "name", "auto-detect"),
        suggested_codex=suggested_codex,
        action=action,
    )


# ---------------------------------------------------------------------------
# Ingest a URL
# ---------------------------------------------------------------------------


def ingest_url(url: str, *, rules: Optional[List[IngestRule]] = None) -> IngestResult:
    """Scrape a URL and ingest the content into the Athenaeum."""
    if rules is None:
        rules = load_rules()

    title, content = scrape_url(url)
    if not content:
        return IngestResult(success=False, source=url, error="Failed to scrape URL")

    # Write content to a temp file first to run through the pipeline
    filename = _url_to_filename(url, title)
    tmp = Path(tempfile.mkdtemp()) / filename
    tmp.write_text(content, encoding="utf-8")

    result = ingest_file(str(tmp), rules=rules)
    # Update source to the original URL
    result.source = url

    # Clean up temp
    try:
        tmp.unlink()
        tmp.parent.rmdir()
    except Exception:
        pass

    return result


def _url_to_filename(url: str, title: Optional[str] = None) -> str:
    """Generate a safe filename from a URL."""
    import re

    if title:
        safe = re.sub(r"[^a-zA-Z0-9_\- ]+", "", title)[:60]
        return f"{_timestamp()}--{safe.strip().replace(' ', '_')}.md"
    # Fallback: use domain + path
    from urllib.parse import urlparse

    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "").split(".")[0]
    path = parsed.path.strip("/").replace("/", "-")[:40]
    return f"{_timestamp()}--{domain}_{path}.md"


# ---------------------------------------------------------------------------
# Bulk import
# ---------------------------------------------------------------------------


def ingest_bulk(
    directory: str,
    *,
    rules: Optional[List[IngestRule]] = None,
    classify: bool = True,
) -> List[IngestResult]:
    """Ingest an entire directory, grouping files by base name.

    For audio files, groups companion files (.txt, .md) with the audio.

    Args:
        directory: Path to directory to scan.
        rules: Pre-loaded rules.
        classify: Whether to use LLM classification.

    Returns:
        List of IngestResult for each file processed.
    """
    root = Path(directory).expanduser().resolve()
    if not root.is_dir():
        return [IngestResult(success=False, source=directory, error="Directory not found")]

    if rules is None:
        rules = load_rules()

    # Collect all files, grouped by stem
    all_files: List[Path] = []
    for f in root.rglob("*"):
        if f.is_file() and f.suffix.lower() in ALL_KNOWN_EXTS:
            all_files.append(f)

    # Group by stem for companion detection
    from collections import defaultdict

    by_stem: Dict[str, List[Path]] = defaultdict(list)
    for f in all_files:
        by_stem[f.stem].append(f)

    results: List[IngestResult] = []

    for stem, files in by_stem.items():
        # Separate audio from non-audio
        audio_files = [f for f in files if f.suffix.lower() in AUDIO_EXTS]
        text_files = [f for f in files if f.suffix.lower() in TEXT_EXTS]
        other_files = [f for f in files if f not in audio_files and f not in text_files]

        if audio_files:
            # Process audio first with bulk_group metadata
            for af in audio_files:
                result = ingest_file(
                    str(af),
                    rules=rules,
                    classify=classify,
                    bulk_group={"song_name": stem},
                )
                results.append(result)
        else:
            # No audio — process each non-text file individually,
            # and do text classification for the first text file
            for f in other_files:
                results.append(ingest_file(str(f), rules=rules, classify=classify))

            if text_files:
                # Use the first text file for classification, rest file alongside
                first = True
                for tf in text_files:
                    results.append(
                        ingest_file(
                            str(tf),
                            rules=rules,
                            classify=classify,
                            bulk_group={"song_name": stem} if first else None,
                        )
                    )
                    first = False

    return results


# ---------------------------------------------------------------------------
# Embed into ChromaDB
# ---------------------------------------------------------------------------


def _embed_into_chroma(file_path: str, codex: str) -> bool:
    """Embed a file into the Pantheon ChromaDB.

    This is a lightweight helper; if the Pantheon plugin is loaded it
    handles this via its own embedder. If not, we try direct.
    """
    try:
        # First try via the plugin if available
        from hermes_constants import get_hermes_home  # noqa: PLC0415
    except ImportError:
        logger.debug("Not running inside Hermes — skipping ChromaDB embed")
        return False

    # We're inside Hermes; try to use the active memory provider
    # If it's the Pantheon provider, its embed_file is on the provider
    # But we can also call directly
    try:
        from plugins.pantheon import PantheonMemoryProvider  # noqa: PLC0415

        # Create a lightweight embedder directly if needed
        pass
    except ImportError:
        pass

    # For now, log it — the Demeter watcher or periodic job will re-embed
    # This prevents double-embedding in the same session
    logger.info("File ingested: %s → %s (embed deferred to Demeter)", file_path, codex)
    return True


# ---------------------------------------------------------------------------
# Read text content from various file types
# ---------------------------------------------------------------------------


def _read_text_content(path: Path) -> Optional[str]:
    """Try to extract text content from a file."""
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            try:
                import pymupdf

                doc = pymupdf.open(str(path))
                text = "\n".join(page.get_text() for page in doc)
                doc.close()
                return text[:5000]
            except ImportError:
                return None
        return path.read_text(encoding="utf-8", errors="replace")[:5000]
    except Exception:
        return None
