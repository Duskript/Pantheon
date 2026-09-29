# TheoForge Outreach — Fusion Phase A Spec Contract

**Owner:** Hermes planner
**Executor:** Fusion sidekick via `delegate_task`
**Date:** 2026-08-31
**Status:** implementation authorized; no commit/push by executor

## Objective

Close the next production workflow seam without touching unrelated Pantheon work:

1. Add a deterministic, dependency-free inbound email reply state machine that records replies on the canonical lead, automatically suppresses unsubscribe requests, and creates an approval-gated reply draft for actionable replies.
2. Add the missing relay-7 public proxy routes so `/healthz` and `/api/*` reach the running TheoForge v9 service instead of the static root.

This phase must remain fail-closed: unsubscribe replies never create an outbound draft; reply drafts never send automatically; unknown leads are reported without creating a phantom lead.

## Real layout verified by planner

- Canonical bridge source: `/home/konan/pantheon/services/theoforge-bridge/`
- Existing pure outbound state machine: `outreach.mjs`
- Existing outbound tests: `outreach.test.mjs` (node:test)
- Existing relay config source: `/home/konan/pantheon/caddyfile_blog`
- Active relay app: `/srv/theoforge/server.mjs` on relay-7, port 4321
- Active bridge: `http://100.115.50.41:4323`
- Active Caddy root serves `/var/www/theoforge`; it currently has no generic `/healthz` or `/api/*` reverse proxy.
- Canonical lead schema: `/home/konan/pantheon/shared/lead-schema.md`

## Allowed files — executor 1

- `services/theoforge-bridge/inbound.mjs` (create)
- `services/theoforge-bridge/inbound.test.mjs` (create)

Executor 1 must not modify `server.mjs`, `outreach.mjs`, `outreach.test.mjs`, service units, lead files, or any unrelated file.

## Allowed files — executor 2

- `caddyfile_blog` (modify only the `theoforgesolutions.com:80` block)

Executor 2 must not modify the relay app, bridge, service units, certificates, DNS, or unrelated Caddy host blocks.

## Inbound module contract

Export these functions:

```js
classifyInboundReply({ from, to, subject, text, message_id, in_reply_to, references }):
  { ok, classification, normalized, is_unsubscribe, is_actionable, event_key }

applyInboundReply(lead, inbound, options = {}):
  { ok, lead, classification, suppressed, draft, idempotent, error? }
```

`classifyInboundReply` requirements:

- Normalize sender email to lowercase/trimmed.
- Require a valid sender email and non-empty body; return `validation_failed` with field errors otherwise.
- Preserve bounded `subject`, `text`, provider `message_id`, `in_reply_to`, and `references` values.
- Detect unsubscribe intent from common phrases including `unsubscribe`, `remove me`, `stop emailing`, `do not contact`, and `don't contact me`, case-insensitively.
- Classify unsubscribe before positive/negative/actionable classification.
- Return one of: `unsubscribe`, `positive`, `negative`, `question`, `neutral`.
- `is_actionable` is true for `positive` and `question`; false for `unsubscribe`, `negative`, and `neutral`.
- Produce a stable `event_key`: provider `message_id` when present, otherwise a deterministic digest-like key from normalized sender + subject + text. Do not use random IDs for deduplication.

`applyInboundReply` requirements:

- Never mutate the caller's object in place; clone the lead.
- Reject missing lead with `lead_required`.
- Deduplicate an already-recorded inbound event by `event_key`; return `ok:true`, `idempotent:true`, unchanged conversation/draft counts.
- Append exactly one `conversation` entry for a new reply:
  - `channel: "email_in"`
  - `direction: "in"`
  - timestamp from `options.now` or current ISO time
  - sender, subject, bounded text, provider identifiers, and `event_key`
- Update `last_contact_at`, `last_contact_channel: "email_in"`, and `updated_at`.
- For unsubscribe: set `suppressed: true`, `re_engagement_allowed: false`, set `outreach.suppressed: true`, and do not create a draft.
- For negative/neutral: do not create a draft.
- For actionable positive/question: create exactly one pending draft using the existing `createDraftRecord` contract. The draft must be `status: "draft"`, `created_by: "system:inbound-reply"`, and include a deterministic safe reply body. It must never be `approved` or `sent`.
- Reply draft creation must be idempotent for the same inbound `event_key`.
- Do not call the network, Resend, filesystem, or an LLM.

## Caddy routing contract

Inside the existing `theoforgesolutions.com:80` block, before the final static-root catch-all:

```caddy
handle /healthz {
    reverse_proxy 127.0.0.1:4321
}

handle /api/* {
    reverse_proxy 127.0.0.1:4321
}
```

The existing eBay `/api/ebay/*` handlers must remain before the generic `/api/*` handler. No other host block or static path may change.

## Verification required from executors

Executor 1:

```bash
node --check services/theoforge-bridge/inbound.mjs
node --test services/theoforge-bridge/inbound.test.mjs services/theoforge-bridge/outreach.test.mjs
```

Tests must cover validation, all five classifications, unsubscribe suppression, actionable draft creation, no-send status, duplicate event idempotency, and immutability.

Executor 2:

```bash
caddy validate --config caddyfile_blog
```

If `caddy` is unavailable, run a structural check proving the two handlers exist in the correct host block and that no unrelated host block changed; report the unavailable command as a gap rather than claiming validation.

## Parent-owned follow-up integration

After executor review, Hermes will wire `inbound.mjs` into `server.mjs`, add route-level tests, deploy the vetted Caddy source to relay-7, reload Caddy, and run live health → public API → lead persistence → draft/approval/suppression acceptance. Executors must not perform these mutations.

## Non-goals for Phase A

- No operator UI.
- No background queue or retry worker.
- No automatic outbound send.
- No Resend domain/DNS changes.
- No CashyOS mutation.
- No commits, pushes, branch switches, or broad cleanup of the dirty Pantheon worktree.

## Exit gate

Phase A is not complete until:

1. Both executor file scopes match exactly.
2. Focused tests and syntax checks pass independently.
3. Caddy config validates or the precise unavailable validator is recorded.
4. Parent wires the module and runs a fresh live acceptance test.
5. Public `/healthz` returns the v9 JSON and public `/api/prospects` accepts a complete controlled payload.
6. An inbound unsubscribe fixture updates suppression without producing a draft.
7. No real outbound email is sent during automated tests.

## Caddy security correction — required before deploy

The first executor added a generic `/api/*` proxy as mechanically requested. Parent review rejects that public exposure because the relay also has internal lead listing, departure, and follow-up mutation endpoints. Replace the generic handler before applying the config remotely.

The public Caddy block may proxy only these browser-facing routes to `127.0.0.1:4321`:

- `/healthz`
- `/api/leads`
- `/api/chat`
- `/api/prospects`
- `/api/prospects/followup`
- `/api/mercer/message`
- `/api/mercer/reset`
- `/api/mercer/health`

Keep existing specific `/api/ebay/*` handlers ahead of this matcher. Do not expose `/api/prospects/list`, `/api/prospects/depart`, or any bridge `/outreach/*` route publicly. Prefer one named Caddy path matcher for the list above over a wildcard. `caddy validate --adapter caddyfile --config caddyfile_blog` must pass.

## Phase A.1 — bridge inbound route integration

This follow-on slice is authorized after the pure inbound module passes review.

### Allowed files

- `services/theoforge-bridge/server.mjs`
- `services/theoforge-bridge/inbound-http.test.mjs` (create)

Do not modify the pure `inbound.mjs`, its tests, `outreach.mjs`, Caddy, service units, credentials, or unrelated files.

### Required behavior

- Import `classifyInboundReply` and `applyInboundReply` from `./inbound.mjs`.
- Add `POST /inbound/reply` to the bridge.
- Accept the Resend event shape `{ type: "email.received", data: {...} }` and the already-normalized `{ from, to, subject, text, ... }` shape.
- Map Resend `data.email_id` to the inbound event `message_id`; accept `message_id` as a fallback.
- Accept `to` as either a string or array; use the first recipient for the normalized event.
- Require a valid sender and non-empty text; return HTTP 400 with structured validation fields.
- Look up the sender by email in the canonical lead directory. Return HTTP 404 `lead_not_found` without writing for unknown senders.
- Apply the pure state transition, atomically persist the returned lead, and return classification/suppression/draft/idempotency fields.
- Never call Resend or send an email from this route. Actionable replies create a pending draft only.
- Preserve duplicate event idempotency across repeated HTTP requests.
- Keep the route tailnet-internal; do not add a public Caddy route for `/inbound/reply`.

### HTTP tests

Run the bridge as a child process with an isolated temporary `THEOFORGE_LEADS_DIR`, `BRIDGE_HOST=127.0.0.1`, collision-free `BRIDGE_PORT`, `RESEND_ENV_PATH` pointing to an empty temp file, `MERCER_PROFILE_DIR` pointing to an empty temp directory, and `BRIDGE_NOTIFY_DRY_RUN=1`. Seed one lead JSON fixture through the temp directory. Test health, positive reply → one pending draft, repeated event → idempotent no-op, unsubscribe → suppression/no draft, unknown sender → 404, malformed input → 400, and verify no Resend request was attempted.

### Verification

```bash
node --check services/theoforge-bridge/server.mjs
node --test services/theoforge-bridge/inbound.test.mjs services/theoforge-bridge/inbound-http.test.mjs services/theoforge-bridge/outreach.test.mjs
```

Return exactly `STATUS`, `CHANGES`, `VERIFIED`, and `GAPS`. Do not commit, push, branch-switch, reset, clean, or touch secrets.
