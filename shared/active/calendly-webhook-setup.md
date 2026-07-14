# Calendly Appointment Notifications — Setup Summary

## Status
✅ **Active and verified** — end-to-end test passed through public URL

## Architecture
```
Calendly booking → Webhook POST → Tailscale Funnel → Hermes Gateway → Telegram DM
```

## Key Details

| Item | Value |
|------|-------|
| **Public URL** | `https://pantheon.tail164759.ts.net/webhooks/calendly-bookings` |
| **Funnel port** | 8644 (Hermes gateway webhook platform) |
| **Events** | `invitee.created`, `invitee.canceled` |
| **Calendly scope** | User-scoped (Konan's bookings only) |
| **Delivery mode** | Direct (zero LLM cost — no agent spin-up) |
| **Calendly sub URI** | `https://api.calendly.com/webhook_subscriptions/94ee4897-b1ac-4c9c-a2f6-efa3e5673795` |
| **HMAC secret** | Stored in `~/.hermes/webhook_subscriptions.json` |

## Off-switch
To stop incoming webhooks (disconnect the funnel):
```bash
tailscale funnel --https=443 off
```
To resume:
```bash
tailscale funnel --bg --set-path=/ http://localhost:8644
tailscale funnel status  # verify Funnel is: ON
```

Or just disable the Calendly subscription:
```bash
curl -X DELETE "https://api.calendly.com/webhook_subscriptions/94ee4897-b1ac-4c9c-a2f6-efa3e5673795" \
  -H "Authorization: Bearer <calendly-token>"
```

## What happens on a booking
1. Calendly sends a signed POST with booking data
2. Tailscale forwards it to the Hermes gateway on port 8644
3. Gateway verifies the HMAC signature, matches event type
4. Renders the prompt template with booking details
5. Delivers directly to Telegram — **no LLM cost, no agent loop**
6. Message includes: name, email, time, meeting type, reschedule/cancel links
