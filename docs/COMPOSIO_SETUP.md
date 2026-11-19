# Connecting services (Composio)

Pantheon's onboarding wizard has a **Connect Integrations** step
(`/onboarding/integrations`) where services like Gmail, Google Calendar, Notion,
Slack and GitHub are connected over OAuth. One backend powers it: the
**Composio bridge** on `http://127.0.0.1:8789`, proxied by the WebUI under
`/api/composio/*`.

Everything here is about **one** credential: a Composio **project API key**.

---

## 1. What you need: a project API key (`ak_…`)

1. Sign in at https://dashboard.composio.dev (free tier is fine).
2. Create a project if you don't have one.
3. Open the project's **Settings → API Keys** page and create/copy the key there.
   It begins with **`ak_`**.

> **The `ck_` key will not work.** The key on the personal *Sessions & API Key*
> page starts with `ck_` and is a different credential. The bridge rejects it
> with an explicit message rather than a bare 401. This is the single most
> common reason connecting services "just never worked".

Copy the key once — the dashboard won't show it again in full.

### Least-privilege scoped key (optional)

A default project key works as-is. If you use a scoped key, grant:

- **Sessions:** read and write
- **Toolkits:** read
- **Connected accounts:** read and write

Connected-account *write* is required so **Disconnect** can revoke the provider
grant before deleting the connection.

---

## 2. Give the key to the bridge

The bridge reads `COMPOSIO_API_KEY` from `composio-bridge/.env` (gitignored,
mode 0600 — this file is authoritative for `COMPOSIO_*`):

```bash
cd ~/pantheon/composio-bridge
printf 'COMPOSIO_API_KEY=ak_your_project_key\n' > .env   # only once; keep it 0600
chmod 600 .env
```

Alternatively set `COMPOSIO_API_KEY` in the service environment, or run from the
installer prompt (`install/install-pantheon.sh`, Phase 4).

Then restart and check:

```bash
systemctl --user restart composio-bridge
curl -s http://localhost:8789/health | python3 -m json.tool
```

Expected when healthy:

```json
{
  "status": "ok",
  "composio": true,
  "configured": true,
  "key_valid": true,
  "connections": 0,
  "session_id": "trs_…"
}
```

`connections: 0` is normal before you connect anything.

---

## 3. Troubleshooting

Read `/health` (or `/config`) first — every failure is reported there, in words:

| `/health` says | Meaning | Fix |
| --- | --- | --- |
| `configured: false` | No key at all | Do §2 |
| `key_issue` mentions `ak_` / `ck_` | Wrong credential type | Copy the **project** key from **Settings → API Keys** |
| `Invalid API key: ak_…` | Key revoked or from another project | Issue a fresh project key |
| bridge unreachable | Service not running | `systemctl --user status composio-bridge` |

```bash
journalctl --user -u composio-bridge -n 40 --no-pager
curl -s http://localhost:8789/config | python3 -m json.tool   # never prints the key
```

The bridge **never exits** on a bad key: it serves `composio:false` with a reason
so the wizard can say *why*, instead of showing a dead integration panel.

---

## 4. How it works (and why it is reliable)

Adapted from [OpenMausBot](https://github.com/milind-soni/OpenMausBot)
(Apache-2.0 — see `composio-bridge/NOTICE`). Two ideas carry the reliability:

1. **A project key talks to the v3.1 REST API directly** with an `x-api-key`
   header — no SDK whose types trail the API.
2. **One reusable Tool Router Session** owns the connection state, the
   authorization links and the MCP endpoint. A stable Composio *user id* is kept
   in `~/.hermes/state/composio-bridge.json` (mode 0600); connections belong to
   that user, so a recreated Session keeps every existing grant.

Multi-account mode is on (up to 5 accounts per toolkit, explicit selection), so a
second Gmail or Slack account never silently replaces the first.

Pantheon never stores the raw Gmail/Slack/GitHub provider tokens — Composio owns
their lifecycle.

---

## 5. Day-to-day

```bash
curl -s http://localhost:8789/connectors/connected | python3 -m json.tool   # inventory
curl -s http://localhost:8789/providers | python3 -m json.tool               # connectable services
```

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | `composio`, `configured`, `key_valid`, `connections` |
| GET | `/config` | key prefix, user/session ids, state file (no secrets) |
| GET | `/providers` | the project's own auth configs |
| GET | `/connections` | connected accounts |
| POST | `/connections/connect` | `{provider, alias?}` → `{id, url}` to open |
| GET | `/connections/:id/status` | poll after authorizing |
| DELETE | `/connections/:id` | revoke upstream, then delete |
| GET | `/connectors/connected` | renderer-neutral inventory for any client |
| POST | `/execute` | `{tool, arguments}` via the Session MCP endpoint |

Apps with no Composio-managed sign-in (e.g. Xero, Buffer) need your own auth
config for that app, created in the Composio dashboard. The bridge discovers the
project's own configs automatically and enables Tool Router for them on first
use — so connecting one just works once the config exists.

---

## 6. Notes for the installer / Enterprise

- `install/install-pantheon.sh` Phase 4 prompts for the **project key** and
  writes it to `composio-bridge/.env`. `--enterprise` and
  `--skip-composio-prompt` skip the prompt; the bridge still starts and reports
  `composio:false` until a key exists.
- The old `COMPOSIO_CONSUMER_KEY` (+ `COMPOSIO_AUTH_TOKEN`) pair is no longer
  used by this flow. `COMPOSIO_CONSUMER_KEY` is still read as a *fallback* name
  for the project key, but only when it holds an `ak_…` value.
