# Resend as Interim Mailing List Layer

Generated: 2026-08-09
Owner: Hermes
Context: Iris landing page posts newsletter signup payloads to `/webhook/newsletter-signup`; n8n on CachyOS is the integration layer.

## Verdict

Yes — **Resend works for the time being**.

But treat it as a **validation-phase hosted email/list layer**, not as the final self-hosted mailing-list system. It is a strong temporary fit because it already has:

- verified-domain email sending;
- API keys;
- Contacts API;
- Segments/Broadcasts model;
- Broadcast API;
- webhook/event support;
- n8n integration maintained/verified by Resend according to n8n’s integration page.

It is not self-hosted. If the requirement becomes “own the list app and data plane,” migrate to listmonk later and keep Resend/Postmark/SES/Mailgun as outbound relay.

## Why it works for this lane

The Week 1 validation target is tiny: 25 subscribers, 5 replies, or 1 paid opportunity. Resend is good enough for that because the list system only needs to:

1. accept signup contacts from the Iris landing page;
2. preserve consent/source metadata;
3. send a welcome email or first newsletter;
4. track delivery/open/click/reply signals enough to validate demand;
5. handle unsubscribe for marketing broadcasts.

Resend docs describe itself as an email API for developers and require a verified domain plus API key before sending. It supports transactional emails and marketing campaigns/broadcasts distributed to a contact list.

## How to wire it now

```text
Iris landing page form
  → n8n webhook: POST /webhook/newsletter-signup
  → validate email + consent
  → Resend: create/update contact
  → Resend: add contact to segment/topic for Operator Field Report
  → optional: send welcome email
  → notify Discord/Telegram
```

Fields to send from n8n:

```json
{
  "email": "subscriber@example.com",
  "first_name": "Optional name split",
  "unsubscribed": false,
  "properties": {
    "interest": "AI agents / business automation / MCP tools",
    "source": "operator-field-report-landing-page",
    "consent_at": "2026-08-09T18:57:17Z"
  }
}
```

For broadcasts, use a Segment such as:

`Operator Field Report — Early Validation`

## Pros

- Fastest path to live validation.
- No new Docker service to deploy before testing demand.
- Good developer API and clean n8n surface.
- Lets us use the same tool for welcome email, broadcasts, and event webhooks.
- Domain verification/SPF/DKIM flow is straightforward compared with running our own sender.
- Easy migration later: export contacts or mirror contacts into Postgres/listmonk from n8n.

## Cons / gotchas

- Not self-hosted.
- Not the long-term “owned infrastructure” choice.
- Marketing/list features are newer and may be less deep than listmonk/Mautic for advanced segmentation and automation.
- Audiences docs indicate older Audiences endpoints are deprecated in favor of Segments, so build against Segments/Contacts where possible.
- Free tier limits are enough for validation but not for scale; current public pricing shows Free at 3,000 emails/month and 100/day, with paid tiers for higher volume. Marketing contacts/broadcast plan limits should be checked in the dashboard before a real launch.

## Recommended path

Use Resend immediately for the validation loop:

1. Verify sending domain.
2. Create API key.
3. Create segment/topic: `Operator Field Report — Early Validation`.
4. Wire n8n webhook to Resend Contacts/Segments.
5. Send a welcome email after signup.
6. Send first issue manually or via Resend Broadcast.
7. Track validation: 25 subs, 5 replies, or 1 paid opportunity.

Then, if this starts working, migrate the list-of-record to **listmonk** and keep Resend only as outbound delivery if we like its deliverability/API.

## Decision

**Use Resend now. Plan listmonk as the self-hosted upgrade.**

This gives us speed without locking us into the final architecture.

## Sources checked

- https://resend.com/docs
- https://resend.com/docs/dashboard/audiences
- https://resend.com/docs/api-reference/contacts/create-contact
- https://resend.com/docs/api-reference/broadcasts/create-broadcast
- https://resend.com/pricing
- https://n8n.io/integrations/resend/
