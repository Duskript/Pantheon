# composio-bridge

Node sidecar that turns a Composio **project** API key into the small REST
surface the Pantheon WebUI (and the onboarding wizard's *Connect Integrations*
step) talks to.

The Python webui proxies every `/api/composio/*` request to this bridge on
`127.0.0.1:8789` (see `webui/api/routes.py`).

## Why it is built this way

The connection pattern is adapted from [OpenMausBot](https://github.com/milind-soni/OpenMausBot)
(Apache-2.0 — see `NOTICE`). Two things make it work where the earlier bridge did
not:

1. **The right credential.** It uses a Composio *project* key (`ak_…`), sent in
   the `x-api-key` header straight to the v3.1 REST API. The `ck_…` key on the
   personal *Sessions & API Key* page is a different credential and is rejected.
2. **A Tool Router Session.** One reusable Session per stable user id owns the
   connection state, the authorization links and the MCP endpoint. Connections
   belong to the Composio *user*, so recreating a Session keeps every grant.

No Composio SDK is used — the API surface is small and stable, and the SDK's
types lag behind it.

## Configuration

| Variable | Meaning |
| --- | --- |
| `COMPOSIO_API_KEY` | **Required.** Composio project key (`ak_…`). |
| `COMPOSIO_PROJECT_KEY` | Alias for the above. |
| `COMPOSIO_CONSUMER_KEY` | Legacy name; only used if it holds an `ak_…` value. |
| `COMPOSIO_BRIDGE_PORT` | Listen port (default `8789`). |
| `COMPOSIO_API_BASE` | Override the API base (default `https://backend.composio.dev/api/v3.1`). |
| `COMPOSIO_STATE_FILE` | Where the user/session ids are kept (default `~/.hermes/state/composio-bridge.json`, mode 0600). |

The bridge **never exits** for a missing or invalid key: `/health` reports
`composio:false` with a reason, so the wizard shows a prompt instead of a dead
service.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | `{status, composio, configured, key_valid, connections}` |
| GET | `/config` | Non-secret status: key prefix, user/session ids, state file |
| GET | `/providers` | The project's own auth configs (one row per toolkit) |
| GET | `/connections` | Connected accounts for this bridge's user |
| GET | `/connections/:id` | One account |
| GET | `/connections/:id/status` | Lifecycle status for polling after OAuth |
| POST | `/connections/connect` | `{provider, alias?}` → `{id, url}` authorization link |
| DELETE | `/connections/:id` | Revoke upstream, then delete |
| GET | `/connectors/connected` | Renderer-neutral inventory: `{configured, services}` |
| POST | `/execute` | `{tool, arguments}` → runs via the Session MCP endpoint |

## Develop

```bash
npm install
COMPOSIO_API_KEY=ak_… npm start     # http://127.0.0.1:8789/health
npm run typecheck
```

## Service

Installed as a user systemd unit (`install/assets/systemd/composio-bridge.service`):

```bash
systemctl --user restart composio-bridge
journalctl --user -u composio-bridge -n 40
curl -s http://localhost:8789/health | python3 -m json.tool
```
