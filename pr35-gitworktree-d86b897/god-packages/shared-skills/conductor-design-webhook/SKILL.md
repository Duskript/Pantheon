---
name: conductor-design-webhook
description: "Use when the user says 'set up a webhook', 'connect X service to Pantheon', 'receive notifications from Y', or any request to bring external events into the Pantheon. Produces a webhook integration config and rule, saved to ~/pantheon/conductor/webhooks/ and ~/pantheon/conductor/rules/."
version: 1.0.0
author: Thoth & Hermes (Pantheon)
license: MIT
metadata:
  hermes:
    tags: [conductor, webhook, integration, external, event]
    related_skills: [conductor-design-rule, conductor-design-workflow]
---

# Conductor Webhook Designer

## When to Use

Load this skill when the user wants to connect an external service to the Pantheon event system. Keywords: "webhook," "connect X," "receive from," "monitor Y," "set up integration for."

## Process

### Step 1: Identify the External Service

Ask:
- **Which service is sending events?** (GitHub, Stripe, Reddit, YouTube, Jira, Slack, custom)
- **What type of events do you want to receive?** (PR opened, payment succeeded, mention, video uploaded)
- **Does the service support webhooks natively, or do we need to poll an API?**

### Step 2: Define How to Receive

| Method | When | Example |
|---|---|---|
| Native webhook | Service sends HTTP POST to a URL | GitHub, Stripe, Jira |
| Polling | Cron job checks API periodically | Reddit, YouTube, RSS feeds |
| NATS bridge | Tallon's instance forwards via Relay-7 | Cross-Pantheon events |

If native webhook, Conductor will need a webhook endpoint URL. Ask if the user has:
- A domain/subdomain to receive webhooks on
- Any auth tokens or secrets the service requires for verification

### Step 3: Determine Handling Mode

Same as rule designer — walk through the modes:

| Mode | Best For |
|---|---|
| `log_only` | Reddit mentions, YouTube uploads, passive monitoring |
| `notify` | Low-priority FYI alerts |
| `approval_required` | Actionable events (PR review request, deploy request) |
| `route_on_approval` | Known actionable events with predictable routing |

### Step 4: Define the Payload Mapping

Ask: "What fields from the webhook payload matter?"
- Map the service's payload structure to the Conductor event envelope
- Identify which fields go into the notification summary
- Identify which fields go into the context bag if dispatched to a god

### Step 5: Write Artifacts

Two files:
1. **Webhook config** → `~/pantheon/conductor/webhooks/{service}-{purpose}.yaml`
   - Source, endpoint, auth method, payload parsing rules
2. **Reaction rule** → `~/pantheon/conductor/rules/{service}-{purpose}.yaml`
   - When → handling_mode → action

### Step 6: Validate

- [ ] Webhook endpoint URL is reachable
- [ ] Auth secrets are configured (not hardcoded in YAML)
- [ ] Handling mode is appropriate for external source
- [ ] Payload mapping covers all fields the downstream workflow needs
- [ ] Unknown payloads fall to safe defaults

### Step 7: Register

If the service needs a webhook URL registered (GitHub repo settings, Stripe dashboard, etc.), note that as a manual step for the user.

### Step 8: Confirm

Summarize:
- Service connected and event type monitored
- Handling mode
- What Konan will see when an event arrives
- Any manual registration steps remaining
