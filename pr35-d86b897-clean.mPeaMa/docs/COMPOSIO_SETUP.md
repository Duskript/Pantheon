# Getting your Composio API key

The Pantheon wizard's Step 4 ("Connect Integrations") uses [Composio](https://composio.dev) to handle OAuth flows for Gmail, Google Calendar, Notion, Slack, GitHub, and ~250 other tools. The Pantheon-onboarding integration path **exclusively** uses Composio — n8n is a separate, optional workflow tool that is intentionally not part of the wizard.

This walkthrough covers how to get Composio credentials so the wizard's "Connect" buttons work.

---

## 1. Create a Composio account

1. Go to https://composio.dev
2. Sign up (free tier is fine — the Pantheon install doesn't need a paid plan)
3. Verify your email

## 2. Create a project and grab your keys

1. In the Composio dashboard, click **Settings → API Keys** (or follow the onboarding flow)
2. You'll see two values:
   - **Consumer Key** (also called API Key in some docs) — looks like `comp_xxx...`
   - **Auth Token** (also called Integration Token) — looks like `eyJ...` (a JWT)
3. Copy both. You won't be able to see the Auth Token again after closing the page.

## 3. Add them to your Pantheon install

When the install script runs Phase 4 (Composio bridge), it will prompt you interactively. Paste the keys when asked. They're written to `~/.hermes/.env` (chmod 600, only your user can read).

If you skipped the prompt or want to add them later:

```bash
nano ~/.hermes/.env
# Find these two lines:
COMPOSIO_CONSUMER_KEY=
COMPOSIO_AUTH_TOKEN=
# Paste your values after the = signs
```

Then restart the bridge:

```bash
systemctl --user restart composio-bridge
curl http://localhost:8789/health
# expected: {"status":"ok","composio":true,"connections":0}
```

(The `connections:0` is normal — you haven't connected any apps yet. The wizard will start populating that.)

## 4. Verify in the wizard

Open `http://localhost:8787/onboarding/welcome` → Step 4 ("Connect Integrations"). You should see a list of providers (Gmail, GitHub, Slack, etc.). Click any one to start the OAuth flow.

If Step 4 says "Connection service not reachable," the bridge isn't running or doesn't have keys. Check:

```bash
systemctl --user status composio-bridge
curl http://localhost:8789/health
```

## Troubleshooting

- **"Invalid consumer key"** — You copied the wrong field. The Consumer Key is short (`comp_xxx...`), the Auth Token is a long JWT.
- **Bridge keeps restarting** — Check `journalctl --user -u composio-bridge -n 50`. The bridge refuses to start without both keys.
- **"composio:false" in /health** — The bridge is up but doesn't see your keys. Re-check `~/.hermes/.env` (no trailing whitespace, no quotes around the values).

---

## Why this is in the install docs and not the wizard

Composio's free tier allows unlimited connections with their hosted OAuth flows. There's no Pantheon-specific reason to skip this — we just don't want the install script to silently fail or interrupt the install flow when you don't have keys yet. The interactive prompt lets you skip and add them later.

For the **Enterprise edition** (private repo with pre-populated keys), the install runs with `--enterprise` and skips this prompt entirely — your keys are already in `~/.hermes/.env` from the Enterprise repo's `enterprise.env`.
