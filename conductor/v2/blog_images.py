"""Blog/social image generation helpers for Pantheon Conductor.

Hermes' configured image-generation provider is the primary backend. This lets
Pantheon use ChatGPT/Codex OAuth through Hermes' ``openai-codex`` image provider
without requiring a separate ``OPENAI_API_KEY``. Direct OpenAI API-key support is
kept as a secondary compatibility path. If no real provider succeeds, the helper
produces a clearly-labeled local TheoForge SVG card so operator-selected image
generation still creates a concrete preview artifact without pretending AI was
used.
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
import shutil
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_STORAGE_DIR = "/home/konan/pantheon/blog-queue/images"
DEFAULT_MODEL = "gpt-image-1"
DEFAULT_SIZE = "1536x1024"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def slugify(value: str, max_len: int = 80) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug[:max_len].strip("-") or "blog-featured-image"


def build_featured_image_prompt(title: str, body: str) -> str:
    excerpt = re.sub(r"\s+", " ", str(body or "")).strip()[:1800]
    return textwrap.dedent(
        f"""
        Create a professional TheoForge Business Solutions featured image for a blog post.

        Blog title: {title}
        Article excerpt: {excerpt}

        Visual direction:
        - clean modern business-operations aesthetic
        - subtle forge/craft/workflow metaphor, not fantasy art
        - useful, human, proof-forward tone
        - dark navy / blue / green palette with warm highlights
        - leave safe negative space for a headline overlay
        - no fake logos, fake UI screenshots, testimonials, awards, statistics, or long embedded text
        - suitable as a blog hero and social preview image
        """
    ).strip()


def _image_output_dir(*, workflow_id: str, title: str, storage_dir: str | None = None) -> Path:
    root = Path(storage_dir or os.environ.get("BLOG_IMAGE_STORAGE_DIR") or os.environ.get("AD_IMAGE_STORAGE_DIR") or DEFAULT_STORAGE_DIR).expanduser()
    safe = f"{workflow_id}-{slugify(title, 54)}"
    return root / safe


def _write_metadata(output_dir: Path, metadata: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")


def _generate_local_card(*, title: str, prompt: str, output_dir: Path, file_name: str = "featured.svg", variant_label: str | None = None) -> dict[str, Any]:
    """Generate a dependency-free local SVG card for dashboard preview."""
    label = variant_label or "Generated image card"
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / Path(file_name).with_suffix(".svg").name
    safe_title = textwrap.shorten(re.sub(r"\s+", " ", str(title or "TheoForge image")).strip(), width=92, placeholder="…")
    safe_prompt = textwrap.shorten(re.sub(r"\s+", " ", str(prompt or "")).strip(), width=170, placeholder="…")

    def xml_escape(value: str) -> str:
        return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630" role="img" aria-label="{xml_escape(label)}">
  <rect width="1200" height="630" fill="#07111f"/>
  <rect x="0" y="0" width="1200" height="630" fill="#0f2740" opacity="0.72"/>
  <circle cx="930" cy="160" r="260" fill="none" stroke="#74d6ff" stroke-opacity="0.42" stroke-width="5"/>
  <circle cx="1010" cy="360" r="330" fill="none" stroke="#4ade80" stroke-opacity="0.30" stroke-width="4"/>
  <circle cx="760" cy="470" r="260" fill="none" stroke="#a78bfa" stroke-opacity="0.28" stroke-width="4"/>
  <rect x="58" y="54" width="230" height="50" rx="24" fill="#0f2740" stroke="#74d6ff" stroke-width="2"/>
  <text x="78" y="88" font-family="Inter, DejaVu Sans, Arial, sans-serif" font-size="25" font-weight="800" fill="#dff7ff">THEOFORGE</text>
  <text x="72" y="170" font-family="Inter, DejaVu Sans, Arial, sans-serif" font-size="58" font-weight="900" fill="#e5eefc">{xml_escape(safe_title)}</text>
  <text x="76" y="496" font-family="Inter, DejaVu Sans, Arial, sans-serif" font-size="29" font-weight="700" fill="#9fb0cf">{xml_escape(label)} · local preview</text>
  <text x="76" y="542" font-family="Inter, DejaVu Sans, Arial, sans-serif" font-size="28" font-weight="700" fill="#74d6ff">Prompt fingerprint: {digest}</text>
  <text x="76" y="586" font-family="Inter, DejaVu Sans, Arial, sans-serif" font-size="19" font-weight="500" fill="#b8c7dd">{xml_escape(safe_prompt)}</text>
</svg>'''
    image_path.write_text(svg, encoding="utf-8")
    return {
        "ok": True,
        "status": "local_svg_generated",
        "provider": "local-svg-card",
        "model": "stdlib-svg-theoforge-card",
        "image_path": str(image_path),
        "alt": f"TheoForge generated image card for {title}",
        "variant_label": variant_label,
        "prompt": prompt,
        "generated_at": utc_now(),
        "note": "OPENAI_API_KEY was not configured, so Pantheon generated a local SVG preview card instead of calling OpenAI.",
    }


def _generate_openai_image(*, prompt: str, output_dir: Path, file_name: str = "featured.png") -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    model = os.environ.get("BLOG_IMAGE_OPENAI_MODEL") or os.environ.get("AD_IMAGE_OPENAI_MODEL") or DEFAULT_MODEL
    size = os.environ.get("BLOG_IMAGE_SIZE") or DEFAULT_SIZE
    payload = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "n": 1,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/images/generations",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"OpenAI image generation failed HTTP {exc.code}: {body}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"OpenAI image generation failed: {exc}") from exc

    item = (data.get("data") or [{}])[0]
    image_bytes: bytes
    if item.get("b64_json"):
        image_bytes = base64.b64decode(item["b64_json"])
    elif item.get("url"):
        with urllib.request.urlopen(str(item["url"]), timeout=120) as img_resp:
            image_bytes = img_resp.read()
    else:
        raise RuntimeError("OpenAI image generation returned no b64_json or url")

    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / file_name
    image_path.write_bytes(image_bytes)
    return {
        "ok": True,
        "status": "openai_image_generated",
        "provider": "openai",
        "model": model,
        "size": size,
        "image_path": str(image_path),
        "prompt": prompt,
        "generated_at": utc_now(),
    }



def _hermes_agent_root() -> str:
    return os.environ.get("HERMES_AGENT_ROOT") or "/home/konan/.hermes/hermes-agent"


def _local_image_suffix(value: str) -> str:
    parsed = urllib.parse.urlparse(str(value or ""))
    suffix = Path(parsed.path or value).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return suffix
    return ".png"


def _materialize_provider_image(image_ref: str, *, output_dir: Path, file_name: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = _local_image_suffix(image_ref)
    target = output_dir / Path(file_name).with_suffix(suffix).name
    lowered = str(image_ref or "").lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        with urllib.request.urlopen(str(image_ref), timeout=180) as response:
            target.write_bytes(response.read())
        return target

    source = Path(str(image_ref)).expanduser().resolve()
    if not source.is_file():
        raise RuntimeError(f"Hermes image provider returned a non-file image reference: {image_ref}")
    if source.resolve() != target.resolve():
        shutil.copyfile(source, target)
    return target


def _generate_hermes_image(
    *, prompt: str, output_dir: Path, file_name: str = "featured.png", aspect_ratio: str = "landscape"
) -> dict[str, Any]:
    """Generate an image through Hermes' configured image_gen provider stack.

    This is the ChatGPT OAuth path when ``image_gen.provider`` is
    ``openai-codex``. The helper intentionally goes through Hermes plugin
    discovery and provider dispatch instead of reading ``auth.json`` directly.
    """
    agent_root = _hermes_agent_root()
    if agent_root not in sys.path:
        sys.path.insert(0, agent_root)

    try:
        from agent.image_gen_registry import get_active_provider
        from hermes_cli.plugins import _ensure_plugins_discovered
    except Exception as exc:
        raise RuntimeError(f"Hermes image provider stack is not importable: {exc}") from exc

    _ensure_plugins_discovered()
    provider = get_active_provider()
    if provider is None:
        raise RuntimeError("No active Hermes image_gen provider is configured or available")

    result = provider.generate(prompt=prompt, aspect_ratio=aspect_ratio)
    if not isinstance(result, dict):
        raise RuntimeError(f"Hermes image provider {provider.name!r} returned non-dict result")
    if not result.get("success") or not result.get("image"):
        error = result.get("error") or "unknown image generation error"
        raise RuntimeError(f"Hermes image provider {provider.name!r} failed: {error}")

    image_path = _materialize_provider_image(str(result["image"]), output_dir=output_dir, file_name=file_name)
    return {
        "ok": True,
        "status": "hermes_image_generated",
        "provider": result.get("provider") or provider.name,
        "model": result.get("model") or provider.default_model(),
        "image_path": str(image_path),
        "alt": "AI-generated TheoForge image",
        "prompt": prompt,
        "generated_at": utc_now(),
        "hermes_image_provider": provider.name,
        "source_image_ref": str(result.get("image")),
    }


def _generate_real_image(
    *, prompt: str, output_dir: Path, file_name: str = "featured.png", aspect_ratio: str = "landscape"
) -> dict[str, Any]:
    if os.environ.get("PANTHEON_IMAGE_FORCE_LOCAL", "").lower() in {"1", "true", "yes"}:
        raise RuntimeError("PANTHEON_IMAGE_FORCE_LOCAL is enabled")
    try:
        return _generate_hermes_image(
            prompt=prompt,
            output_dir=output_dir,
            file_name=file_name,
            aspect_ratio=aspect_ratio,
        )
    except Exception as hermes_exc:
        if os.environ.get("OPENAI_API_KEY"):
            try:
                return _generate_openai_image(prompt=prompt, output_dir=output_dir, file_name=file_name)
            except Exception as openai_exc:
                raise RuntimeError(
                    f"Hermes image provider failed ({hermes_exc}); OpenAI API fallback failed ({openai_exc})"
                ) from openai_exc
        raise


def _fallback_card(
    *, title: str, prompt: str, output_dir: Path, fallback_reason: Exception | str,
    file_name: str = "featured.svg", variant_label: str | None = None,
) -> dict[str, Any]:
    result = _generate_local_card(
        title=title,
        prompt=prompt,
        output_dir=output_dir,
        file_name=file_name,
        variant_label=variant_label,
    )
    result["fallback_reason"] = str(fallback_reason)
    result["note"] = "Real image generation failed, so Pantheon generated a local SVG preview card."
    return result


def generate_blog_featured_image(*, title: str, body: str, workflow_id: str, storage_dir: str | None = None) -> dict[str, Any]:
    output_dir = _image_output_dir(workflow_id=workflow_id, title=title, storage_dir=storage_dir)
    prompt = build_featured_image_prompt(title, body)
    try:
        result = _generate_real_image(prompt=prompt, output_dir=output_dir)
    except Exception as exc:
        result = _fallback_card(title=title, prompt=prompt, output_dir=output_dir, fallback_reason=exc)
    metadata = {**result, "title": title, "workflow_id": workflow_id, "mime_type": mimetypes.guess_type(result.get("image_path", ""))[0] or "image/png"}
    _write_metadata(output_dir, metadata)
    return metadata


def generate_blog_featured_image_variants(*, title: str, body: str, workflow_id: str, variant_count: int = 3, storage_dir: str | None = None) -> dict[str, Any]:
    output_dir = _image_output_dir(workflow_id=workflow_id, title=title, storage_dir=storage_dir)
    base_prompt = build_featured_image_prompt(title, body)
    directions = [
        "Option 1: abstract workflow-forge composition with luminous process lines and generous negative space.",
        "Option 2: warm human-operations desk scene with subtle craft/process metaphor, no fake UI.",
        "Option 3: bold editorial social-preview graphic with geometric depth and strong focal contrast.",
    ]
    items: list[dict[str, Any]] = []
    for idx in range(max(1, min(int(variant_count or 3), 4))):
        label = f"Option {idx + 1}"
        prompt = f"{base_prompt}\n\n{directions[idx % len(directions)]}"
        file_name = f"featured-option-{idx + 1}.png"
        try:
            result = _generate_real_image(prompt=prompt, output_dir=output_dir, file_name=file_name)
            result["variant_label"] = label
        except Exception as exc:
            result = _fallback_card(
                title=title,
                prompt=prompt,
                output_dir=output_dir,
                fallback_reason=exc,
                file_name=file_name,
                variant_label=label,
            )
        metadata = {
            **result,
            "title": title,
            "workflow_id": workflow_id,
            "variant_index": idx,
            "label": label,
            "mime_type": mimetypes.guess_type(result.get("image_path", ""))[0] or "image/png",
        }
        items.append(metadata)
    package = {
        "ok": any(item.get("ok") for item in items),
        "status": "image_variants_generated",
        "title": title,
        "workflow_id": workflow_id,
        "generated_at": utc_now(),
        "selected_image_path": next((item.get("image_path") for item in items if item.get("ok") and item.get("image_path")), None),
        "items": items,
    }
    _write_metadata(output_dir, {**package, "prompt": base_prompt})
    return package


SOCIAL_DEFAULT_STORAGE_DIR = "/home/konan/pantheon/phone-queue/images"


def build_social_image_prompt(*, text: str, surface: str) -> str:
    excerpt = re.sub(r"\s+", " ", str(text or "")).strip()[:1400]
    platform = str(surface or "social").replace("-", " ")
    return textwrap.dedent(
        f"""
        Create a professional social-media graphic for a {platform} post.

        Post copy excerpt: {excerpt}

        Visual direction:
        - clean, scroll-stopping social feed image
        - human, useful, curiosity-forward tone
        - no fake app UI, fake metrics, fake screenshots, testimonials, or invented logos
        - avoid long embedded text; use visual metaphor and negative space instead
        - dark navy / blue / green palette with warm accent highlights
        - suitable for Facebook and LinkedIn feed attachment previews
        - brand-safe for TheoForge Business Solutions when business-facing, casual and non-salesy when personal-facing
        """
    ).strip()


def _social_output_dir(*, text: str, workflow_id: str, surface: str, storage_dir: str | None = None) -> Path:
    root = Path(storage_dir or os.environ.get("SOCIAL_IMAGE_STORAGE_DIR") or SOCIAL_DEFAULT_STORAGE_DIR).expanduser()
    return root / f"{workflow_id}-{slugify(surface or 'social', 28)}-{hashlib.sha256(str(text or '').encode('utf-8')).hexdigest()[:10]}"


def generate_social_post_image(*, text: str, workflow_id: str, surface: str, storage_dir: str | None = None) -> dict[str, Any]:
    title = f"{surface or 'social'} social image"
    output_dir = _social_output_dir(text=text, workflow_id=workflow_id, surface=surface, storage_dir=storage_dir)
    prompt = build_social_image_prompt(text=text, surface=surface)
    try:
        result = _generate_real_image(prompt=prompt, output_dir=output_dir)
    except Exception as exc:
        result = _fallback_card(title=title, prompt=prompt, output_dir=output_dir, fallback_reason=exc)
    metadata = {
        **result,
        "surface": surface,
        "workflow_id": workflow_id,
        "mime_type": mimetypes.guess_type(result.get("image_path", ""))[0] or "image/png",
        "alt": result.get("alt") or f"Social post image for {surface or 'social'}",
    }
    _write_metadata(output_dir, metadata)
    return metadata


def generate_social_post_image_variants(*, text: str, workflow_id: str, surface: str, variant_count: int = 3, storage_dir: str | None = None) -> dict[str, Any]:
    title = f"{surface or 'social'} social image"
    output_dir = _social_output_dir(text=text, workflow_id=workflow_id, surface=surface, storage_dir=storage_dir)
    base_prompt = build_social_image_prompt(text=text, surface=surface)
    directions = [
        "Option 1: bold editorial feed graphic with geometric shapes and high-contrast focal point.",
        "Option 2: subtle human/desk/lifestyle metaphor, polished but casual, no fake UI.",
        "Option 3: abstract conversation/signal map with luminous lines and social-feed negative space.",
    ]
    items: list[dict[str, Any]] = []
    for idx in range(max(1, min(int(variant_count or 3), 4))):
        label = f"Option {idx + 1}"
        prompt = f"{base_prompt}\n\n{directions[idx % len(directions)]}"
        file_name = f"{slugify(surface or 'social', 28)}-option-{idx + 1}.png"
        try:
            result = _generate_real_image(prompt=prompt, output_dir=output_dir, file_name=file_name)
            result["variant_label"] = label
        except Exception as exc:
            result = _fallback_card(
                title=title,
                prompt=prompt,
                output_dir=output_dir,
                fallback_reason=exc,
                file_name=file_name,
                variant_label=label,
            )
        metadata = {
            **result,
            "surface": surface,
            "workflow_id": workflow_id,
            "variant_index": idx,
            "label": label,
            "mime_type": mimetypes.guess_type(result.get("image_path", ""))[0] or "image/png",
            "alt": result.get("alt") or f"Social post image for {surface or 'social'}",
        }
        items.append(metadata)
    package = {
        "ok": any(item.get("ok") for item in items),
        "status": "image_variants_generated",
        "surface": surface,
        "workflow_id": workflow_id,
        "generated_at": utc_now(),
        "selected_image_path": next((item.get("image_path") for item in items if item.get("ok") and item.get("image_path")), None),
        "items": items,
    }
    _write_metadata(output_dir, {**package, "prompt": base_prompt})
    return package
