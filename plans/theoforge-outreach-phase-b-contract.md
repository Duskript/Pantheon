# TheoForge Outreach — Fusion Phase B Spec Contract

**Owner:** Hermes planner
**Executor:** Fusion implementation lane
**Date:** 2026-09-01
**Status:** implementation authorized; executor must not commit, push, deploy, or mutate production

## Objective

Build the first operator-facing approval surface for the existing TheoForge outreach state machine.

The console must let a tailnet operator:

1. See pending and failed outbound drafts across canonical leads.
2. Read the full recipient, subject, body, source lead, and latest inbound context.
3. Reject a draft with an operator identity and reason.
4. Approve a draft with an operator identity and approval version.
5. Send only after explicit approval, through the existing `/outreach/send` route.
6. See the resulting state and provider ID without page reload ambiguity.

The surface is an internal operations tool. It must be served by the Tailscale-bound bridge only. It must not be added to relay-7 public Caddy or the public TheoForge landing page.

## Current verified architecture

- Bridge source: `/home/konan/pantheon/services/theoforge-bridge/`
- Bridge service: `theoforge-bridge.service`, bound to `100.115.50.41:4323`
- Existing pure outreach state machine: `outreach.mjs`
- Existing bridge routes:
  - `GET /outreach/drafts?email=...`
  - `POST /outreach/drafts`
  - `POST /outreach/approve`
  - `POST /outreach/send`
- Existing public relay app: `/srv/theoforge` on relay-7; out of scope
- Existing operator APIs are tailnet-internal; preserve that boundary
- Existing draft statuses: `draft`, `approved`, `send_failed`, `sent`
- Existing lead files: `$THEOFORGE_LEADS_DIR/*.json`

## Allowed files

The executor may modify or create only:

- `services/theoforge-bridge/outreach.mjs`
- `services/theoforge-bridge/outreach.test.mjs`
- `services/theoforge-bridge/server.mjs`
- `services/theoforge-bridge/operator/index.html` (create)
- `services/theoforge-bridge/operator.test.mjs` (create)

The executor must not modify:

- `inbound.mjs`, `inbound.test.mjs`, `inbound-http.test.mjs`
- `theoforge-inbound-forward.py`
- `caddyfile_blog`
- service units, credentials, lead files, relay-7 files, or unrelated Pantheon work

## Outreach state-machine contract

Add and export:

```js
rejectDraftRecord(lead, input, options = {}):
  { ok, lead, draft, idempotent, error?, fields? }
```

Requirements:

- Require `draft_id`, `rejected_by`, and `rejection_reason`.
- Bound `rejected_by` to 200 characters and `rejection_reason` to 500 characters.
- Reject only `draft` or `send_failed` drafts.
- Return `draft_not_found` for an unknown draft.
- Return `already_sent` for a sent draft.
- Return `draft_not_rejectable` for approved/rejected drafts.
- Set `status: "rejected"`, `rejected_by`, `rejected_at`, and `rejection_reason`.
- Clear transient `last_error` only when the reason is recorded; never clear provider send history.
- Do not mutate the caller's lead.
- Repeating the same rejection for an already rejected draft returns `ok: true`, `idempotent: true`, with the existing draft unchanged.
- No network, filesystem, or LLM calls.

## Queue API contract

Add a tailnet-only `GET /outreach/queue` route in `server.mjs`.

Query parameters:

- `status` — optional comma-separated statuses; default `draft,send_failed`
- `limit` — optional positive integer; default 100, hard maximum 500

Response:

```json
{
  "ok": true,
  "count": 1,
  "items": [
    {
      "lead_email": "jane@example.com",
      "lead_name": "Jane Doe",
      "leadId": "lead-jane-001",
      "pipeline_stage": "prospect",
      "latest_inbound": {},
      "draft": {}
    }
  ]
}
```

Requirements:

- Scan only the configured canonical leads directory.
- Ignore malformed/non-JSON files without crashing the request; count only valid matching drafts.
- Return drafts with their complete current fields; do not redact operator-visible draft body.
- Include `lead_email`, `lead_name`, `leadId`, `pipeline_stage`, and the latest `conversation` entry where `channel === "email_in"`.
- Sort newest draft first by `created_at`, then stable `lead_email`, then `draft_id`.
- Never expose `/outreach/queue` through relay-7 Caddy; the bridge binding remains the access boundary.
- Return 400 for invalid `limit` or unknown/empty requested statuses.

Add `POST /outreach/reject` using the same lead lookup and atomic persistence pattern as approve.

## Operator UI contract

Serve `GET /operator` and `GET /operator/` from the bridge’s existing static handler, rooted at `services/theoforge-bridge/operator/index.html`.

The UI must:

- Use same-origin `fetch` only.
- Render a clear page title: `TheoForge Approval Queue`.
- Load `/outreach/queue?status=draft,send_failed` on initial load and from a visible Refresh button.
- Show loading, empty, error, and success states.
- Display each item’s lead identity, pipeline stage, inbound subject/body context, draft recipient, sender, subject, body, status, and timestamps.
- Provide accessible controls:
  - operator identity input, required before approve/reject/send;
  - approval version input with a deterministic default;
  - reject reason input, required before reject;
  - Approve button for `draft` and `send_failed`;
  - Reject button for `draft` and `send_failed`;
  - Send button only for `approved`;
  - disabled state while a request is pending;
  - `aria-live` status feedback and keyboard-accessible native controls.
- After any mutation, replace the affected item from the returned draft state or refresh the queue; do not claim success on a non-2xx response.
- Never call `/outreach/send` from an unapproved draft; the UI must not hide a 409 approval error.
- Never send automatically on load or refresh.
- Keep CSS local to the operator page; do not alter public landing-page styling.
- Include a visible boundary notice: `Tailnet-only operator surface — no public campaign sending.`

## Tests required

`outreach.test.mjs` must add coverage for:

- rejection validation and bounds;
- rejection of draft/send_failed;
- rejection idempotency;
- rejection immutability;
- approved/sent/rejected guard behavior.

`operator.test.mjs` must run `server.mjs` as an isolated child with a temporary leads directory and assert:

- `GET /operator` and `/operator/` return HTML;
- `GET /outreach/queue` returns the expected sorted pending item;
- status filtering and limit work;
- invalid query returns 400;
- malformed lead files do not crash queue reads;
- `POST /outreach/reject` records rejection metadata and persists it;
- rejected draft cannot be approved or sent;
- existing approval and send routes remain approval-gated;
- no Resend request occurs during queue or reject tests.

Use the existing test isolation pattern from `inbound-http.test.mjs`; never point tests at real leads or credentials.

## Verification commands

From `/home/konan/pantheon`:

```bash
node --check services/theoforge-bridge/server.mjs
node --check services/theoforge-bridge/outreach.mjs
node --test services/theoforge-bridge/outreach.test.mjs services/theoforge-bridge/inbound.test.mjs services/theoforge-bridge/inbound-http.test.mjs services/theoforge-bridge/operator.test.mjs
```

Additional parent verification after implementation:

```bash
curl -fsS http://100.115.50.41:4323/healthz
curl -fsS http://100.115.50.41:4323/operator
curl -fsS 'http://100.115.50.41:4323/outreach/queue?status=draft,send_failed'
```

Then manually verify in a tailnet browser:

- operator page renders;
- queue item is readable at desktop and narrow viewport;
- approve reveals send action but does not send;
- reject removes/marks the item;
- send is impossible while status is `draft`;
- no public Caddy or landing-page route changed.

## Non-goals

- No public admin route or Caddy change.
- No authentication redesign; Tailscale binding remains the current boundary.
- No campaign scheduler, queue worker, retry worker, bounce reconciliation, or delivery webhook changes.
- No automatic send, bulk approve, bulk send, or delete operation.
- No React/Vite migration.
- No changes to inbound classification or Resend webhook forwarding.
- No commits, pushes, deployments, service restarts, or credential edits by the executor.

## Exit gate

Phase B implementation is not accepted until:

1. Only allowed files changed.
2. Focused tests and syntax checks pass independently.
3. Queue ordering/filtering and rejection are proven in isolated HTTP tests.
4. Existing 39+ inbound/outreach tests remain green.
5. Parent independently verifies the live tailnet page and queue.
6. A separate QA pass reviews the diff and reports `SHIP` or named fixes.
7. Production deployment, if approved later, is a separate parent-owned action with backup, service restart, and live browser proof.
