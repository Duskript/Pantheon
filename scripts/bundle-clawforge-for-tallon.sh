#!/usr/bin/env bash
# =============================================================================
# bundle-clawforge-for-tallon.sh
# =============================================================================
# Builds a self-contained tarball that gives Tallon's Pantheon instance
# everything it needs to connect to the Clawforge federation:
#
#   - clawforge-proxy.py + clawforge-messenger.py (daemons)
#   - systemd unit files (templated with __USER__ placeholders)
#   - starter ~/.hermes/clawforge.yaml with instance.id = "tallon"
#   - clawforge-tokens.env with the shared NATS client token
#   - INSTALL.md — Tallon-specific install excerpt
#
# Run this on Pantheon (Konan's box). Output goes to dist/.
#
# Security note: the resulting tarball contains a NATS client token. Treat
# it as you would any credential bundle — secure-channel delivery, not
# Telegram plaintext, not email, not a public repo.
# =============================================================================

set -euo pipefail

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PANTHEON_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DIST_DIR="${PANTHEON_DIR}/dist"
TOKENS_FILE="${HOME}/.hermes/clawforge-tokens.env"
RELAY_HOST="100.100.46.52"   # Tailscale IP for relay-7
INSTANCE_ID="tallon"

# ── Sanity checks ────────────────────────────────────────────────────────────
[[ -f "${TOKENS_FILE}" ]] || {
    echo "FATAL: ${TOKENS_FILE} not found." >&2
    echo "Run install-pantheon.sh or restore from your secret store." >&2
    exit 1
}

# Read the shared token. Use awk to avoid redaction in the shell command
# history (the pattern `=***` triggers terminal redaction in this environment).
TOKEN="$(awk -F= '$1 == "CLAWFORGE_CLIENT_TOKEN" { print $2; exit }' "${TOKENS_FILE}")"
[[ -n "${TOKEN}" ]] || {
    echo "FATAL: CLAWFORGE_CLIENT_TOKEN not found in ${TOKENS_FILE}" >&2
    exit 1
}

# ── Build dir ────────────────────────────────────────────────────────────────
TS="$(date -u +%Y%m%dT%H%M%SZ)"
STAGE_DIR="$(mktemp -d -t clawforge-bundle-tallon.XXXXXX)"
trap 'rm -rf "${STAGE_DIR}"' EXIT

mkdir -p "${STAGE_DIR}/scripts"
mkdir -p "${STAGE_DIR}/systemd"
mkdir -p "${STAGE_DIR}/config"
mkdir -p "${DIST_DIR}"

# ── Daemons (canonical) ──────────────────────────────────────────────────────
cp -v "${PANTHEON_DIR}/scripts/clawforge-proxy.py"     "${STAGE_DIR}/scripts/"
cp -v "${PANTHEON_DIR}/scripts/clawforge-messenger.py" "${STAGE_DIR}/scripts/"

# ── Systemd units (templated) ────────────────────────────────────────────────
cp -v "${PANTHEON_DIR}/scripts/clawforge-proxy.service"     "${STAGE_DIR}/systemd/"
cp -v "${PANTHEON_DIR}/scripts/clawforge-messenger.service" "${STAGE_DIR}/systemd/"

# ── Proxy config (Tallon-flavored) ───────────────────────────────────────────
cat > "${STAGE_DIR}/config/clawforge.yaml" <<YAML
# Clawforge Proxy v0.1.0 — Tallon instance config
# This file is read by clawforge-proxy.py on startup.

# Where to find the relay (NATS server). Reached over the Tailscale tailnet
# shared between Konan and Tallon.
relay:
  host: "${RELAY_HOST}"   # Tailscale IP for relay-7
  port: 4222
  # Token loaded from ~/.hermes/clawforge-tokens.env (CLAWFORGE_CLIENT_TOKEN)

# Who we are
instance:
  id: "${INSTANCE_ID}"
  display_name: "Tallon's Pantheon"
  # Edit this to match where your Pantheon repo lives on this box.
  god_registry: "/home/\$(whoami)/pantheon/gods/gods.yaml"

# How often to re-publish our profile (heartbeat). Seconds.
heartbeat_interval_seconds: 300

# Where to cache profiles from other instances we discover
peers_cache: "/home/\$(whoami)/.hermes/clawforge/known-instances.json"

# Where the daemon writes its log
log_file: "/home/\$(whoami)/.hermes/clawforge/proxy.log"

# NATS subjects we subscribe to (v0.1.0: profile sync + Pass 3 pattern sync)
subscribe:
  - "claw.profile.update"
  - "claw.package.publish.>"
  - "pattern.effective.>"
  - "pattern.recommendation.\${INSTANCE_ID}"
  - "pattern.request.\${INSTANCE_ID}.>"

# Subjects we publish to
publish:
  - "claw.profile.update"
YAML

# ── Tokens file (mode 0600, shared token, instance id baked in) ──────────────
cat > "${STAGE_DIR}/config/clawforge-tokens.env" <<ENV
# Clawforge client tokens for instance '${INSTANCE_ID}'
# Issued:  $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Host:    $(hostname)
# DO NOT COMMIT. Mode 0600. Shared token — same one Konan uses.
CLAWFORGE_CLIENT_TOKEN=${TOKEN}
CLAWFORGE_INSTANCE_ID=${INSTANCE_ID}
CLAWFORGE_NATS_HOST=${RELAY_HOST}
CLAWFORGE_NATS_PORT=4222
ENV
chmod 600 "${STAGE_DIR}/config/clawforge-tokens.env"

# ── INSTALL.md — Tallon-specific excerpt ─────────────────────────────────────
cat > "${STAGE_DIR}/INSTALL.md" <<MD
# Clawforge Connect — Tallon Install Bundle

**Bundle built:** $(date -u +%Y-%m-%dT%H:%M:%SZ)
**Relay host:** ${RELAY_HOST} (Tailscale IP, port 4222)
**Your instance ID:** ${INSTANCE_ID}

This bundle gives your Pantheon install everything it needs to talk to
the Clawforge federation bus. Konan built it from the canonical sources
in his Pantheon repo.

## What's in the bundle

\`\`\`
scripts/clawforge-proxy.py        # Daemon — heartbeats your profile, caches other instances
scripts/clawforge-messenger.py    # Daemon — receives claw.request.<god>.tallon, dispatches to hermes
systemd/clawforge-proxy.service   # systemd unit for the proxy (templated with __USER__)
systemd/clawforge-messenger.service  # systemd unit for the messenger
config/clawforge.yaml             # Your proxy config (instance.id: ${INSTANCE_ID})
config/clawforge-tokens.env       # The shared NATS client token (mode 0600)
INSTALL.md                        # This file
\`\`\`

## Prerequisites

- Pantheon repo is cloned to \`~/pantheon\` and Hermes Agent is at \`~/.hermes/\`
- Tailscale is installed and your machine can reach \`${RELAY_HOST}\` (Konan will share his tailnet if needed)
- You're on the same Linux user that runs Hermes (the systemd units use \`__USER__\` — set this below)

## Install steps

### 1. Drop the files in place

\`\`\`bash
# From wherever you saved the tarball
tar xzf clawforge-bundle-tallon-*.tar.gz -C /tmp/
cd /tmp/clawforge-bundle-tallon-*/

# Set the username the systemd units should run as
export USER_NAME="\$(whoami)"

# Daemons — copy to your Pantheon scripts dir
cp scripts/clawforge-*.py ~/pantheon/scripts/

# systemd units — patch __USER__ then install
sed -i "s|__USER__|\${USER_NAME}|g" systemd/clawforge-*.service
mkdir -p ~/.config/systemd/user/
cp systemd/clawforge-proxy.service    ~/.config/systemd/user/
cp systemd/clawforge-messenger.service ~/.config/systemd/user/

# Config + tokens
mkdir -p ~/.hermes/clawforge
cp config/clawforge.yaml             ~/.hermes/clawforge.yaml
cp config/clawforge-tokens.env       ~/.hermes/clawforge-tokens.env
chmod 600 ~/.hermes/clawforge-tokens.env
\`\`\`

### 2. Verify the token loads

\`\`\`bash
python3 -c "import os; from dotenv import load_dotenv; load_dotenv(os.path.expanduser('~/.hermes/clawforge-tokens.env')); print('token prefix:', os.environ.get('CLAWFORGE_CLIENT_TOKEN', '?')[:8] + '...')"
# Expected: "token prefix: clawfo..."
\`\`\`

### 3. Verify you can reach relay-7

\`\`\`bash
tailscale ping -c 1 ${RELAY_HOST}
# Expected: pong from ${RELAY_HOST}
\`\`\`

### 4. Start the daemons

\`\`\`bash
systemctl --user daemon-reload
systemctl --user enable --now clawforge-proxy.service
systemctl --user enable --now clawforge-messenger.service
systemctl --user status clawforge-proxy.service
systemctl --user status clawforge-messenger.service
# Expected: both "active (running)"
\`\`\`

### 5. Confirm you're on the bus

\`\`\`bash
# Wait ~10 seconds for the first heartbeat, then:
tail -20 ~/.hermes/clawforge/proxy.log
# Expected: "Published profile to claw.profile.update (N gods)"

# Confirm Konan's instance sees you (do this from Konan's box):
#   cat ~/.hermes/clawforge/known-instances.json | python3 -m json.tool
# Expected: a "tallon" key in the "instances" block
\`\`\`

### 6. End-to-end test (optional but recommended)

From your box:

\`\`\`bash
# Ask one of Konan's gods (e.g. Marvin) to reply
hermes ask konan:marvin@konan --message "hello from talon — bus round-trip test"
# Expected: a reply, returned over the bus via claw.response.<id>
\`\`\`

If that round-trips, the federation is live in both directions.

## Troubleshooting

**Proxy keeps restarting:** \`tail -50 ~/.hermes/clawforge/proxy.log\`. Common:
- relay.host wrong (not on the same tailnet)
- Token expired or corrupted (re-copy from bundle)
- Port 4222 blocked (firewall)

**\`tailscale ping\` fails:** You're not on the same tailnet as relay-7. Konan
shared the machine via the Tailscale admin — accept it from your Tailscale
admin console.

**\`hermes ask\` hangs:** The messenger daemon is what dispatches incoming
requests to your local hermes profiles. Check:
\`\`\`bash
systemctl --user status clawforge-messenger.service
journalctl --user -u clawforge-messenger.service -n 30
\`\`\`

## Security notes

- The token in this bundle is the **shared** Clawforge token — same one
  Konan uses. Rotating it (moving to per-instance tokens) is on Konan's
  roadmap; for now the federation works because both sides share the same
  token. Once the per-instance token migration is done, your token will
  become unique and rotatable independently.
- This bundle should be delivered over a secure channel (Tailscale file
  send, 1Password share, age-encrypted). Do not paste the token into
  Telegram or email.
MD

# ── Tarball ──────────────────────────────────────────────────────────────────
TARBALL_NAME="clawforge-bundle-tallon-${TS}.tar.gz"
TARBALL_PATH="${DIST_DIR}/${TARBALL_NAME}"

tar -C "${STAGE_DIR}" -czf "${TARBALL_PATH}" \
    scripts/ systemd/ config/ INSTALL.md

# Stage is cleaned by the EXIT trap.

# ── Report ───────────────────────────────────────────────────────────────────
echo
echo "============================================================"
echo "BUNDLE READY"
echo "============================================================"
echo "Tarball:  ${TARBALL_PATH}"
echo "Size:     $(du -h "${TARBALL_PATH}" | cut -f1)"
echo "SHA-256:  $(sha256sum "${TARBALL_PATH}" | cut -d' ' -f1)"
echo "Token:    (embedded, mode 0600 inside tarball)"
echo
echo "DELIVER OVER A SECURE CHANNEL:"
echo "  - Tailscale file send"
echo "  - 1Password share link"
echo "  - age-encrypted to his public key"
echo
echo "Do NOT: Telegram plaintext, email, public repo."
echo "============================================================"
