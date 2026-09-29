# Person Roots Active Chat Clarify Wrapper Contract

## Objective

Provide the live-turn glue between structured Person Roots candidate facts and Hermes' interactive `clarify` tool, without creating a durable approval backlog during a chat turn.

## Delivered surfaces

- `lib/person_roots/live_chat.py`
  - `handle_live_chat_candidates(...)`
  - `render_live_chat_result(...)`
  - `load_candidate_stream(...)`
- `scripts/person-roots-live-chat.py`
  - JSON/JSONL local smoke CLI.
- `tests/test_person_roots_live_chat.py`
  - 5 tests covering clarify, safe apply, review-no-queue, no-op, and CLI smoke.
- `lib/person_roots/__init__.py`
  - Exports live-chat helpers.

## Behavior contract

`handle_live_chat_candidates(...)` returns:

- `action="clarify"`
  - includes exact `clarify_args`;
  - includes `tool_call={"name":"clarify","arguments": clarify_args}`;
  - writes nothing.
- `action="applied"`
  - safe `allow` facts applied through the guarded writer;
  - does not queue review items.
- `action="planned_review"`
  - approval/deny-class facts observed;
  - writes nothing;
  - appends nothing to `_pending/PROPOSALS.jsonl`.
- `action="no_candidates"`
  - no-op.

## Safety boundaries

This slice intentionally does **not**:

- perform LLM/free-form extraction;
- create person roots;
- link platform accounts;
- append proposal records to `_pending/PROPOSALS.jsonl`;
- auto-approve sensitive/cross-person facts;
- call the Hermes `clarify` tool inside the library.

The agent/gateway layer is responsible for actually calling:

```python
clarify(**result["clarify_args"])
```

when `result["action"] == "clarify"`.

## Verification evidence

```text
Ran 5 live-chat wrapper tests in 0.390s — OK
Ran 106 Person Roots tests in 8.304s — OK
RESULT: PASS (15 person folder(s), 125 file(s) checked, 0 warning(s))
AST OK
git diff --check passed for touched live-chat files
No top-level debug print / bare except / pdb / TODO / FIXME matches in touched live-chat files.
```
