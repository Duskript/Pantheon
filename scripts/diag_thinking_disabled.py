"""Test: does adding thinking.disabled make deepseek-v4-flash produce visible output?

The L2 loop's failure mode: model used all 800 max_tokens for reasoning_content,
emitted 0 chars of visible content. If thinking.disabled works, content should
be non-empty with max_tokens=800.
"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, "/home/konan/pantheon")
from scripts.diag_l2_one_batch import _load_opencode_go_key  # type: ignore  # noqa

api_base = "https://opencode.ai/zen/go/v1"
key = _load_opencode_go_key()

prompt = """You are an entity-and-relationship extractor.

Given conversation turns, extract entities (people, orgs, projects, tools, concepts, files, URLs) and relationships (typed connections). Return JSON only.

Turn 1: Konan decided to use Tailscale for relay-7 access. Tailscale is a WireGuard-based mesh VPN.
Turn 2: The relay-7 box runs NATS at nats://100.100.46.52:4222, which SkillClaw proxies outbound to.
Turn 3: Tallon is the recipient of the auth key for cross-tailnet access. His tailnet is digitalon01@gmail.com."""

body = json.dumps({
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": prompt}],
    "max_tokens": 800,
    "temperature": 0.2,
    "thinking": {"type": "disabled"},  # per deepseek docs
}).encode("utf-8")

req = urllib.request.Request(f"{api_base}/chat/completions", data=body, method="POST")
req.add_header("Content-Type", "application/json")
req.add_header("User-Agent", "pantheon-ichor/1.0 (lib.ichor.llm)")
req.add_header("Authorization", f"Bearer {key}")

print("=== Test: thinking=disabled, max_tokens=800 ===")
with urllib.request.urlopen(req, timeout=60) as resp:
    data = json.loads(resp.read().decode("utf-8"))
    if "choices" in data and data["choices"]:
        msg = data["choices"][0].get("message", {})
        content = msg.get("content", "")
        reasoning = msg.get("reasoning_content", "")
        print("finish_reason:", data["choices"][0].get("finish_reason"))
        print("content length:", len(content))
        print("reasoning_content length:", len(reasoning))
        print("usage:", data.get("usage"))
        print()
        print("=== content ===")
        print(content[:2000] if content else "(empty)")
        if reasoning:
            print()
            print("=== reasoning_content (first 500) ===")
            print(reasoning[:500])
