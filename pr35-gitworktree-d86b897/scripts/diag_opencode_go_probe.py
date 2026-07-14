"""Probe the opencode-go API directly to see what a successful response looks like.

Bypasses the package's _call_llm to see the raw response shape.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

api_base = "https://opencode.ai/zen/go/v1"

# Load the same key the package uses
key = os.environ.get("OPENCODE_GO_API_KEY", "").strip()
if not key:
    for line in Path("/home/konan/.hermes/.env").read_text().splitlines():
        line = line.strip()
        if line.startswith("OPENCODE_GO_API_KEY="):
            key = line.split("=", 1)[1].strip().strip('"').strip("'")
            break

print(f"key loaded: length={len(key)}, prefix={key[:8]}...")

# Test 1: trivial JSON request
prompt = 'Return a JSON object with a single key "test" set to "ok". Output ONLY the JSON, no prose.'
body = json.dumps({
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": prompt}],
    "max_tokens": 100,
    "temperature": 0.0,
}).encode("utf-8")

req = urllib.request.Request(f"{api_base}/chat/completions", data=body, method="POST")
req.add_header("Content-Type", "application/json")
req.add_header("User-Agent", "pantheon-ichor/1.0 (lib.ichor.llm)")
req.add_header("Authorization", f"Bearer {key}")

print("\n=== Test 1: trivial JSON request ===")
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        print("Top-level keys:", list(data.keys()))
        if "choices" in data:
            print(f"choices length: {len(data['choices'])}")
            if data["choices"]:
                msg = data["choices"][0].get("message", {})
                print(f"message keys: {list(msg.keys())}")
                print(f"content length: {len(msg.get('content', ''))}")
                print(f"content first 300: {msg.get('content', '')[:300]!r}")
                print(f"finish_reason: {data['choices'][0].get('finish_reason')}")
        if "usage" in data:
            print(f"usage: {data['usage']}")
        if "model" in data:
            print(f"model returned: {data['model']}")
        print("\nFull response (first 1500 chars):")
        print(json.dumps(data, indent=2)[:1500])
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")

# Test 2: the actual L2 prompt style (extract entities)
print("\n\n=== Test 2: actual L2-style prompt ===")
prompt2 = """You are an entity-and-relationship extractor.

Given a list of conversation turns, extract:
1. Entities — people, organizations, projects, tools, concepts, files, URLs.
2. Relationships — typed connections between entities.

Return JSON only, no prose, no markdown fences. Shape:
{"entities": [{"name": "...", "type": "..."}], "relationships": []}

Turn 1: Konan decided to use Tailscale for relay-7 access. Tailscale is a WireGuard-based mesh VPN.
Turn 2: The relay-7 box runs NATS at nats://100.100.46.52:4222, which SkillClaw proxies outbound to.
Turn 3: Tallon is the recipient of the auth key for cross-tailnet access."""

body2 = json.dumps({
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": prompt2}],
    "max_tokens": 800,
    "temperature": 0.2,
}).encode("utf-8")

req2 = urllib.request.Request(f"{api_base}/chat/completions", data=body2, method="POST")
req2.add_header("Content-Type", "application/json")
req2.add_header("User-Agent", "pantheon-ichor/1.0 (lib.ichor.llm)")
req2.add_header("Authorization", f"Bearer {key}")

try:
    with urllib.request.urlopen(req2, timeout=60) as resp:
        data2 = json.loads(resp.read().decode("utf-8"))
        if "choices" in data2 and data2["choices"]:
            msg = data2["choices"][0].get("message", {})
            content = msg.get("content", "")
            print(f"content length: {len(content)}")
            print(f"finish_reason: {data2['choices'][0].get('finish_reason')}")
            print(f"\ncontent (first 2000):\n{content[:2000]}")
        if "usage" in data2:
            print(f"\nusage: {data2['usage']}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
