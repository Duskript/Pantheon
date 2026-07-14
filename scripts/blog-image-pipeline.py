#!/usr/bin/env python3
"""
Blog Image Pipeline — Pantheon
===============================
Takes blog post content, plans images with the LLM, generates them via
Cloudflare Workers AI or fallback backends. Returns structured output
with image paths, alt text, and placement metadata.

Usage:
    cat blog-post.md | python3 blog-image-pipeline.py --out ~/pantheon/output/blogs
    python3 blog-image-pipeline.py --file blog-post.md --out ./images
    python3 blog-image-pipeline.py --test  # Run a quick smoke test
"""

import argparse
import base64
import io
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# ── Config ──

LLM_API_URL = os.getenv("OPENCODE_GO_API_URL", "https://opencode.ai/zen/go/v1/chat/completions")
LLM_API_KEY = ""
LLM_MODEL = os.getenv("BLOG_IMAGE_LLM", "minimax-m3")

# Try env first, then fall back to Hermes auth.json credential pool
env_key = os.getenv("OPENCODE_GO_API_KEY", "")
if env_key and env_key != "***":
    LLM_API_KEY = env_key
else:
    auth_path = os.path.expanduser("~/.hermes/auth.json")
    if os.path.exists(auth_path):
        try:
            auth = json.load(open(auth_path))
            pool = auth.get("credential_pool", {})
            # Try opencode-go first, then opencode-zen for fallback
            for provider_name in ["opencode-go", "opencode-zen"]:
                creds = pool.get(provider_name, [])
                if not isinstance(creds, list):
                    continue
                for cred in creds:
                    token = cred.get("access_token", "")
                    status = cred.get("last_status", "")
                    url = cred.get("base_url", "")
                    if token and status == "ok" and len(token) > 10:
                        LLM_API_KEY = token
                        if url:
                            LLM_API_URL = url.rstrip("/") + "/chat/completions"
                        globals()["LLM_API_KEY"] = LLM_API_KEY
                        globals()["LLM_API_URL"] = LLM_API_URL
                        break
                if LLM_API_KEY:
                    break
        except (json.JSONDecodeError, KeyError, IndexError):
            pass

CF_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "6496c476b3b133a6c8096ef094728ef6")
CF_API_KEY = os.getenv("CLOUDFLARE_API_KEY", "")
CF_WORKER_URL = os.getenv("CF_WORKER_URL", "")  # e.g. https://pantheon-image-gen.example.workers.dev

DEFAULT_OUTPUT = os.getenv("BLOG_IMAGE_OUTPUT", str(Path.home() / "pantheon" / "output" / "blog-images"))

IMAGE_PRESETS = {
    "hero": {"desc": "Wide hero / banner image for top of post", "aspect": "landscape", "default_steps": 6},
    "section": {"desc": "Section illustration inline with content", "aspect": "landscape", "default_steps": 4},
    "social_square": {"desc": "Square share image for LinkedIn/Facebook/X", "aspect": "square", "default_steps": 4},
    "social_wide": {"desc": "Wide social share card (LinkedIn banner)", "aspect": "landscape", "default_steps": 4},
    "quote_bg": {"desc": "Background for a quote card", "aspect": "square", "default_steps": 4},
    "thumbnail": {"desc": "Blog listing thumbnail", "aspect": "square", "default_steps": 4},
    "divider": {"desc": "Section divider / visual separator", "aspect": "landscape", "default_steps": 3},
}

# ── LLM Interface ──

def call_llm(system_prompt: str, user_prompt: str, temperature: float = 0.7) -> str:
    """Call the configured LLM for planning/reasoning."""
    if not LLM_API_KEY:
        raise RuntimeError("OPENCODE_GO_API_KEY not set — cannot plan images without an LLM")

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": 4096,
    }

    req = urllib.request.Request(
        LLM_API_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LLM_API_KEY}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode())
            return result["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        raise RuntimeError(f"LLM API error {e.code}: {body}")
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"LLM returned unexpected response: {e}")


# ── Image Generation ──

def generate_via_cf_worker(prompt: str, preset: str, steps: int) -> bytes:
    """Generate image via Cloudflare Worker."""
    if not CF_WORKER_URL:
        raise RuntimeError("CF_WORKER_URL not set — deploy the Worker first")

    payload = json.dumps({
        "prompt": prompt,
        "preset": preset,
        "steps": steps,
        "format": "jpeg",
    }).encode()

    req = urllib.request.Request(
        CF_WORKER_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        raise RuntimeError(f"Worker error {e.code}: {body}")


def generate_via_cf_api(prompt: str, model: str = "@cf/black-forest-labs/flux-1-schnell", steps: int = 4) -> bytes:
    """Generate image via Cloudflare Workers AI REST API directly."""
    if not CF_API_KEY:
        raise RuntimeError("CLOUDFLARE_API_KEY not set — cannot call Workers AI directly")

    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{model}"
    payload = json.dumps({"prompt": prompt, "steps": steps}).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {CF_API_KEY}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode())
            image_b64 = result.get("result", {}).get("image", "")
            if not image_b64:
                raise RuntimeError("No image in Cloudflare response")
            return base64.b64decode(image_b64)
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        raise RuntimeError(f"Cloudflare API error {e.code}: {body}")


# ── Core Pipeline ──

def slugify(text: str, max_len: int = 30) -> str:
    """Convert text to a filesystem-safe slug."""
    slug = re.sub(r"[^a-zA-Z0-9\s-]", "", text.lower())
    slug = re.sub(r"\s+", "-", slug.strip())
    return slug[:max_len].rstrip("-")


def parse_image_plan(llm_output: str) -> list[dict]:
    """Parse LLM output into a structured image plan."""
    # Try JSON first
    cleaned = llm_output.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        plan = json.loads(cleaned)
        if isinstance(plan, list):
            return plan
        if isinstance(plan, dict) and "images" in plan:
            return plan["images"]
    except json.JSONDecodeError:
        pass

    # Fallback: try to extract image blocks from markdown
    images = []
    blocks = re.split(r"##+\s*", llm_output)
    for block in blocks:
        lines = block.strip().split("\n")
        if not lines or not lines[0].strip():
            continue
        entry = {"type": slugify(lines[0].strip(), 20), "prompt": "", "alt": ""}
        for line in lines[1:]:
            line = line.strip()
            if line.lower().startswith("prompt:"):
                entry["prompt"] = line[len("prompt:"):].strip()
            elif line.lower().startswith("alt:"):
                entry["alt"] = line[len("alt:"):].strip()
            elif line.lower().startswith("placement:"):
                entry["placement"] = line[len("placement:"):].strip()
            elif line.lower().startswith("preset:"):
                entry["preset"] = line[len("preset:"):].strip()
        if entry["prompt"]:
            images.append(entry)

    return images


def plan_images(blog_title: str, blog_content: str) -> list[dict]:
    """Call LLM to plan images for a blog post."""

    system_prompt = """You are a creative director for a business automation brand (TheoForge).

Your job: given a blog post, plan 2-4 images that will make the post visually engaging on social media and the blog itself.

Image types available:
- hero — Wide hero/banner for top of post, landscape aspect ratio
- section — Section illustration inline with content, landscape
- social_square — Square share image for LinkedIn/Facebook/X
- social_wide — Wide social share card
- quote_bg — Background for a quote card, square
- thumbnail — Blog listing thumbnail, square
- divider — Section divider pattern, landscape

OUTPUT FORMAT: Return ONLY a valid JSON array. No markdown, no explanation.

Each item:
{
  "type": "hero | section | social_square | social_wide | thumbnail | quote_bg | divider",
  "prompt": "Detailed image prompt describing what to generate — describe the visual metaphor, colors, mood, composition. 50-150 words. Include 'TheoForge brand colors' if appropriate.",
  "alt": "Descriptive alt text for accessibility. 10-20 words.",
  "placement": "Where this image goes — e.g. 'Top of post, before the title', 'After the second paragraph about automation benefits', 'LinkedIn share card'"
}

RULES:
- A blog post typically needs: 1 hero + 1 social_square + 1-2 section images
- Prompts must be specific: describe the scene, style, lighting, colors, and mood
- No text in images — text should be overlaid separately
- Style: clean, modern, slightly warm, business-professional, abstract where appropriate
- For TheoForge: use business/automation/forge/craftsmanship metaphors"""

    user_prompt = f"""Blog title: {blog_title}

Blog content:
{blog_content[:8000]}

Plan the images for this post. Return ONLY the JSON array."""

    output = call_llm(system_prompt, user_prompt, temperature=0.6)
    return parse_image_plan(output)


def generate_images(plan: list[dict], output_dir: Path) -> list[dict]:
    """Generate all images in the plan."""
    results = []
    output_dir.mkdir(parents=True, exist_ok=True)

    for i, item in enumerate(plan):
        preset = item.get("preset", item.get("type", "section"))
        preset_config = IMAGE_PRESETS.get(preset, IMAGE_PRESETS["section"])
        steps = preset_config.get("default_steps", 4)
        prompt = item["prompt"]
        img_type = item.get("type", preset)
        slug = slugify(img_type, 20) or f"image-{i}"
        filename = f"{i+1:02d}-{slug}.jpg"
        filepath = output_dir / filename

        print(f"  [{i+1}/{len(plan)}] Generating {img_type}...", file=sys.stderr)

        try:
            if CF_WORKER_URL:
                img_data = generate_via_cf_worker(prompt, preset, steps)
            elif CF_API_KEY:
                img_data = generate_via_cf_api(prompt, steps=steps)
            else:
                raise RuntimeError("No image generation backend configured — set CF_WORKER_URL or CLOUDFLARE_API_KEY")

            filepath.write_bytes(img_data)
            size_kb = len(img_data) / 1024

            result = {
                "type": img_type,
                "preset": preset,
                "file": str(filepath.relative_to(output_dir.parent)) if output_dir.parent else str(filepath),
                "path": str(filepath),
                "size_kb": round(size_kb, 1),
                "prompt": prompt,
                "alt": item.get("alt", ""),
                "placement": item.get("placement", ""),
            }
            results.append(result)
            print(f"    ✓ Saved ({size_kb:.0f} KB)", file=sys.stderr)

        except Exception as e:
            print(f"    ✗ Failed: {e}", file=sys.stderr)
            results.append({
                "type": img_type,
                "error": str(e),
                "prompt": prompt,
                "alt": item.get("alt", ""),
            })

    return results


# ── CLI ──

def main():
    parser = argparse.ArgumentParser(description="Blog image pipeline for Pantheon")
    parser.add_argument("--file", "-f", help="Path to blog post markdown file")
    parser.add_argument("--title", "-t", help="Blog post title (auto-detected from content if not provided)")
    parser.add_argument("--out", "-o", default=DEFAULT_OUTPUT, help=f"Output directory (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--plan-only", action="store_true", help="Only plan images, don't generate them")
    parser.add_argument("--test", action="store_true", help="Run a quick smoke test with a dummy blog post")
    parser.add_argument("--json", action="store_true", help="Output result as JSON only")
    parser.add_argument("--print-prompts", action="store_true", help="Print the planned prompts to stdout, don't generate")
    args = parser.parse_args()

    if args.test:
        blog_content = """# How Small Businesses Can Automate Admin Work

Administrative tasks eat up 40% of a small business owner's week. From invoicing to scheduling to follow-up emails, the busywork never ends.

But what if you could automate most of it?

## The Problem

Most small business owners wear every hat. You're the CEO, accountant, marketer, and customer support team all at once. That leaves zero time for strategic growth.

## The Solution: Workflow Automation

Tools like TheoForge's visual editor let you build custom automations without writing a single line of code. Connect your tools, set your triggers, and let the system handle the repetitive work.

## Real Results

One SaaS founder automated their entire client onboarding flow — from contract signing to Slack channel setup to first invoice — saving 12 hours per week.

## Getting Started

Start with one process. Map it out. Automate one step. Then another. Before you know it, you've bought back your week."""
        blog_title = "How Small Businesses Can Automate Admin Work"
        print("🧪 Test mode — using sample blog post\n", file=sys.stderr)
    else:
        if args.file:
            blog_content = Path(args.file).read_text()
        else:
            blog_content = sys.stdin.read()

        if not blog_content.strip():
            print("Error: No blog content provided. Use --file or pipe content to stdin.", file=sys.stderr)
            sys.exit(1)

        blog_title = args.title or ""

    # Extract title from content if not provided
    if not blog_title:
        title_match = re.search(r"^#\s+(.+)$", blog_content, re.MULTILINE)
        blog_title = title_match.group(1).strip() if title_match else "Untitled Blog Post"

    output_dir = Path(args.out)

    print(f"📝 Planning images for: {blog_title}", file=sys.stderr)
    print(f"   Content length: {len(blog_content)} chars", file=sys.stderr)
    print(f"   Output dir: {output_dir}", file=sys.stderr)
    print(file=sys.stderr)

    try:
        plan = plan_images(blog_title, blog_content)
    except RuntimeError as e:
        print(f"\n❌ Planning failed: {e}", file=sys.stderr)
        sys.exit(1)

    if not plan:
        print("⚠️  LLM returned empty plan — check model response", file=sys.stderr)
        sys.exit(1)

    print(f"\n🎨 Planned {len(plan)} images:", file=sys.stderr)
    for item in plan:
        print(f"   - {item.get('type', '?')}: {item.get('prompt', '')[:80]}...", file=sys.stderr)
    print(file=sys.stderr)

    if args.plan_only:
        print(json.dumps(plan, indent=2))
        return

    if args.print_prompts:
        for item in plan:
            print(json.dumps(item))
        return

    # Check if any backend is available
    if not CF_WORKER_URL and not CF_API_KEY:
        print("⚠️  No image generation backend configured.", file=sys.stderr)
        print(file=sys.stderr)
        print("Set one of these env vars to enable generation:", file=sys.stderr)
        print("  CF_WORKER_URL     — Deployed Cloudflare Worker URL", file=sys.stderr)
        print("  CLOUDFLARE_API_KEY — Cloudflare API token with Workers AI access", file=sys.stderr)
        print(file=sys.stderr)
        print("Falling back to prompt-only mode. Saving plan JSON instead.", file=sys.stderr)
        plan_file = output_dir / "image-plan.json"
        output_dir.mkdir(parents=True, exist_ok=True)
        plan_file.write_text(json.dumps(plan, indent=2))
        print(f"Plan saved to: {plan_file}", file=sys.stderr)
        if args.json:
            print(json.dumps({"plan": plan, "status": "prompts-only"}, indent=2))
        return

    results = generate_images(plan, output_dir)

    # Save manifest
    manifest = {
        "blog_title": blog_title,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "total": len(results),
        "successful": sum(1 for r in results if "error" not in r),
        "failed": sum(1 for r in results if "error" in r),
        "images": results,
    }

    manifest_path = output_dir / "_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"\n📦 Manifest saved: {manifest_path}", file=sys.stderr)
    print(f"   Images: {manifest['successful']} generated, {manifest['failed']} failed", file=sys.stderr)
    print(file=sys.stderr)

    if manifest["failed"] > 0:
        print("Failed images:", file=sys.stderr)
        for r in results:
            if "error" in r:
                print(f"  ✗ {r['type']}: {r['error']}", file=sys.stderr)

    if args.json:
        print(json.dumps(manifest, indent=2))
    else:
        print("✅ Done!", file=sys.stderr)
        for r in results:
            if "error" not in r:
                print(f"   ✓ {r['type']} → {r['path']} ({r['size_kb']} KB)", file=sys.stderr)


if __name__ == "__main__":
    main()
