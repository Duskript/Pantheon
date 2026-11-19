# Composio bridge → OpenMausBot pattern: ported & live

**Date:** 2026-11-16 · **Component:** `pantheon/composio-bridge`

## What was asked

Onboarding should let you connect other services to the system. OpenMausBot
(`github.com/milind-soni/OpenMausBot`) uses Composio as its connection backend;
take what they use and put it into the Pantheon repo / onboarding.

## What was actually wrong (why it "never worked")

Neither Composio nor the wizard was the problem. Four things were:

1. **Wrong credential type.** `docs/COMPOSIO_SETUP.md` and the installer told
   you to use the **Consumer Key (`ck_…`)** + Auth Token. OpenMausBot uses a
   Composio **project key (`ak_…`)** with the `x-api-key` header. `ck_` is
   rejected — that is the single biggest cause.
2. **Bridge read an env var that was set nowhere.** `server.ts` wanted
   `COMPOSIO_API_KEY` and `process.exit(1)`ed without it; the env files only had
   `COMPOSIO_CONSUMER_KEY`. The service was simply **dead**.
3. **systemd unit was broken.** Its `PATH` pointed at
   `/home/konan/.nvm/versions/node/v22.12.0/bin` (removed; node is now at
   `~/.local/bin` + `~/.hermes/node/bin`), and it loaded no env file at all.
4. **Architecture was pre-Session + old SDK.** It used `@composio/core@0.10.0`
   with `authConfigs.list()` / `connectedAccounts.list()` — the model before
   Tool Router Sessions.

## What was built

Rewrote the bridge on OpenMausBot's proven pattern, with attribution (Apache-2.0,
see `composio-bridge/NOTICE`):

| File | State |
| --- | --- |
| `composio-bridge/composio.ts` | **new** — v3.1 REST client + Tool Router Session manager |
| `composio-bridge/state.ts` | **new** — persisted user/session ids (0600, key fingerprint) |
| `composio-bridge/server.ts` | rewritten — never exits on a bad key; + `/connectors/connected`, `/config` |
| `composio-bridge/{package.json,tsconfig.json}` | `@composio/core` dropped; typecheck added |
| `composio-bridge/{README.md,NOTICE}` | **new** — usage + attribution |
| `install/assets/systemd/composio-bridge.service` | fixed PATH; sources env; `WorkingDirectory` |
| `docs/COMPOSIO_SETUP.md` | rewritten for the `ak_` project-key flow |
| `install/install-pantheon.sh` | Phase 4 now prompts for the **project key** → `composio-bridge/.env` |
| `webui/api/integrations_bridge.py` | reports real bridge state (`key_valid`, `connections`) |

Key behaviours: one reusable Tool Router **Session** per stable user id (owns
connections + auth links + MCP endpoint); multi-account mode (5/toolkit, explicit
selection); `revoke_on_delete=true` on disconnect; the bridge **never exits** —
it serves `composio:false` with a reason so the wizard explains itself.

## Proof (live, this machine)

```
$ systemctl --user is-active composio-bridge
active

$ curl -s localhost:8789/health
{"status":"ok","composio":true,"configured":true,"key_valid":true,
 "connections":0,"session_id":"trs_OfRqYkoeuF1k"}

$ curl -s localhost:8789/providers      # 6 project auth configs
count: 6   cloudflare_api_key, linkedin, twitter, resend, perplexityai, vapi

$ curl -s localhost:8789/connectors/connected   # 50+ services with state

$ curl -s -XPOST localhost:8789/connections/connect -d '{"provider":"gmail"}'
{"id":"ca_z6MUjpf5boCx","url":"https://connect.composio.dev/...","provider":"gmail"}
   → real OAuth link; account deleted after the test
```

Session id is stable across service restarts (`trs_OfRqYkoeuF1k`). `tsc --noEmit`
clean. The wizard's `/onboarding/integrations` route already existed — it now has
a working backend.

## Notes

- The working key is `COMPOSIO_API_KEY` in `composio-bridge/.env` (gitignored,
  0600) — authoritative for the bridge.
- `~/pantheon/.env` holds a **stale** `ak_…` under the legacy name
  `COMPOSIO_CONSUMER_KEY` (decoy; returns 401). Left in place — it is only a
  fallback name and `COMPOSIO_API_KEY` wins.
- Nothing committed or pushed — changes are in the working tree for your review.
