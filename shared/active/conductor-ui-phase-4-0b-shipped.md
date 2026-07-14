# Conductor UI Phase 4.0b — SHIP (2026-06-17)

**Status:** SHIP — task `t_e145441a` complete. All 4 new endpoints + auth on 3 surfaces verified.

## What shipped (this run, run 85)

- **4 new endpoints** on `conductor/v2/api_server.py` (903 LOC, was 236 in 4.0a slim):
  - `POST /api/workflows/{id}/validate` — runs `validate_workflow_file`, returns `{valid, violations}`
  - `POST /api/workflows/{id}/run` — triggers `engine.start_workflow`, returns `wf_<8hex>`
  - `GET /api/workflows/{id}/runs` — lists run history from `state/wf_*.json`
  - `GET /api/workflows/{id}/runs/{run_id}/events` — SSE live event stream
- **`/health`** (unauthenticated) — service status + wiring state
- **Auth on all 3 surfaces** (was a security gap — webhook + live_stream were running with bind 0.0.0.0 and NO auth before this):
  - `api_server.py` — every endpoint except `/health` via `Depends(auth_dep)`
  - `webhook.py` — `/webhook/{source}` and `/dispatch`
  - `live_stream.py` — `?api_key=` on the `/clitool/{wf}/{step}` WebSocket upgrade
- **New `conductor/v2/auth.py`** — single source of truth for bearer-token logic (resolve_api_key, check_token, bearer_dependency, check_query_key). 274 LOC, ~11K.
- **Single env var** — `CONDUCTOR_API_KEY` (canonical) with `CONDUCTOR_WS_API_KEY` as legacy alias for the live stream.

## Verification

```
test_api_server.py     31/31 pass (2.48s)
test_service.py         6/6  pass (0.92s)
test_webhook.py +
test_live_stream.py    18/18 pass (3.03s)
```

End-to-end smoke (real uvicorn + httpx): all 9 endpoints (health + 4 CRUD + 4 new) return correct status codes. SSE event stream produces `event: open` + data line, relays broadcast events end-to-end.

Kill criterion (engine reload after PUT) verified by `test_put_picks_up_in_memory_reload_kill_criterion` — workflow is in `engine.workflows._workflows` after `PUT`, the next `start_workflow` picks up the new content without a daemon restart.

## Tests changed in this run

The 3 SSE tests in `test_api_server.py` were rewritten to use a real uvicorn server + httpx async client. Reason: `httpx` 0.28 (now in our venv) + starlette.testclient no longer drains streaming responses from async generators — chunks never arrive. All 28 non-streaming tests still work fine with TestClient. Pattern borrowed from `test_live_stream.py` (which has always used real aiohttp).

Also fixed `test_sse_returns_503_when_no_live_stream` — the prior version reused `self.engine` (which had `live_stream` attached) so the api_server's closure never resolved to None. Now constructs a fresh `ConductorEngine(..., live_stream=None)` to exercise the actual 503 path.

## Files (untracked on branch `feature/a2-websocket-live-stream`)

- `conductor/v2/api_server.py` (35K, 903 LOC)
- `conductor/v2/auth.py` (11K, 274 LOC) — NEW
- `conductor/v2/api_server.pre-4.0a-full.py` (34K) — backup, can delete
- `conductor/v2/webhook.py` — modified (auth)
- `conductor/v2/live_stream.py` — modified (auth + env-var resolution)
- `conductor/v2/service.py` — unmodified (uses `APIServer` re-introduced by 4.0b)
- `conductor/v2/tests/test_api_server.py` — 3 SSE tests rewritten

## Follow-ups

1. **Commit decision** — Hephaestus should decide whether to land these on `feature/a2-websocket-live-stream`. Previous 4.0a (t_d20dbc18) also left them untracked.
2. **Backup file** — `api_server.pre-4.0a-full.py` is now redundant; safe to delete.
3. **Tier-2 review** — recommend a reviewer checks the 4 new endpoints + auth against `~/pantheon/shared/active/synergy-wb-port-adapter-spec.md` §4.4 + §6 (happy paths covered by smoke tests; error paths + bridge-* 403 guard warrant explicit validation).
4. **httpx2 upgrade** — if we install `httpx2` (the new recommended client for starlette.testclient), we could revert the SSE tests to use TestClient. Not blocking.

## Evidence links

- Journal: `~/athenaeum/Codex-God-marvin/journal/2026-06-17-conductor-ui-phase-4-0b.md`
- Decision: `~/athenaeum/Codex-God-marvin/DECISIONS.md` 2026-06-17 4.0b entry
- Blueprint: `~/pantheon/shared/active/conductor-ui-phase-4-blueprint.md` (canonical)
- Spec: `~/pantheon/shared/active/synergy-wb-port-adapter-spec.md` (§4.4 endpoints, §6 auth)
