# Cloudflare for Newsletter Signup / Mailing List

Generated: 2026-08-09
Owner: Hermes
Context: Cybermage asked whether something through Cloudflare could work instead of Resend/listmonk for the newsletter lane.

## Verdict

Cloudflare is good as the **front door and glue**, but not the best standalone mailing-list app.

Recommended interim architecture:

```text
Cloudflare Pages / Iris landing page
  + Turnstile anti-spam
  → Cloudflare Worker or n8n webhook
  → Resend Contacts/Segments/Broadcasts for validation
  → optional later mirror/migrate to listmonk
```

Cloudflare alone can receive inbound mail, store contacts, and send transactional emails, but it does not replace a newsletter/list-management product unless we build that layer ourselves.

## What Cloudflare can do well

### 1. Host the landing page

Cloudflare Pages or Workers can host the Iris landing page close to users with low operational friction.

### 2. Protect the signup form

Cloudflare Turnstile is a smart CAPTCHA alternative that can be embedded into any site, including sites not proxied through Cloudflare. For the newsletter signup, Turnstile is useful before accepting `POST /webhook/newsletter-signup`.

### 3. Store signup records

Cloudflare D1 is a managed serverless SQL database with SQLite semantics and Worker/API access. It can store a lightweight subscriber/audit table:

- email
- name
- interest
- source
- consent_at
- resend_contact_id
- unsubscribed_at

This is useful as a neutral backup/source-of-truth while Resend or listmonk handles the actual campaign sending.

### 4. Handle inbound replies / catch-all addresses

Cloudflare Email Routing handles incoming emails and can route them to Workers or forwarding addresses. Great for addresses like:

- `newsletter@domain.com`
- `reply@domain.com`
- `tools@domain.com`

This helps capture replies as validation signals.

### 5. Send transactional emails — cautiously

Cloudflare Email Service now documents Email Sending Beta for outbound transactional emails, available on Workers Paid. Pricing docs say Workers Paid includes 3,000 outbound emails/month, then $0.35 per 1,000 emails. Limits docs say each email can have up to 50 combined recipients.

That makes it plausible for welcome/confirmation messages, but not my first pick for marketing broadcasts yet.

## What Cloudflare does NOT replace cleanly

Cloudflare is not, by itself, a Mailchimp/listmonk/Beehiiv-style newsletter app.

Missing or custom-build territory:

- full contact list UI;
- campaign editor;
- segment builder UX;
- preference center;
- automatic marketing unsubscribe flows;
- campaign performance dashboard;
- import/export workflows;
- suppression/bounce workflow suitable for non-developers;
- newsletter archive/editor experience.

We could build those on Workers + D1 + Email Service, but that is product work. For this validation lane, that is too much ceremony before proving demand.

## Best Cloudflare-flavored option

Use Cloudflare for the edges, not the list app:

```text
Cloudflare Pages
  hosts landing page

Cloudflare Turnstile
  blocks bot signups

Cloudflare Worker or n8n webhook
  validates + normalizes signup payload

D1 / Postgres / Google Sheet
  stores audit row and validation metrics

Resend
  manages contacts, segments, broadcasts, unsubscribe, delivery

Cloudflare Email Routing
  receives replies to newsletter@ / reply@ and forwards or routes to Worker
```

This gives us a strong, cheap, fast architecture without building a custom ESP.

## Cloudflare-only option

Possible, but not recommended for v1:

```text
Cloudflare Pages
  → Worker signup endpoint
  → D1 subscriber table
  → Cloudflare Email Service transactional send
  → custom unsubscribe endpoint
  → custom broadcast loop / queue
```

This is technically elegant but becomes a custom newsletter platform. Useful later if the product itself is “operator-grade mailing list infrastructure,” not useful for validating whether people want the field report.

## Comparison against Resend

| Need | Cloudflare only | Resend |
| --- | --- | --- |
| Landing page | Excellent | No |
| Bot protection | Excellent via Turnstile | No |
| Subscriber storage | Possible via D1/custom | Built in Contacts/Segments |
| Newsletter broadcasts | Custom work / Email Sending Beta | Built in Broadcasts |
| Unsubscribe handling | Custom work | Built in for Broadcasts |
| Reply capture | Excellent via Email Routing | Webhooks/events; inbound depends setup |
| Speed to launch | Medium/slower | Fast |
| Ownership | Higher | Lower |

## Recommendation

For right now:

**Cloudflare + Resend** is better than **Cloudflare instead of Resend**.

Use:

- Cloudflare Pages/Worker/Turnstile for the landing page + signup endpoint;
- Resend for contacts, broadcasts, unsubscribe, and deliverability;
- n8n as the orchestration layer;
- Cloudflare Email Routing for reply/catch-all capture;
- listmonk later if/when we want the list-of-record self-hosted.

## Sources checked

- https://developers.cloudflare.com/email-service
- https://developers.cloudflare.com/email-service/platform/pricing
- https://developers.cloudflare.com/email-service/platform/limits
- https://developers.cloudflare.com/email-routing/
- https://developers.cloudflare.com/workers/tutorials/send-emails-with-resend
- https://developers.cloudflare.com/d1/
- https://developers.cloudflare.com/turnstile/
