# Ichor Context-Pack Canary Plan

This document defines the next gate after the dry-run/manual context-pack surface. It is intentionally **replay-only** until Konan explicitly approves a disposable live-profile canary.

## Status

Implemented on branch `feature/ichor-context-pack-canary-harness`:

- `scripts/replay-ichor-context-pack-canary.py` — replay-only matrix runner and report generator.
- `tests/test_ichor_context_pack_canary.py` — safety, quality, artifact, and documentation contract tests.
- This document — operator plan, non-goals, readiness gate, and rollback contract.

## Non-goals

This branch does **not** enable live context injection.

Hard non-goals:

- No live profile mutation.
- No gateway restart.
- No LCM enablement.
- No compressor engine replacement.
- No session rotation.
- No transcript rewrite.
- No config edit.
- No automatic production enablement.

The harness can write only scratch artifacts under the requested artifact directory, normally `/tmp/ichor-context-pack-canary-<UTC>/`.

## Replay-only matrix

The canary harness runs representative dry-run rows across:

- `hermes / ops` operator follow-up questions about the context-pack work itself.
- `hephaestus / debug` and `thoth / research` golden `Conductor v2` role-aware queries.
- `rheta / copywriting` pricing-copy context.
- `hermes` and `thoth` LCM/risk recall.
- casual/no-op chat rows for `hermes`, `thoth`, and `hephaestus`.

Each row records:

- coverage status and returned source count
- source titles and source paths
- injectable context size
- token estimate
- wall time
- DB reads and writes
- LLM/API call counts
- mutation safety flags
- comparison against the cheap default-compressor baseline

## Readiness gate

The summary has three separate verdicts:

- `safety_pass` — dry-run invariants only.
- `quality_pass` — source grounding, role coverage, and no-op behavior.
- `canary_ready` — true only when both safety and quality pass.

Safety requires:

- `llm_calls == 0`
- `api_calls == 0`
- `db_writes == 0`
- all runtime mutation flags false

Quality requires:

- operator follow-up rows return source-backed context
- high-priority golden rows return source-backed context
- source grounding improves over the default-compressor baseline
- casual/no-op rows return no injectable context, zero tokens, and zero DB reads

## Rollback contract

Because this branch is replay-only, rollback is deletion of scratch artifacts and abandoning the branch/PR.

If a future Konan-approved disposable live-profile canary exists, rollback must be documented in that future PR as:

1. revert exactly one disposable profile config diff
2. restart only that disposable profile gateway
3. verify no LCM plugin/config change exists
4. verify default compressor remains the fleet default
5. preserve the replay report proving why the canary was stopped

## Operator commands

Run the replay harness from the worktree root:

```bash
PYTHONPATH=/home/konan/pantheon-ichor-context-pack-canary \
/usr/local/lib/hermes-agent/venv/bin/python \
  scripts/replay-ichor-context-pack-canary.py \
  --artifact-dir /tmp/ichor-context-pack-canary-manual \
  --format json
```

Markdown report mode:

```bash
PYTHONPATH=/home/konan/pantheon-ichor-context-pack-canary \
/usr/local/lib/hermes-agent/venv/bin/python \
  scripts/replay-ichor-context-pack-canary.py \
  --artifact-dir /tmp/ichor-context-pack-canary-manual \
  --format markdown
```

Expected artifact files:

- `summary.json`
- `report.md`
- one `<case_id>.json` file per replay row

Expected current verdict:

```text
safety_pass: true
quality_pass: true
canary_ready: true
```

That verdict means **ready to discuss a disposable-profile canary**, not ready for fleet enablement.
