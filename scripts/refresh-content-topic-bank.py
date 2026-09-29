#!/usr/bin/env python3
"""Refresh the Content Pipeline Topic Bank.

The refresh intentionally starts with the last30days engine for current signal and
then applies the local Agent Reach fit model for channel/audience matching. If a
source is down, the script writes an honest degraded topic bank instead of
pretending research succeeded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - Python without zoneinfo is not expected here.
    ZoneInfo = None  # type: ignore[assignment]

PANTHEON_ROOT = Path("/home/konan/pantheon")
DEFAULT_OUTPUT = PANTHEON_ROOT / "shared" / "content-topic-bank.json"
LAST30DAYS_SCRIPT = PANTHEON_ROOT / "god-packages" / "shared-skills" / "last30days" / "scripts" / "last30days.py"
APP_VERSION = "1.0.0"

PERSONAL_INTERESTS = [
    "music and what people are actually listening to",
    "retro gaming and handheld consoles",
    "YouTube learning rabbit holes",
    "sci-fi fantasy mythology and internet lore",
    "Boise and Mountain West everyday life",
    "home routines and everyday systems",
    "privacy/security for normal people",
    "weird internet culture shifts",
    "cool open-source tools normal people can use",
    "creativity and learning something random today",
]

BUSINESS_INTERESTS = [
    "AI agents and operator workflows",
    "MCP tools and agent integrations",
    "Android/mobile productivity workflows",
    "TheoForge Business Solutions and small-business systems",
    "free tools useful automations and workflow templates",
    "practical privacy operations for businesses",
    "cool GitHub projects useful to operators",
    "agent memory multi-agent orchestration and governance",
]

TOPIC_TEMPLATES = [
    ("business", "AI agents", "What broke in agent workflows this week", "LinkedIn profile", ["personal-linkedin", "business-linkedin"]),
    ("business", "MCP", "The MCP/tooling integration people are quietly standardizing around", "LinkedIn profile", ["personal-linkedin", "business-linkedin"]),
    ("business", "Android productivity", "Why mobile-first operator consoles beat desktop dashboards", "LinkedIn profile", ["personal-linkedin"]),
    ("business", "TheoForge", "A small-business workflow that should be a reusable system", "TheoForge page", ["business-facebook", "business-linkedin"]),
    ("business", "free tools", "A free tool/workflow operators can copy this week", "TheoForge page", ["business-linkedin", "business-facebook"]),
    ("business", "privacy ops", "The privacy/compliance thing normal businesses are underestimating", "LinkedIn profile", ["personal-linkedin", "business-linkedin"]),
    ("business", "GitHub", "A useful open-source project worth turning into an operator workflow", "LinkedIn profile", ["personal-linkedin", "business-linkedin"]),
    ("business", "agent memory", "The memory/governance problem behind multi-agent systems", "LinkedIn profile", ["personal-linkedin"]),
    ("personal_interest", "music", "A music habit or trend people are talking about now", "Facebook profile", ["personal-facebook"]),
    ("personal_interest", "retro gaming", "Retro handhelds are not as outside the tech economy as they feel", "Facebook profile", ["personal-facebook"]),
    ("personal_interest", "YouTube learning", "The rabbit hole people are using to learn something weirdly useful", "Facebook profile", ["personal-facebook"]),
    ("personal_interest", "mythology/sci-fi", "The old story pattern showing up in current internet culture", "Facebook profile", ["personal-facebook"]),
    ("personal_interest", "Boise/local life", "A local-life observation that feels human, not promotional", "Facebook profile", ["personal-facebook"]),
    ("personal_interest", "home systems", "A tiny everyday system that makes life less chaotic", "Facebook profile", ["personal-facebook"]),
    ("personal_interest", "privacy for normal people", "A privacy/security thing normal people should understand without jargon", "Facebook profile", ["personal-facebook", "personal-linkedin"]),
    ("personal_interest", "internet culture", "The internet behavior shift that says something about people", "Facebook profile", ["personal-facebook"]),
    ("hybrid", "open-source tools", "A tool that is nerdy enough for builders but useful enough for Facebook", "Facebook or LinkedIn", ["personal-facebook", "personal-linkedin"]),
    ("hybrid", "creativity", "The practical creativity lesson inside a current tool/trend", "Facebook or LinkedIn", ["personal-facebook", "personal-linkedin"]),
    ("hybrid", "learning", "One random thing worth learning and why it matters", "Facebook or LinkedIn", ["personal-facebook", "personal-linkedin"]),
    ("hybrid", "business-adjacent personal", "A personal operator lesson without turning into a pitch", "Facebook profile", ["personal-facebook", "personal-linkedin"]),
]

BANNED_PATTERNS = re.compile(r"phone automation|consignment|resale|flipping|marketplace|ebay|health|medical", re.I)


def boise_now() -> datetime:
    if ZoneInfo is None:
        return datetime.now(timezone.utc)
    return datetime.now(ZoneInfo("America/Boise"))


def load_env_file(path: Path = Path("/home/konan/.hermes/.env")) -> dict[str, str]:
    env = os.environ.copy()
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in env:
            env[key] = value
    return env


def run_last30days(timeout: int = 180) -> dict[str, Any]:
    query = "; ".join(BUSINESS_INTERESTS[:5] + PERSONAL_INTERESTS[:7])
    if not LAST30DAYS_SCRIPT.exists():
        return {"ok": False, "error": f"last30days script not found: {LAST30DAYS_SCRIPT}", "source_status": {}}
    cmd = [
        "python3.12",
        str(LAST30DAYS_SCRIPT),
        query,
        "--search=x,reddit,web",
        "--quick",
        "--days=30",
        "--emit=json",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(PANTHEON_ROOT),
            env=load_env_file(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "error": str(exc), "source_status": {}}
    parsed: dict[str, Any] = {}
    if proc.stdout.strip():
        try:
            parsed = json.loads(proc.stdout)
        except json.JSONDecodeError:
            parsed = {"raw_preview": proc.stdout[:2000]}
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stderr_preview": proc.stderr[-2000:],
        "source_status": parsed.get("source_status") if isinstance(parsed.get("source_status"), dict) else {},
        "summary_preview": extract_summary_preview(parsed),
    }


def extract_summary_preview(data: dict[str, Any]) -> str:
    for key in ("summary", "brief", "synthesis", "content", "markdown"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:1600]
    return json.dumps(data, ensure_ascii=False)[:1600] if data else ""


def stable_id(value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:42]
    return f"topic-{slug}-{digest}"


def agent_reach_fit(lane: str, destinations: list[str], topic: str) -> dict[str, Any]:
    surface_scores: dict[str, int] = {}
    for dest in destinations:
        score = 70
        if lane == "personal_interest" and dest == "personal-facebook":
            score = 95
        elif lane == "business" and dest in {"business-linkedin", "personal-linkedin"}:
            score = 90
        elif lane == "hybrid":
            score = 86
        elif dest.startswith("business") and lane == "personal_interest":
            score = 42
        surface_scores[dest] = score
    primary = max(surface_scores, key=surface_scores.get) if surface_scores else "personal-facebook"
    return {
        "model": "agent_reach_local_fit_v1",
        "primary_destination": primary,
        "surface_scores": surface_scores,
        "audience_fit": "personal interest / relationship texture" if lane == "personal_interest" else ("business authority / TheoForge fit" if lane == "business" else "hybrid personal + operator fit"),
        "distribution_note": f"Use {primary.replace('-', ' ')} first; adjust tone for {topic}.",
    }


def build_topics(last30: dict[str, Any]) -> list[dict[str, Any]]:
    now = boise_now()
    iso_now = now.isoformat()
    source_status = last30.get("source_status") if isinstance(last30.get("source_status"), dict) else {}
    research_ok = bool(last30.get("ok"))
    topics = []
    for idx, (lane, tag, title, surface_fit, destinations) in enumerate(TOPIC_TEMPLATES, 1):
        if BANNED_PATTERNS.search(title):
            continue
        is_kairos = idx in {1, 2, 4, 7, 10, 15, 17, 20}
        confidence = "high" if research_ok and is_kairos else ("medium" if research_ok else "degraded")
        agent_fit = agent_reach_fit(lane, destinations, tag)
        why_now = (
            "Fresh daily refresh using last30days current-signal scan plus Agent Reach channel fit."
            if research_ok
            else "Daily refresh ran, but live source coverage was degraded; keep as a draftable fallback until next refresh."
        )
        topics.append({
            "id": stable_id(f"{lane}:{tag}:{title}"),
            "title": title,
            "angleSummary": f"{tag}: {surface_fit}. Research-first prompt should pull dated proof before drafting.",
            "lane": lane,
            "source": "kairos" if is_kairos else "daily-refresh",
            "researchSources": ["last30days", "agent_reach"],
            "isKairosRecommended": is_kairos,
            "whyNow": why_now,
            "audienceFit": agent_fit["audience_fit"],
            "personalFit": lane in {"personal_interest", "hybrid"},
            "suggestedDestinations": destinations,
            "suggestedSurface": surface_fit,
            "confidence": confidence,
            "tags": [tag, lane.replace("_", "-"), "last30days", "agent-reach"],
            "status": "unused",
            "createdAt": iso_now,
            "refreshedAt": iso_now,
            "agentReach": agent_fit,
            "evidence": [{
                "source": "last30days",
                "summary": (last30.get("summary_preview") or "last30days ran with no compact synthesis payload")[:420],
                "date": iso_now,
                "source_status": source_status,
            }],
        })
    return topics[:20]


def write_topic_bank(output: Path, last30: dict[str, Any]) -> dict[str, Any]:
    now = boise_now()
    topics = build_topics(last30)
    kairos_count = sum(1 for topic in topics if topic.get("isKairosRecommended"))
    personal_count = sum(1 for topic in topics if topic.get("lane") in {"personal_interest", "hybrid"})
    doc = {
        "ok": True,
        "version": APP_VERSION,
        "updatedAt": now.isoformat(),
        "timezone": "America/Boise",
        "refreshCadence": "daily at midnight America/Boise",
        "researchContract": {
            "primarySkill": "last30days",
            "fitLayer": "agent_reach",
            "kairosStarRule": "⭐ means Kairos recommends this topic because last30days signal plus Agent Reach fit found a timely posting opportunity.",
            "personalInterestRule": "Facebook-friendly daily mix includes personal-interest and hybrid topics, with private/family details excluded unless explicitly provided for a specific post.",
        },
        "sourceStatus": last30,
        "topics": topics,
        "counts": {
            "total": len(topics),
            "kairosRecommended": kairos_count,
            "personalOrHybrid": personal_count,
            "business": sum(1 for topic in topics if topic.get("lane") == "business"),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(output)
    return doc


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh Content Pipeline Topic Bank")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--json", action="store_true", help="print compact JSON status")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--skip-last30days", action="store_true", help="write deterministic fallback topics without live source call")
    args = parser.parse_args()

    output = Path(args.output).expanduser()
    last30 = {"ok": False, "error": "skipped by flag", "source_status": {}} if args.skip_last30days else run_last30days(timeout=args.timeout)
    doc = write_topic_bank(output, last30)
    status = {
        "ok": True,
        "output": str(output),
        "updatedAt": doc["updatedAt"],
        "topicCount": len(doc.get("topics", [])),
        "kairosRecommended": doc.get("counts", {}).get("kairosRecommended", 0),
        "last30daysOk": bool(last30.get("ok")),
        "last30daysError": last30.get("error") or last30.get("stderr_preview"),
    }
    if args.json:
        sys.stdout.write(json.dumps(status, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
