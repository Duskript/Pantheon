# Cloudflare + listmonk Newsletter Architecture

Generated: 2026-08-09
Owner: Hermes
Context: Cybermage asked whether Cloudflare would be used with listmonk.

## Verdict

Yes. **Cloudflare + listmonk is the strongest long-term shape.**

Use Cloudflare for the public edge, spam protection, DNS, TLS, and reply routing. Use listmonk as the actual self-hosted newsletter/list system.

## Recommended production-ish shape

```text
Public visitor
  → Cloudflare Pages: Iris landing page
  → Cloudflare Turnstile: anti-spam proof
  → Cloudflare Worker: public signup endpoint
  → listmonk API/public subscription endpoint
  → listmonk: subscribers, lists, campaigns, unsubscribe, analytics
  → SMTP relay: SES/Postmark/Mailgun/Resend/Cloudflare Email Service if acceptable

Replies
  → Cloudflare Email Routing: newsletter@ / reply@
  → destination inbox or Worker
  → n8n/Hermes notification + validation metrics
```

## What each layer owns

### Cloudflare

- DNS and domain verification records.
- Cloudflare Pages/Workers hosting for the landing page.
- Turnstile on signup forms.
- Optional Worker validation layer before listmonk.
- Cloudflare Tunnel or reverse proxy in front of listmonk public endpoints.
- Email Routing for inbound replies/catch-all addresses.

### listmonk

- Source of truth for subscribers.
- Lists and segments.
- Campaign editor and broadcasts.
- Unsubscribe/preference flows.
- Basic analytics.
- Subscriber API for n8n/Worker integration.

### n8n

- Optional orchestration layer:
  - notify Discord/Telegram on signup;
  - append validation metrics;
  - enrich or tag leads;
  - sync to CRM/spreadsheet;
  - process reply signals.

### SMTP / outbound email

listmonk still needs an outbound sender.

Best mature options:

- Amazon SES — cheapest scale path.
- Postmark — best quality, more expensive.
- Mailgun — flexible.
- Resend — good developer UX, fine bridge.

Cloudflare Email Service can potentially work as the SMTP relay because Cloudflare documents authenticated SMTP on `smtp.mx.cloudflare.net:465`, username `api_token`, password = Cloudflare API token with Email Sending: Edit permission. But it is still Email Sending Beta, Workers Paid is required for arbitrary recipients, and limits include 3,000 outbound emails/month included then `$0.35/1,000`, plus 50 recipients per SMTP session and 5 MiB message size.

For v1 validation, Cloudflare Email Service as relay is plausible. For serious newsletter deliverability, use SES/Postmark/Mailgun/Resend unless Cloudflare proves itself in real inbox tests.

## Security posture

Do not expose the whole listmonk admin UI naked to the internet.

Expose only what is needed:

- public subscription pages/endpoints;
- link tracking endpoint;
- campaign pixel endpoint;
- webhook endpoints as needed.

Keep admin private:

- Tailscale-only, or
- Cloudflare Access-protected, or
- private reverse proxy route with SSO.

listmonk docs separate private admin endpoints (`/api/*`, `/admin/*`) from public endpoints (`/subscription/*`, `/link/*`, `/campaign/*`, `/public/*`, service webhooks, uploads), which maps cleanly to this split.

## Two viable wiring options

### Option A — Simpler: Cloudflare Page posts to listmonk public subscription

```text
Landing page form
  → listmonk /subscription/* or /api/public/subscription
```

Pros:
- fewer moving parts;
- fastest once listmonk is public behind Cloudflare.

Cons:
- less custom validation/orchestration;
- harder to notify/score/tag unless listmonk/webhooks cover it.

### Option B — Better operator workflow: Cloudflare Worker or n8n in front

```text
Landing page form
  → Cloudflare Worker /signup
  → validate Turnstile + consent + email
  → POST to listmonk subscriber API
  → notify n8n/Hermes
```

Pros:
- clean validation boundary;
- no direct browser access to listmonk admin API;
- easy metrics/notifications;
- can swap listmonk/Resend later without changing page.

Cons:
- one extra component to maintain.

## Recommendation

Use **Option B** if we are building this as an operator-grade pipeline.

Final architecture:

```text
Cloudflare Pages + Turnstile
  → Cloudflare Worker signup endpoint
  → listmonk subscriber API
  → listmonk campaigns
  → external SMTP relay
  → Cloudflare Email Routing for replies
  → n8n/Hermes validation metrics
```

This is the cleanest “owned list + Cloudflare edge” design.
