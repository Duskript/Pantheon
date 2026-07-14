"""Diagnostic: how much output does the model want for the dense batch-5 input?

Builds the exact prompt the L2 loop would build for events 76-233, then
calls the model with max_tokens=16000 to capture its full intended output.
Reports:
- raw response length
- whether it parses as JSON
- entity/relationship count from the parsed response
- what max_tokens is sufficient (i.e., at what point does output get cut off)
"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, "/home/konan/pantheon")
from scripts.diag_l2_one_batch import _load_opencode_go_key  # type: ignore  # noqa
from lib.ichor.entities.schema import get_conn  # type: ignore  # noqa
from lib.ichor.entities.l2_llm import _events_for_batch, build_prompt  # type: ignore  # noqa

api_base = "https://opencode.ai/zen/go/v1"
key = _load_opencode_go_key()

# Same query as the failed batch 5: last_event_id=75, batch_size=25
conn = get_conn()
rows = _events_for_batch(conn, 75, 25)
conn.close()
texts = [r["raw_text"] for r in rows]
prompt = build_prompt(texts)

print(f"=== INPUT ===")
print(f"  events: {len(texts)}")
print(f"  prompt: {len(prompt)} chars")

body = json.dumps({
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": prompt}],
    "max_tokens": 16000,  # generous — let's see the model's true intent
    "temperature": 0.2,
    "thinking": {"type": "disabled"},
}).encode("utf-8")

req = urllib.request.Request(f"{api_base}/chat/completions", data=body, method="POST")
req.add_header("Content-Type", "application/json")
req.add_header("User-Agent", "pantheon-ichor/1.0 (lib.ichor.llm)")
req.add_header("Authorization", f"Bearer {key}")

print("\n=== LLM CALL (max_tokens=16000) ===")
with urllib.request.urlopen(req, timeout=120) as resp:
    data = json.loads(resp.read().decode("utf-8"))
    if "choices" in data and data["choices"]:
        msg = data["choices"][0].get("message", {})
        content = msg.get("content", "")
        reasoning = msg.get("reasoning_content", "")
        finish = data["choices"][0].get("finish_reason")
        usage = data.get("usage", {})

        print(f"  finish_reason: {finish}")
        print(f"  content length: {len(content)}")
        print(f"  reasoning_content length: {len(reasoning)}")
        print(f"  completion_tokens: {usage.get('completion_tokens')}")
        print(f"  reasoning_tokens: {usage.get('completion_tokens_details', {}).get('reasoning_tokens')}")

        # Try to parse
        print("\n=== PARSE ATTEMPT ===")
        try:
            from lib.ichor.entities.l2_llm import parse_extraction  # type: ignore  # noqa
            parsed = parse_extraction(content)
            ents = parsed.get("entities", [])
            rels = parsed.get("relationships", [])
            print(f"  entities: {len(ents)}")
            print(f"  relationships: {len(rels)}")
            print(f"  parse_warnings: {parsed.get('_parse_warnings', [])}")
        except Exception as e:
            print(f"  parse failed: {e}")
            # Check if the response ends with a complete entity
            print(f"  last 200 chars: {content[-200:]!r}")
            print(f"  first 200 chars: {content[:200]!r}")

        # If finish_reason is 'length', the model wanted more
        if finish == "length":
            print("\n=== TRUNCATED ===")
            print(f"  Model used all {usage.get('completion_tokens')} tokens and was cut off")
            print(f"  Implied full output: >{len(content)} chars (probably 2x more)")
        elif finish == "stop":
            print("\n=== COMPLETE ===")
            print(f"  Model finished naturally — {len(content)} chars was sufficient")
