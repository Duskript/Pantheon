# listmonk on relay-7 — Deployment Record

Generated: 2026-08-09
Owner: Hermes
Reason: Cybermage asked for a zero-cashflow mailing-list stack hosted on relay-7, not paid SaaS.

## Verdict

Deployed **listmonk on relay-7** using the existing free hosting surface.

No paid service was added. Outbound email is intentionally **not configured yet** because free-only sending must be chosen separately and safely.

## Live deployment

| Component | Value |
|---|---|
| Host | `relay-7` / Tailscale `100.100.46.52` |
| Admin URL | `http://100.100.46.52:9000/admin` tailnet-only |
| Public API base | `http://100.100.46.52:9000/api/public` tailnet-only for now |
| App container | `listmonk-app` |
| DB container | `listmonk-db` |
| App image | `listmonk/listmonk:latest` |
| DB image | `postgres:17-alpine` |
| Docker network | `listmonk_net` |
| Data dir | `/opt/listmonk/postgres-data` |
| Uploads dir | `/opt/listmonk/uploads` |
| Credentials file | `/opt/listmonk/listmonk.env` root-only; do not print in chat |
| Bind | `100.100.46.52:9000->9000/tcp` |

## Newsletter list

| Field | Value |
|---|---|
| Name | `Operator Field Report` |
| Type | `public` |
| Opt-in | `single` for early validation |
| Tags | `newsletter`, `validation` |
| UUID | `debcd121-5f81-4378-88ad-81672994bc95` |

## Verified proof

```bash
ssh relay-7 'sudo docker ps --filter name=listmonk --format "table {{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}"'
# listmonk-app   listmonk/listmonk:latest   100.100.46.52:9000->9000/tcp   Up
# listmonk-db    postgres:17-alpine         5432/tcp                       Up

curl -s http://100.100.46.52:9000/api/public/lists | python3 -m json.tool
# [{"uuid":"debcd121-5f81-4378-88ad-81672994bc95","name":"Operator Field Report"}]
```

Smoke test:

- `POST /api/public/subscription` returned `HTTP_CODE=200` with `{"data":{"has_optin":false}}`.
- Temporary `hermes-listmonk-smoke-*` subscriber was verified in DB and deleted.

## Why tailnet-only for now

`cloudflared` currently has wildcard `*.theoforgesolutions.com -> localhost:80`, so any new Caddy hostname becomes public by default. listmonk admin/API routes include private endpoints (`/admin/*`, `/api/*`), so exposing a public subdomain without Cloudflare Access or route-level hardening would be reckless.

Current safe posture:

```text
Iris landing page
  -> existing public /webhook/newsletter-signup route
  -> n8n / Conductor
  -> tailnet call to http://100.100.46.52:9000/api/public/subscription or authenticated listmonk API later
```

## Free-only sending options

Cloudflare Email Routing is free for inbound/replies. Cloudflare Email Sending currently requires Workers Paid, so it is not the no-spend outbound answer.

Potential zero-cashflow outbound options to validate later:

1. Existing Gmail/Google SMTP with app password, if available.
2. Resend free tier, if acceptable as temporary SaaS.
3. Brevo/SMTP2GO/free SMTP tier, if domain verification works.
4. Delay broadcast sending and use listmonk only as list-of-record until cash exists.

Do **not** run our own SMTP on relay-7.

## Operations

```bash
# Status
ssh relay-7 'sudo docker ps --filter name=listmonk'

# Logs
ssh relay-7 'sudo docker logs --tail=100 listmonk-app'
ssh relay-7 'sudo docker logs --tail=100 listmonk-db'

# Restart
ssh relay-7 'sudo docker restart listmonk-app listmonk-db'

# Backup DB
ssh relay-7 'sudo docker exec listmonk-db pg_dump -U listmonk listmonk | gzip | sudo tee /opt/listmonk/listmonk-$(date +%F-%H%M).sql.gz >/dev/null'
```

## Sources checked

- listmonk installation docs: Docker and binary deployment patterns.
- listmonk configuration docs: private/public route split, env vars, SMTP notes.
- listmonk subscriber/list API docs: `POST /api/public/subscription`, public list UUIDs, authenticated list/subscriber APIs.
- Cloudflare Email Service docs: SMTP exists, but outbound Email Sending is Workers Paid; Email Routing is Free/Paid.
