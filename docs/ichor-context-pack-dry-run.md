# Ichor Context-Pack Dry-Run Operator Notes

This branch adds a bounded, source-backed context-pack builder for Ichor. It is intentionally **manual / dry-run only** until Konan explicitly approves canary or live wiring.

## Status

Implemented on branch `feature/ichor-context-pack-dry-run`:

- `lib/ichor/context_pack.py` — pure builder that returns compact, source-linked context packs.
- `scripts/dry-run-ichor-context-pack.py` — operator CLI for benchmark and comparison output.
- `lib/ichor_mcp.py` — MCP/manual tool surface named `ichor_context_pack`.
- `tests/test_ichor_context_pack.py` and `tests/test_ichor_mcp.py` — golden-query, no-op, MCP, budget, and safety contracts.

## Safety guarantees

The context-pack path is deliberately constrained:

- No LLM calls.
- No external API calls.
- No runtime mutation.
- No session rotation.
- No transcript rewrite.
- No config edits.
- No gateway restart.
- No LCM enablement.
- No DB writes in the builder metrics path.
- No MCP audit DB write for `ichor_context_pack` dry-run calls.

The MCP wrapper forces `dry_run=True` internally and does not expose a public `dry_run` / live-mode parameter.

Public MCP budgets are clamped before the builder runs:

- `max_items`: 1–8
- `max_tokens`: 1–900
- `max_ms`: 1–350

Invalid or non-finite budget values fall back to safe defaults.

## CLI usage

Run from the Pantheon repo/worktree root:

```bash
PYTHONPATH=/home/konan/pantheon-ichor-context-pack-dry-run \
python3 scripts/dry-run-ichor-context-pack.py \
  --god thoth \
  --phase research \
  --query "Conductor v2" \
  --max-items 8 \
  --compare-default-compressor \
  --format json
```

Markdown output is also available:

```bash
PYTHONPATH=/home/konan/pantheon-ichor-context-pack-dry-run \
python3 scripts/dry-run-ichor-context-pack.py \
  --god hephaestus \
  --phase debug \
  --query "Conductor v2" \
  --max-items 8 \
  --format markdown
```

Expected safety fields in dry-run output:

```json
{
  "would_mutate_runtime": false,
  "would_rotate_session": false,
  "would_rewrite_transcript": false,
  "would_change_config": false,
  "would_restart_gateway": false
}
```

## MCP/manual tool usage

The standalone MCP server manifest should include `ichor_context_pack`:

```bash
PYTHONPATH=/home/konan/pantheon-ichor-context-pack-dry-run \
python3 lib/ichor_mcp.py --list-tools
```

Direct manual smoke:

```bash
PYTHONPATH=/home/konan/pantheon-ichor-context-pack-dry-run python3 - <<'PY'
import json
from lib import ichor_mcp

pack = json.loads(ichor_mcp.ichor_context_pack(
    query="Conductor v2",
    god_name="thoth",
    phase="research",
    max_items=8,
))
print(json.dumps({
    "coverage": pack["coverage"],
    "metrics": pack["metrics"],
}, indent=2, sort_keys=True))
PY
```

Expected invariant highlights:

- `metrics.mode == "dry_run"`
- `metrics.llm_calls == 0`
- `metrics.api_calls == 0`
- `metrics.db_writes == 0`
- returned pack includes `injectable_context` and source links when coverage is available

## Verification recipe

Use the Hermes Agent venv when this host's `/bin/python3` lacks pytest:

```bash
PYTHONPATH=/home/konan/pantheon-ichor-context-pack-dry-run:$PYTHONPATH \
/usr/local/lib/hermes-agent/venv/bin/python -m pytest \
  tests/test_ichor_context_pack.py \
  tests/test_ichor_mcp.py \
  -q
```

Current expected result after Phase 2:

```text
26 passed
```

## Canary/live wiring gate

This branch does **not** enable the context pack in the live compressor/session path.

Do not change any of these without explicit Konan approval:

- `context.engine`
- profile or fleet `compression.*`
- live god gateway process state
- LCM plugin/config state
- automatic context injection path

Recommended next step after PR review is a separate canary plan for one god/profile with rollback, metrics, and a live proof gate.
