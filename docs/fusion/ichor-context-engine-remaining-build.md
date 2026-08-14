# Fusion Spec Contract — IchorContextEngine Remaining Build

## Objective

Finish the remaining default-off `IchorContextEngine` build item: persist raw turns losslessly into an Ichor-owned SQLite store while preserving the v0 safety boundary.

The current prototype keeps raw turns in process memory. That proves exact expansion handles inside one engine instance, but does not yet satisfy the architecture line from `docs/specs/ichor-precision-context-engine.md`:

```text
ingest every turn losslessly into Ichor
→ maintain session frontier and fresh tail
→ expose exact recall/expand tools for omitted context
```

## Files allowed

Allowed to create/modify only:

- `docs/fusion/ichor-context-engine-remaining-build.md`
- `lib/ichor/raw_turns.py`
- `hermes-agent/plugins/context_engine/ichor/__init__.py`
- `tests/test_ichor_raw_turns.py`
- `tests/test_ichor_context_engine.py`

Do not touch live config, profile env, cron, gateway units, LCM plugin settings, or PR #138 benchmark files unless a test proves it is required.

## Interfaces

Create `lib.ichor.raw_turns` with:

```python
@dataclass(frozen=True)
class RawTurn:
    session_id: str
    seq: int
    role: str
    content: str
    content_hash: str
    message_json: str
    tool_name: str | None = None
    tool_call_id: str | None = None
    source: str = "context_engine"
    created_at: str | None = None

class RawTurnStore:
    def __init__(self, db_path: str | Path) -> None: ...
    def migrate(self) -> dict[str, object]: ...
    def ingest_messages(self, session_id: str, messages: list[dict[str, Any]], *, source: str = "context_engine") -> dict[str, int]: ...
    def fetch_range(self, session_id: str, start_seq: int, end_seq: int) -> list[RawTurn]: ...
    def get_frontier(self, session_id: str) -> dict[str, Any] | None: ...
```

SQLite tables:

```sql
ichor_raw_turns(session_id, seq, role, content_hash, content, message_json, tool_name, tool_call_id, source, created_at, PRIMARY KEY(session_id, seq))
ichor_session_frontier(session_id PRIMARY KEY, last_ingested_seq, active_tail_start_seq, updated_at)
```

`ingest_messages()` must be idempotent by `(session_id, seq)` and must not duplicate repeated calls with the same message list.

Update `IchorContextEngine`:

- accepts optional `raw_turn_store: RawTurnStore | None`
- default remains `None` so the prototype does not mutate live DB by default
- `_ingest_raw_turns()` always keeps in-process rows and also writes to `raw_turn_store` if configured
- `ichor_expand` first checks in-process rows, then falls back to `raw_turn_store.fetch_range()` if available
- `get_status()` exposes raw-turn storage metrics: configured/persisted count/frontier or last error
- no LLM/API calls; no fleet/profile/default changes

## Constraints

- Strict TDD: write tests that fail before implementation.
- No top-level debug `print()` in Python files.
- No bare `except:`.
- No live DB writes in tests; use temp DB paths only.
- No config/fleet/LCM changes.
- Preserve existing benchmark verdict shape unless new storage metrics are additive.
- If SQLite write fails, fail quiet for prompt assembly: keep in-process expansion working and report error in status; do not inject panic context into the live prompt.

## Verification

Commands must pass from `/tmp/pantheon-ichor-context-engine`:

```bash
PYTHONPATH=/tmp/pantheon-ichor-context-engine:/tmp/pantheon-ichor-context-engine/hermes-agent /usr/local/lib/hermes-agent/venv/bin/python -m pytest tests/test_ichor_raw_turns.py tests/test_ichor_context_engine.py -q
PYTHONPATH=/tmp/pantheon-ichor-context-engine:/tmp/pantheon-ichor-context-engine/hermes-agent /usr/local/lib/hermes-agent/venv/bin/python -m pytest tests/test_ichor_context_pack.py tests/test_ichor_context_pack_canary.py tests/test_ichor_context_pack_rollout_simulation.py tests/test_ichor_compressor_weight_benchmark.py tests/test_ichor_context_engine.py tests/test_ichor_context_engine_turn_benchmark.py tests/test_ichor_raw_turns.py -q
PYTHONPATH=/tmp/pantheon-ichor-context-engine:/tmp/pantheon-ichor-context-engine/hermes-agent /usr/local/lib/hermes-agent/venv/bin/python -m py_compile lib/ichor/raw_turns.py hermes-agent/plugins/context_engine/ichor/__init__.py tests/test_ichor_raw_turns.py tests/test_ichor_context_engine.py
git diff --check
```

Also run a static scan for:

- top-level `print(` outside `if __name__ == "__main__"`
- bare `except:`
- hardcoded token/API-key patterns

## Expected result

A stacked follow-up on PR #139 proving the remaining build item:

```text
IchorContextEngine can persist raw turns losslessly to Ichor when explicitly configured, while default-off operation still performs zero live DB writes.
```
