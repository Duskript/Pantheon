# Resend + listmonk Free-Tier Setup

Generated: 2026-08-09
Owner: Hermes
Context: Cybermage approved the zero-cashflow path: relay-7 listmonk as list/campaign system, Resend free tier as the first outbound sender.

## Current state

Already done:

- listmonk is deployed on relay-7.
- listmonk is tailnet-only at `http://100.100.46.52:9000/admin`.
- `Operator Field Report` list exists.
- Public list UUID: `debcd121-5f81-4378-88ad-81672994bc95`.
- Public subscription smoke test passed.

Current verified state:

- Resend key was recovered from the prior TheoForge setup record, stored in the main env at `/home/konan/.hermes/.env` locally and on relay-7, and kept root-only for listmonk at `/opt/listmonk/secrets/resend_api_key`.
- Resend API probe succeeds with HTTP 200.
- Resend account has domain `theoforgesolutions.com`.
- Resend domain status is currently `partially_failed`:
  - DKIM `resend._domainkey` = verified.
  - Receiving MX = verified.
  - SPF/MX on `send.theoforgesolutions.com` = failed in Resend.
- listmonk SMTP is configured for Resend and SMTP login succeeds with code `235`.

Remaining DNS fix:

- Add or repair Resend's required `send.theoforgesolutions.com` MX/TXT records in Cloudflare, then re-run Resend verify. Hermes found the Iris Cloudflare token but DNS-record API calls returned `403 Authentication error`, so this needs either a broader token or dashboard edit.

## Resend SMTP settings for listmonk

From Resend docs:

| Field | Value |
|---|---|
| Host | `smtp.resend.com` |
| Port | `465` preferred, or `587` |
| Username | `resend` |
| Password | Resend API key |
| Security | SSL/TLS for `465`; STARTTLS for `587` |

## Recommended sender identity

Preferred future sender subdomain for reputation isolation:

```text
newsletter.theoforgesolutions.com
```

Current working sender configured in listmonk because the existing Resend account has `theoforgesolutions.com`:

```text
from: Operator Field Report <field-report@theoforgesolutions.com>
reply-to: reply@theoforgesolutions.com or newsletter@theoforgesolutions.com
```

## Optional future setup for a dedicated newsletter subdomain

The current account/domain are already usable for SMTP auth. If we want better reputation isolation later, add this dedicated domain in Resend:

1. Add domain: `newsletter.theoforgesolutions.com`.
2. Copy the DNS records Resend gives for DKIM/SPF/verification.
3. Add those records in Cloudflare DNS.
4. Wait until Resend says domain is verified.
5. Re-run `/opt/listmonk/apply-resend-smtp.py` with `--from-email field-report@newsletter.theoforgesolutions.com`.

## What Hermes prepared now

- Disabled listmonk's fake default SMTP entry so it cannot accidentally try `smtp.yoursite.com`.
- Set listmonk `app.site_name` to `Operator Field Report`.
- Set listmonk `app.root_url` to `http://100.100.46.52:9000`.
- Installed the root-only Resend SMTP apply script on relay-7:

```text
/opt/listmonk/apply-resend-smtp.py
```

## Applied command

Hermes stored the existing Resend key root-only and applied SMTP with:

```bash
sudo /opt/listmonk/apply-resend-smtp.py \
  --key-file /opt/listmonk/secrets/resend_api_key \
  --from-email field-report@theoforgesolutions.com \
  --hello-hostname theoforgesolutions.com
```

Verified listmonk settings:

```text
smtp_host=smtp.resend.com, enabled=true, username=resend, port=465, from=field-report@theoforgesolutions.com
app.from_email="Operator Field Report <field-report@theoforgesolutions.com>"
app.site_name="Operator Field Report"
```

Next:

1. Fix the Resend SPF/MX DNS records Cloudflare-side.
2. Re-run Resend verify until `theoforgesolutions.com` is fully verified, not `partially_failed`.
3. Send one test email to Cybermage/Konan.
4. Wire n8n signup flow to listmonk public subscription endpoint.

## Do not do

- Do not run raw SMTP from relay-7.
- Do not pay for Cloudflare Workers Paid just for Email Sending.
- Do not expose listmonk admin publicly until Cloudflare Access or route hardening exists.
- Do not put Resend keys in browser JavaScript, Ghost posts, markdown, or Discord logs.
