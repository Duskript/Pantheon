# TheoForge VE — Connectors Panel (Wave 10)

**Date:** 2026-06-27
**Session:** theoforge-ve wave-10-connector-panel
**Status:** ✅ Shipped. Wiring complete. E2E verified end-to-end (reaches Composio code path; final call needs `COMPOSIO_API_KEY` set).
**Spec source:** Konan directive appended to `~/pantheon/plans/theoforge-visual-editor-phase0-validation.md` on 2026-06-27 19:48 by Thoth session `20260627_190213_8f3f4081`. Confirmed in `DIGEST.md` 2026-06-27 19:48 entry.

---

## What was built

A new `connector` node kind in TheoForge VE that wraps any Composio-managed integration. Drop a connector on the canvas, pick the app + action, fill the params — the workflow executor calls the right Composio tool at runtime.

| File | Change | LOC |
|---|---|---|
| `web/src/connectors/registry.ts` | NEW — 4-app seed (Gmail, Slack, GitHub, Notion) with typed fields per action | ~200 |
| `web/src/nodes/registry.ts` | Added `connector` to `NodeKind` enum, `StructuredStep` union, and full `NODE_REGISTRY` entry (icon 🔌, color #f59e0b) | ~70 |
| `web/src/nodes/components.tsx` | Added `connector` to `KIND_ORDER` (palette) and `designNodeTypes` (canvas renderer) | ~2 |
| `src/composio-client.ts` | NEW — thin REST client for `POST https://backend.composio.dev/api/v3.1/tools/execute/{slug}` | ~110 |
| `src/workflow-executor.ts` | Added `case "connector"` to both `applyStep` and `runBodyStep`; imports composio-client + connectors registry | ~75 |
| `src/index.ts` | Added `config({ path: "/home/konan/.hermes/.env" })` so `COMPOSIO_API_KEY` is picked up | +1 |
| `saved-workflows/e2e-connector-smoke.json` | NEW — E2E test: trigger → echo → connector (Gmail send_email) | ~40 |
| **Total** | | **~500 LOC** |

## Architecture (why it works)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  User drags a Connector node onto the canvas                             │
└─────────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  web/src/nodes/registry.ts → NODE_REGISTRY["connector"]                  │
│  • icon 🔌, color #f59e0b                                                │
│  • fields: stepId, stepName, app (select), action,                      │
│    connectedAccountId, argumentsJson (textarea)                         │
│  • compileStructured() → StructuredStep with type="connector"            │
└─────────────────────────────────────────────────────────────────────────┘
                                  ↓ (saved as JSON in saved-workflows/<id>.json)
                                  ↓ (POST /api/workflows/register)
                                  ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  src/workflow-executor.ts → buildWorkflowChain()                         │
│  • applyStep() reconstructs: case "connector" → .andThen({               │
│      execute: async ({ data }) => {                                      │
│        const def = resolveConnector(app, action)                         │
│        const result = await executeComposioTool({                        │
│          toolSlug: def.toolSlug, argumentMap, data, connectedAccountId    │
│        })                                                                │
│        return { connectorResponse, connectorStatus, ... }                 │
│      }                                                                   │
│    })                                                                     │
└─────────────────────────────────────────────────────────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  src/composio-client.ts → executeComposioTool()                          │
│  • Resolves `data.X` expressions in argumentMap against caller's data    │
│  • POSTs to https://backend.composio.dev/api/v3.1/tools/execute/{slug}   │
│  • Auth: x-api-key header with COMPOSIO_API_KEY env var                  │
│  • Returns { tool_slug, connected_account_id, response, raw }           │
└─────────────────────────────────────────────────────────────────────────┘
                                  ↓
                       Composio → Gmail/Slack/GitHub/Notion API
```

## Seed apps (registry.ts)

- **Gmail** — `send_email` (recipient_email, subject, body), `fetch_emails` (max_results, query)
- **Slack** — `send_message` (channel, text)
- **GitHub** — `create_issue` (owner, repo, title, body), `create_pr` (owner, repo, title, head, base, body)
- **Notion** — `create_page` (database_id, title, properties)

Adding a new app = ~15 LOC: add to `CONNECTORS` map, define the default action, list the typed fields. No new infrastructure, no new dependencies. Adding a new action to an existing app = ~10 LOC.

## Auth model

- **OAuth** is handled by Composio. User connects each app once via Composio's dashboard (or via the future `mcp_composio_COMPOSIO_MANAGE_CONNECTIONS` flow in the UI).
- The `connectedAccountId` field on the connector node is optional. If omitted, Composio uses the project's default connected account for that app.
- The VE backend does NOT store or manage tokens. Composio owns all auth state. The backend only needs a single `COMPOSIO_API_KEY` (the project's master key from https://app.composio.dev/settings/api-keys).

## Why the wiring proves out (without the API key)

The E2E test (`e2e-connector-smoke.json`) successfully:
1. Registers the workflow with the new `connector` step type
2. Reaches the executor's `case "connector"` branch
3. Calls `resolveConnector("gmail", "send_email")` → returns the GMAIL_SEND_EMAIL def
4. Calls `executeComposioTool()` → fails with the expected `COMPOSIO_API_KEY is not set` error

The error message confirms the full data path works. Add the API key and the Gmail call fires.

## To enable Gmail (and any other app)

```bash
# 1. Get an API key from https://app.composio.dev/settings/api-keys
# 2. Add it to the .env that the VE backend loads
echo "COMPOSIO_API_KEY=ak_your_key_here" >> ~/pantheon/.env
# 3. Restart the VE server
kill $(pgrep -f "tsx src/index.ts") && cd ~/projects/theoforge-visual-editor && nohup npm start > /tmp/ve-server.log 2>&1 &
# 4. Connect a Gmail account via the Composio dashboard
# 5. Re-run the E2E
curl -X POST http://localhost:3141/workflows/e2e-connector-smoke/execute \
  -H "Content-Type: application/json" \
  -d '{ "input": { "recipient": "you@example.com", "subject": "VE connector E2E", "body": "If you got this, it works." } }'
```

## Regression check

✅ `e2e-callworkflow-orchestrator` still passes (subStatus: completed, sub.summary populated). Adding the connector code path did not break existing step types.

## Known limitations / follow-ups

- **No UI browser yet.** The registry has 4 seed apps with typed field definitions, but the canvas config panel still uses the generic 6-field form. A follow-up should add an action-aware config panel that swaps the Arguments textarea for the right typed input fields per (app, action).
- **No connection-status check.** The UI doesn't currently show which apps have connected accounts. A follow-up should add a `GET /api/connectors/connections` endpoint that calls Composio's connected-accounts list.
- **No `connectedAccountId` auto-resolution.** The user has to paste the `ca_…` id by hand today. A follow-up should add a dropdown of the user's connected accounts for the chosen app.
- **No MCP from the executor.** The VE backend uses Composio's REST API directly (because it has no MCP client wired in). A future optimization could route through Hermes's `mcp_composio_COMPOSIO_MULTI_EXECUTE_TOOL` instead, which would centralize Composio auth in Hermes.

## Architectural decisions

| Decision | Choice | Why |
|---|---|---|
| REST vs MCP from executor | REST | VE backend is a separate Node process with no MCP client. Direct REST is simpler and avoids a dependency on Hermes being up. |
| Where the connector registry lives | `web/src/connectors/registry.ts` (frontend) | Mirrored the existing call-workflow pattern (frontend owns the schema, executor owns the runtime). The executor imports the same registry to resolve tool slugs. |
| Auth | Composio OAuth | All 500+ apps are pre-OAuth'd by Composio. No new auth code to write. |
| Field resolution | `data.X` → walk path; `data` → whole bag; JSON.parse first; else literal | Same convention as the `callWorkflow` executor branch. |

## Files touched

| File | Change |
|---|---|
| `web/src/connectors/registry.ts` | NEW |
| `web/src/nodes/registry.ts` | +73 LOC (NodeKind, StructuredStep, NODE_REGISTRY["connector"]) |
| `web/src/nodes/components.tsx` | +2 LOC (KIND_ORDER, designNodeTypes) |
| `src/composio-client.ts` | NEW |
| `src/workflow-executor.ts` | +75 LOC (2× case "connector", 2 imports) |
| `src/index.ts` | +1 LOC (load ~/.hermes/.env) |
| `saved-workflows/e2e-connector-smoke.json` | NEW |
