"""Reproduce the batch-5 failure with max_tokens=4000 (the current setting).

If the model with max_tokens=4000 produces >4000-token output, it will be
truncated mid-entity and fail to parse. This is the exact failure mode the
L2 loop hit on 2026-06-12.
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

# Same query as the failed batch 5
conn = get_conn()
rows = _events_for_batch(conn, 75, 25)
conn.close()
texts = [r["raw_text"] for r in rows]
prompt = build_prompt(texts)

# Test multiple max_tokens values to find the minimum that works
for max_tok in [2000, 3000, 4000, 6000, 8000]:
    body = json.dumps({
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tok,
        "temperature": 0.2,
        "thinking": {"type": "disabled"},
    }).encode("utf-8")

    req = urllib.request.Request(f"{api_base}/chat/completions", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "pantheon-ichor/1.0 (lib.ichor.llm)")
    req.add_header("Authorization", f"Bearer {key}")

    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        msg = data["choices"][0].get("message", {})
        content = msg.get("content", "")
        finish = data["choices"][0].get("finish_reason")
        usage = data.get("usage", {})

        try:
            from lib.ichor.entities.l2_llm import parse_extraction  # type: ignore  # noqa
            parsed = parse_extraction(content)
            n_ents = len(parsed.get("entities", []))
            n_rels = len(parsed.get("relationships", []))
            parseable = "YES"
        except Exception as e:
            n_ents = n_rels = 0
            parseable = f"NO ({type(e).__name__})"

        print(f"max_tokens={max_tok:5d} → finish={finish:8s} output={len(content):5d} chars "
              f"({usage.get('completion_tokens'):4d} tok) | parsed={parseable:20s} "
              f"ents={n_ents:3d} rels={n_rels:3d}")
