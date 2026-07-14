# n8n setup (optional, currently broken — out of scope)

> **Status as of 2026-06-02:** The n8n systemd service is **crash-looping** due to a broken `npm install` in the bundled n8n package. Pantheon does not install, start, or depend on n8n. The wizard's "Connect Integrations" step (Step 4) uses **Composio** exclusively — see [`COMPOSIO_SETUP.md`](./COMPOSIO_SETUP.md).
>
> This document exists for users who want to fix n8n themselves and use it as a separate workflow tool. It is **not** part of the standard install path.

---

## What's broken

```
$ systemctl --user status n8n
× n8n.service - n8n workflow engine
     Active: failed (Result: exit-code) since ...
  Process: 12345 ExecStart=/usr/bin/node ./node_modules/n8n/bin/n8n (code=exited, status=1/FAILURE)
  Main PID: 12345 (code=exited, status=1/FAILURE)
```

The bundled n8n's `bin/n8n` script does `require('../package')` and fails with `Cannot find module '../package'`. The npm install is broken.

## Why we left it broken

The user explicitly decided not to fix n8n in the install pipeline:
- The wizard's integration path uses Composio, not n8n. n8n is power-user plumbing.
- Fixing the npm install is a yak-shave that doesn't unblock any wizard step.
- If you need n8n for a custom workflow, the fix is below.

## The fix (if you want it)

### Option A: Reinstall n8n from npm

```bash
# Remove the broken install
rm -rf ~/pantheon/.n8n/node_modules

# Reinstall
cd ~/pantheon/.n8n
npm install n8n --save

# Test
npx n8n --version
# expected: a version number, not a stack trace

# Restart the service
systemctl --user restart n8n
systemctl --user status n8n
```

### Option B: Switch to n8n cloud

If you don't want to host n8n yourself, the cloud version (https://n8n.cloud) has a free tier. The Pantheon n8n_client (`webui/api/n8n_client.py`) is already configurable to point at a remote n8n instance — set `N8N_HOST` and `N8N_API_KEY` in `~/pantheon/.env` to your cloud instance URL and API key.

## What Pantheon does with n8n (when it's working)

- **`/api/n8n/*` routes** in `webui/api/routes.py` — proxy requests to the n8n REST API
- **`setup_n8n` function** in `webui/api/onboarding.py:1794` — the wizard's old Step 4 used to call this; the new wizard uses Composio
- **`webui/api/n8n_client.py`** — the client library

None of these are required for the wizard to work. They exist for users who want to wire n8n workflows into their Pantheon.

## Re-enabling n8n in the install script (future)

When n8n is fixed, add a Phase 3b to `install-pantheon.sh`:

```bash
# Phase 3b: n8n (was skipped during cleanup, now optionally enabled)
phase_3b_n8n() {
    if [[ -d "$PANTHEON_HOME/.n8n" ]]; then
        (cd "$PANTHEON_HOME/.n8n" && npm ci)
        cp "$PANTHEON_HOME/install/assets/systemd/n8n.service" \
           "$SYSTEMD_USER_DIR/n8n.service"
        systemctl --user daemon-reload
        systemctl --user enable --now n8n.service
    fi
}
```

But this is **not** part of the standard install path. The install script currently creates no n8n artifacts and the validate script intentionally has no n8n check.

---

If you fix n8n, please open a PR against `Duskript/Pantheon` and link the related install-pipeline issue. The Pantheon maintainer can then decide whether to add Phase 3b to the standard install.
