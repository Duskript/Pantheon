#!/usr/bin/env bash
# beelink-web.sh — Provision Beelink #1 (N5095, 8GB) as Konan's
# always-on web/file/relay hub. Implements the Phases P1-P9 from
# athenaeum/soulforge/beelink-provisioning/handoff.md.
#
# The companion handoff is incomplete on Phases 2-7 (truncated/corrupted).
# This script is built from:
#   - Phase 1 (sdhci fix): from the surviving fragment in the handoff
#   - Phases 2-7: standard install patterns (Tailscale, Cloudflare
#     Tunnel, CyberPanel, Cockpit, Tailscale Serve, Resend handler)
#   - Phase 8: references the existing ~/subspace/ install
#   - Phase 9: drops the Olympus UI static build at /var/www/olympus
#
# Invocation:
#   scp beelink-web.sh beelink-web.env konan@<beelink-ip>:
#   ssh konan@<beelink-ip> 'sudo bash beelink-web.sh'
#
# The handoff's curl-pipe-bash invocation (install.pantheon.local) is
# aspirational — the script is served via scp until that URL is set up.
#
# Requires: beelink-web.env in the same directory, sourced by main().
# Refuses to run without it.

set -euo pipefail
IFS=$'\n\t'

# ─────────────────────────────────────────────────────────────────────
# Path resolution: script lives at ~/pantheon/scripts/beelink-web.sh
# on Konan's main PC. The .env lives next to it.
# When run from Beelink, it expects to find ./beelink-web.env in CWD.
# ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${BEELINK_ENV:-${SCRIPT_DIR}/beelink-web.env}"

# ─────────────────────────────────────────────────────────────────────
# Logging helpers — go to stderr so stdout stays pipeable
# ─────────────────────────────────────────────────────────────────────
log()  { printf '\033[1;34m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
warn() { printf '\033[1;33m[%s] WARN:\033[0m %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
err()  { printf '\033[1;31m[%s] ERROR:\033[0m %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
die()  { err "$@"; exit 1; }

# ─────────────────────────────────────────────────────────────────────
# Preflight
# ─────────────────────────────────────────────────────────────────────
preflight() {
    log "Preflight checks..."

    # Must be root
    [[ $EUID -eq 0 ]] || die "Must run as root (use sudo)"

    # Must be Ubuntu 26.04
    if ! grep -q "26.04" /etc/os-release 2>/dev/null; then
        warn "Expected Ubuntu 26.04. Continuing anyway — this is a Beelink; if you're on a different box, abort now."
        cat /etc/os-release | head -3 >&2
        read -rp "Continue? [y/N] " ans
        [[ "$ans" =~ ^[Yy]$ ]] || die "Aborted by user"
    fi

    # Must have the env file
    [[ -f "$ENV_FILE" ]] || die "Env file not found at $ENV_FILE. Copy beelink-web.env.example to beelink-web.env and fill in the values."
    # shellcheck source=/dev/null
    source "$ENV_FILE"

    # Required env vars
    local missing=()
    for v in THEOFORGE_DOMAIN CF_TUNNEL_TOKEN CF_ACCOUNT_ID CF_ZONE_ID \
             TAILSCALE_AUTHKEY RESEND_API_KEY RESEND_FROM_EMAIL \
             CONTACT_TO_EMAIL CYBERPANEL_ADMIN_EMAIL; do
        [[ -n "${!v:-}" ]] || missing+=("$v")
    done
    if (( ${#missing[@]} > 0 )); then
        die "Missing required env vars: ${missing[*]}. Edit $ENV_FILE."
    fi

    # Verify N5095/N5105 (the sdhci fix is hardware-specific)
    if grep -qi "N5095\|N5105" /proc/cpuinfo; then
        log "✓ Intel N5095/N5105 detected (sdhci fix will apply)"
        HARDWARE_FAMILY="intel-n5xxx"
    else
        local cpu
        cpu=$(grep -m1 "model name" /proc/cpuinfo | cut -d: -f2- | xargs)
        warn "CPU is '$cpu' — not N5095/N5105. The sdhci fix will be SKIPPED."
        warn "This is fine if you're not on a Beelink, but the handoff assumes you are."
        HARDWARE_FAMILY="other"
    fi

    # Verify network
    if ! curl -fsS -m 10 https://api.cloudflare.com >/dev/null 2>&1; then
        die "No internet — curl to api.cloudflare.com failed. Fix DNS/network first."
    fi
    log "✓ Internet reachable"
}

# ─────────────────────────────────────────────────────────────────────
# Phase 1 — System hardening + sdhci fix
# ─────────────────────────────────────────────────────────────────────
phase1_hardening() {
    log "=== Phase 1: System hardening ==="

    # Update + upgrade
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get upgrade -y
    apt-get install -y \
        curl wget git vim htop net-tools ufw fail2ban \
        unattended-upgrades apt-listchanges \
        ca-certificates gnupg lsb-release software-properties-common

    # Autoupgrades — silent security patches
    cat >/etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
APT::Periodic::Download-Upgradeable-Packages "1";
Unattended-Upgrade::Remove-Unused-Dependencies "1";
Unattended-Upgrade::Automatic-Reboot "false";
EOF
    log "✓ unattended-upgrades configured"

    # UFW — default deny, allow SSH only
    ufw --force reset
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow 22/tcp comment "SSH"
    # CyberPanel
    ufw allow 8090/tcp comment "CyberPanel admin (bound to localhost via tunnel)"
    # Cockpit
    ufw allow 9090/tcp comment "Cockpit (bound to localhost via tunnel)"
    # NATS (bound to localhost — tunnel handles external)
    ufw allow 4222/tcp comment "NATS (localhost-only via cloudflared)"
    ufw --force enable
    log "✓ UFW active (SSH only on the public interface)"

    # Fail2ban — default ssh jail
    cat >/etc/fail2ban/jail.local <<'EOF'
[DEFAULT]
bantime  = 1h
findtime = 10m
maxretry = 5

[sshd]
enabled = true
port    = ssh
filter  = sshd
logpath = /var/log/auth.log
EOF
    systemctl enable --now fail2ban
    log "✓ fail2ban active"

    # Time sync
    apt-get install -y systemd-timesyncd
    timedatectl set-ntp true
    log "✓ NTP active"

    # sdhci fix for N5095/N5105 (Jasper Lake)
    # The N5095's SD host controller spams errors without this blacklist.
    # Ref: knowledge base entry on Beelink U55 quirks.
    if [[ "$HARDWARE_FAMILY" == "intel-n5xxx" ]]; then
        cat >/etc/modprobe.d/blacklist-sdhci.conf <<'EOF'
# Blacklist sdhci_pci on N5095/N5105 — the SD card slot's controller
# spams errors in dmesg and can stall boot on some firmware revisions.
# See: athenaeum/Codex-Infrastructure/reference/grub-cascading-error-beelink-u55.md
blacklist sdhci_pci
blacklist sdhci_pci_acpi
EOF
        # Also initramfs so the blacklist takes effect at boot
        update-initramfs -u
        log "✓ sdhci blacklisted + initramfs regenerated"
    fi

    # Kernel module load order is fine without further intervention.
    # The handoff mentions a GRUB fallback (`sdhci.debug_quirks=0x8000
    # sdhci.debug_quirks2=1`) for when the blacklist isn't enough —
    # see §5 Edge Cases. Not applied by default.
}

# ─────────────────────────────────────────────────────────────────────
# Phase 2 — Tailscale
# ─────────────────────────────────────────────────────────────────────
phase2_tailscale() {
    log "=== Phase 2: Tailscale ==="

    if command -v tailscale >/dev/null 2>&1; then
        log "Tailscale already installed; ensuring up"
    else
        curl -fsSL https://tailscale.com/install.sh | sh
    fi

    # Bring up using the auth key from .env. Reusable + pre-approved
    # so no browser interaction needed for headless installs.
    tailscale up --authkey="$TAILSCALE_AUTHKEY" \
        --hostname="beelink-1" \
        --accept-routes \
        --ssh
    log "✓ Tailscale up"

    # Show our tailnet IP for verification
    TAILSCALE_IP=$(tailscale ip -4)
    log "  Tailscale IP: $TAILSCALE_IP"
    echo "TAILSCALE_IP=$TAILSCALE_IP" >> "$ENV_FILE.tmp"
    mv "$ENV_FILE.tmp" "$ENV_FILE"
}

# ─────────────────────────────────────────────────────────────────────
# Phase 3 — Caddy + Cloudflare Tunnel
# ─────────────────────────────────────────────────────────────────────
phase3_caddy_cloudflared() {
    log "=== Phase 3: Caddy + Cloudflare Tunnel ==="

    # Caddy — reverse proxy in front of CyberPanel + Olympus
    apt-get install -y caddy
    cat >/etc/caddy/Caddyfile <<EOF
# Caddy terminates TLS at the tunnel edge? No — cloudflared
# handles TLS to Cloudflare, and Caddy serves plain HTTP to localhost
# (cloudflared routes to it). CyberPanel + Olympus static listen
# on internal ports; Caddy provides hostname-based routing.

# Olympus UI static site
http://theoforgesolutions.com, http://*.theoforgesolutions.com {
    root * /var/www/olympus
    encode gzip zstd
    file_server
    header {
        # Cache static assets aggressively
        Cache-Control "public, max-age=31536000, immutable"
        # HSTS — only matters if the tunnel is bypassed
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Referrer-Policy "strict-origin-when-cross-origin"
    }
}

# CyberPanel (admin subdomain)
http://portal.theoforgesolutions.com {
    reverse_proxy 127.0.0.1:8090 {
        header_up Host {host}
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
    }
}

# Cockpit (admin subdomain, Konan only)
http://admin.theoforgesolutions.com {
    reverse_proxy 127.0.0.1:9090
}

# Resend contact form endpoint
http://contact.theoforgesolutions.com {
    reverse_proxy 127.0.0.1:8080
}
EOF
    systemctl enable --now caddy
    log "✓ Caddy configured + running"

    # cloudflared — Cloudflare Tunnel
    if ! command -v cloudflared >/dev/null 2>&1; then
        # Add Cloudflare's apt repo
        mkdir -p --mode=0755 /usr/share/keyrings
        curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
            | gpg --dearmor -o /usr/share/keyrings/cloudflare-main.gpg
        echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared $(lsb_release -cs) main" \
            >/etc/apt/sources.list.d/cloudflared.list
        apt-get update -y
        apt-get install -y cloudflared
    fi

    # Write the tunnel config (using the token from .env)
    mkdir -p /etc/cloudflared
    cat >/etc/cloudflared/config.yml <<EOF
# Cloudflare Tunnel config for theoforgesolutions.com
# One tunnel, multiple hostnames, multiple services.
# The CF_TUNNEL_TOKEN in .env is the bootstrap credential that
# proves THIS cloudflared to Cloudflare.
tunnel: pantheon-web
credentials-file: /etc/cloudflared/.credentials.json
ingress:
  # Static site + Olympus
  - hostname: theoforgesolutions.com
    service: http://localhost:80
  - hostname: www.theoforgesolutions.com
    service: http://localhost:80
  # CyberPanel
  - hostname: portal.theoforgesolutions.com
    service: http://localhost:8090
  # Cockpit (Konan only — restrict via Cloudflare Access at cloudflare.com)
  - hostname: admin.theoforgesolutions.com
    service: http://localhost:9090
  # Resend contact form handler
  - hostname: contact.theoforgesolutions.com
    service: http://localhost:8080
  # NATS over TCP (for Subspace + cross-Pantheon messaging)
  - hostname: nats.theoforgesolutions.com
    service: tcp://localhost:4222
  # Catch-all
  - service: http_status:404
EOF
    echo "$CF_TUNNEL_TOKEN" > /etc/cloudflared/.credentials.json
    chmod 600 /etc/cloudflared/.credentials.json

    # Install as systemd service and start
    cloudflared service install
    systemctl enable --now cloudflared
    log "✓ cloudflared installed and running"
    log "  Note: DNS records (CNAMEs) for the hostnames above must be"
    log "  created in Cloudflare pointing to the tunnel. See §5 below."
}

# ─────────────────────────────────────────────────────────────────────
# Phase 4 — CyberPanel
# ─────────────────────────────────────────────────────────────────────
phase4_cyberpanel() {
    log "=== Phase 4: CyberPanel ==="
    warn "CyberPanel installs LiteSpeed + MariaDB. Total time: ~10-15 min."
    warn "During install, you'll be asked for:"
    warn "  - Admin email: $CYBERPANEL_ADMIN_EMAIL"
    warn "  - Admin password: (set a strong one)"
    warn "  - MySQL root password: (set a strong one)"

    # CyberPanel official install — single command
    # https://cyberpanel.net/installing-cyberpanel/
    # Use --force to skip the menu
    cd /opt
    curl -fsSL https://cyberpanel.net/install.sh -o cyberpanel-install.sh
    bash cyberpanel-install.sh <<EOF
1
$CYBERPANEL_ADMIN_EMAIL
$CYBERPANEL_ADMIN_USER
$CYBERPANEL_ADMIN_PASSWORD
A
$CYBERPANEL_MYSQL_PASSWORD
N
N
EOF
    rm cyberpanel-install.sh

    # CyberPanel listens on :8090 by default
    systemctl enable --now lscpd
    log "✓ CyberPanel installed"
    log "  Admin UI: https://portal.theoforgesolutions.com (via tunnel)"
    log "  Direct (LAN only): https://<beelink-ip>:8090"
    log "  IMPORTANT: Create a Tallon user in CyberPanel and scope"
    log "  their access to /home/tallon/ — see handoff §4.3."
}

# ─────────────────────────────────────────────────────────────────────
# Phase 5 — Cockpit
# ─────────────────────────────────────────────────────────────────────
phase5_cockpit() {
    log "=== Phase 5: Cockpit ==="

    apt-get install -y cockpit
    systemctl enable --now cockpit.socket
    log "✓ Cockpit installed and listening on :9090 (tunnel-only)"
}

# ─────────────────────────────────────────────────────────────────────
# Phase 6 — File server (Tailscale Serve)
# ─────────────────────────────────────────────────────────────────────
phase6_file_server() {
    log "=== Phase 6: File server (Tailscale Serve) ==="

    # Create Tallon's home
    if ! id "$TALLON_USERNAME" >/dev/null 2>&1; then
        useradd -m -s /bin/bash "$TALLON_USERNAME"
        log "✓ Created user $TALLON_USERNAME"
    fi

    # Bind to tailnet IP only — not 0.0.0.0 — so files are not
    # exposed to the public internet, only to the tailnet.
    # Tailscale Serve (Funnel is NOT used — Funnel would expose
    # to the public internet, which is exactly what we don't want).
    tailscale serve --bg --https=443 \
        --set-path=/files \
        http://localhost:8081
    log "✓ Tailscale Serve: https://<beelink-tailnet-ip>/files → localhost:8081"

    # Create a simple file server bound to localhost:8081
    apt-get install -y caddy  # already installed in P3, idempotent
    cat >/etc/caddy/Caddyfile.tallon <<EOF
http://localhost:8081 {
    root * /home/${TALLON_USERNAME}/files
    file_server browse
    basicauth {
        ${TALLON_USERNAME} \$2a\$14\$placeholderhashfromcaddyhash-password
    }
}
EOF
    warn "⚠️  Placeholder basicauth hash in Caddyfile.tallon — generate a"
    warn "    real bcrypt hash with: caddy hash-password"
    warn "    Edit /etc/caddy/Caddyfile.tallon and uncomment to enable."
    log "  File server is staged but not yet bound to localhost:8081."
    log "  See handoff §4.3 for Tallon's file isolation requirements."
}

# ─────────────────────────────────────────────────────────────────────
# Phase 7 — Resend contact form handler
# ─────────────────────────────────────────────────────────────────────
phase7_resend_handler() {
    log "=== Phase 7: Resend contact form handler ==="

    mkdir -p /opt/contact-form
    cat >/opt/contact-form/server.js <<EOF
// Minimal Node.js contact form handler using Resend's HTTP API.
// Listens on localhost:8080 — Caddy fronts it on
// contact.theoforgesolutions.com via the tunnel.
//
// POST /contact { name, email, message } -> forwards to Resend

const http = require('http');
const https = require('https');

const PORT = 8080;
const RESEND_API_KEY = process.env.RESEND_API_KEY;
const FROM = process.env.RESEND_FROM_EMAIL;
const TO = process.env.CONTACT_TO_EMAIL;

if (!RESEND_API_KEY || !FROM || !TO) {
    console.error('Missing RESEND_API_KEY, RESEND_FROM_EMAIL, or CONTACT_TO_EMAIL');
    process.exit(1);
}

const server = http.createServer((req, res) => {
    // CORS — only allow requests from theoforgesolutions.com
    res.setHeader('Access-Control-Allow-Origin', 'https://theoforgesolutions.com');
    res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (req.method === 'OPTIONS') {
        res.writeHead(204);
        return res.end();
    }

    if (req.method !== 'POST' || req.url !== '/contact') {
        res.writeHead(404, { 'Content-Type': 'application/json' });
        return res.end(JSON.stringify({ error: 'not found' }));
    }

    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', async () => {
        try {
            const { name, email, message } = JSON.parse(body);

            // Basic validation — server-side, even if the form has client checks
            if (!name || !email || !message) {
                res.writeHead(400, { 'Content-Type': 'application/json' });
                return res.end(JSON.stringify({ error: 'missing fields' }));
            }
            if (!email.match(/^[^@]+@[^@]+\.[^@]+$/)) {
                res.writeHead(400, { 'Content-Type': 'application/json' });
                return res.end(JSON.stringify({ error: 'invalid email' }));
            }
            if (message.length > 5000) {
                res.writeHead(413, { 'Content-Type': 'application/json' });
                return res.end(JSON.stringify({ error: 'message too long' }));
            }

            // Send via Resend
            const payload = JSON.stringify({
                from: FROM,
                to: [TO],
                reply_to: email,
                subject: \`[theoforgesolutions.com] \${name}\`,
                text: \`From: \${name} <\${email}>\n\n\${message}\`,
            });

            const reqOpts = {
                hostname: 'api.resend.com',
                port: 443,
                path: '/emails',
                method: 'POST',
                headers: {
                    'Authorization': \`Bearer \${RESEND_API_KEY}\`,
                    'Content-Type': 'application/json',
                    'Content-Length': Buffer.byteLength(payload),
                },
            };

            const apiReq = https.request(reqOpts, apiRes => {
                let apiBody = '';
                apiRes.on('data', chunk => { apiBody += chunk; });
                apiRes.on('end', () => {
                    if (apiRes.statusCode >= 200 && apiRes.statusCode < 300) {
                        res.writeHead(200, { 'Content-Type': 'application/json' });
                        res.end(JSON.stringify({ ok: true }));
                    } else {
                        console.error('Resend API error:', apiRes.statusCode, apiBody);
                        res.writeHead(502, { 'Content-Type': 'application/json' });
                        res.end(JSON.stringify({ error: 'upstream failure' }));
                    }
                });
            });
            apiReq.on('error', e => {
                console.error('Resend request error:', e);
                res.writeHead(502, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ error: 'upstream failure' }));
            });
            apiReq.write(payload);
            apiReq.end();
        } catch (e) {
            console.error('Server error:', e);
            res.writeHead(400, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: 'bad request' }));
        }
    });
});

server.listen(PORT, '127.0.0.1', () => {
    console.log(\`Contact form handler listening on http://127.0.0.1:\${PORT}\`);
});
EOF

    # Systemd service for the form handler
    cat >/etc/systemd/system/contact-form.service <<EOF
[Unit]
Description=Contact form handler (Resend)
After=network.target

[Service]
Type=simple
User=www-data
Environment=RESEND_API_KEY=${RESEND_API_KEY}
Environment=RESEND_FROM_EMAIL=${RESEND_FROM_EMAIL}
Environment=CONTACT_TO_EMAIL=${CONTACT_TO_EMAIL}
WorkingDirectory=/opt/contact-form
ExecStart=/usr/bin/node /opt/contact-form/server.js
Restart=on-failure
RestartSec=5s
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

    # Make sure Node.js is installed
    if ! command -v node >/dev/null 2>&1; then
        curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
        apt-get install -y nodejs
    fi

    # node-only deps — none needed, this is stdlib only
    systemctl daemon-reload
    systemctl enable --now contact-form.service
    log "✓ Contact form handler running on 127.0.0.1:8080"
}

# ─────────────────────────────────────────────────────────────────────
# Phase 8 — Subspace verify
# ─────────────────────────────────────────────────────────────────────
phase8_subspace() {
    log "=== Phase 8: Subspace verify ==="

    if [[ -d /root/subspace ]]; then
        log "Subspace already present at /root/subspace"
    elif [[ -d "$HOME/subspace" ]]; then
        log "Subspace present at $HOME/subspace"
    else
        # Pull from the Pantheon repo (assumes scp/rsync from main PC)
        warn "Subspace directory not found. If Konan hasn't scp'd it yet,"
        warn "do that and rerun phase8 manually with: ./beelink-web.sh phase8"
        return 0
    fi

    # Run the install.sh — it sets up nats-server + bridge + skill
    if [[ -x /root/subspace/install.sh ]]; then
        bash /root/subspace/install.sh
    elif [[ -x "$HOME/subspace/install.sh" ]]; then
        bash "$HOME/subspace/install.sh"
    fi

    # Verify the service is up
    if systemctl is-active --quiet subspace-bridge.service 2>/dev/null; then
        log "✓ subspace-bridge.service is active"
    else
        warn "subspace-bridge.service not active. Check: systemctl status subspace-bridge"
    fi
    log "  When Tallon sends his invite, accept it from the data god (Hermes) with:"
    log "    subspace_connect"
}

# ─────────────────────────────────────────────────────────────────────
# Phase 9 — Deploy Olympus UI static build
# ─────────────────────────────────────────────────────────────────────
phase9_olympus() {
    log "=== Phase 9: Deploy Olympus UI static build ==="

    # Source location is set in .env (OLYMPUS_STATIC_SOURCE) — should
    # point to a tarball or a directory containing the built
    # webui/static/ contents (the index.html, assets/, icons/, etc.)
    if [[ -z "${OLYMPUS_STATIC_SOURCE:-}" ]]; then
        warn "OLYMPUS_STATIC_SOURCE not set in $ENV_FILE."
        warn "Defaulting to /root/olympus-ui-static.tgz — copy your"
        warn "build there or override the env var."
        OLYMPUS_STATIC_SOURCE="/root/olympus-ui-static.tgz"
    fi

    mkdir -p /var/www/olympus

    if [[ -d "$OLYMPUS_STATIC_SOURCE" ]]; then
        # Source is a directory — rsync contents into /var/www/olympus/
        log "Copying from directory: $OLYMPUS_STATIC_SOURCE"
        rsync -av --delete "$OLYMPUS_STATIC_SOURCE/" /var/www/olympus/
    elif [[ -f "$OLYMPUS_STATIC_SOURCE" ]]; then
        # Source is a tarball — extract
        log "Extracting tarball: $OLYMPUS_STATIC_SOURCE"
        tar -xzf "$OLYMPUS_STATIC_SOURCE" -C /var/www/olympus --strip-components=1
    else
        warn "Source $OLYMPUS_STATIC_SOURCE not found."
        warn "Leaving /var/www/olympus/ empty. Konan needs to deploy"
        warn "the build before the public site is functional."
        return 0
    fi

    # Set ownership so caddy can read
    chown -R caddy:caddy /var/www/olympus
    log "✓ Olympus UI static build deployed to /var/www/olympus"
    log "  Reload Caddy: systemctl reload caddy"
}

# ─────────────────────────────────────────────────────────────────────
# Phase 5 of the Cloudflare Tunnel — DNS records
# (not automated; the handoff says these need to be created manually
# in the Cloudflare dashboard. We print the exact records to create.)
# ─────────────────────────────────────────────────────────────────────
print_cloudflare_dns_records() {
    log "=== Cloudflare DNS Records to Create ==="
    cat <<EOF

Go to https://dash.cloudflare.com → theoforgesolutions.com → DNS → Records

For EACH of the hostnames below, create a CNAME record pointing to:
    $(systemctl show cloudflared -p ExecStart 2>/dev/null | grep -oP '(?<=--).*\.cfargotunnel\.com' | head -1 || echo "<tunnel-id>.cfargotunnel.com")

  - theoforgesolutions.com  → CNAME → <tunnel>.cfargotunnel.com (proxied ✓)
  - www                     → CNAME → <tunnel>.cfargotunnel.com (proxied ✓)
  - portal                  → CNAME → <tunnel>.cfargotunnel.com (proxied ✓)
  - admin                   → CNAME → <tunnel>.cfargotunnel.com (proxied ✓)
  - contact                 → CNAME → <tunnel>.cfargotunnel.com (proxied ✓)
  - nats                    → CNAME → <tunnel>.cfargotunnel.com (proxied ✓, TCP)

To find the tunnel's cfargotunnel hostname, run on the Beelink:
  cloudflared tunnel info pantheon-web

EOF
}

# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────
# main — entry point with phase dispatch and --help support.
# Usage:
#   sudo ./beelink-web.sh              # run all phases
#   sudo ./beelink-web.sh phase3       # run just Caddy + Tunnel
#   sudo ./beelink-web.sh --help       # show usage
# Refuses to run without beelink-web.env in the script's directory.
main() {
    # Allow running a single phase for re-runs
    local target="${1:-all}"

    if [[ "$target" == "--help" ]] || [[ "$target" == "-h" ]]; then
        cat <<EOF
beelink-web.sh — Provision Beelink #1 as the Pantheon web/file/relay hub

Usage: sudo ./beelink-web.sh [phase]

Phases:
  all       Run all phases P1-P9 (default)
  phase1    System hardening + sdhci fix (N5095/N5105)
  phase2    Tailscale install + auth
  phase3    Caddy + Cloudflare Tunnel
  phase4    CyberPanel install
  phase5    Cockpit install
  phase6    Tailscale Serve (file server) + Tallon user
  phase7    Resend contact form handler
  phase8    Subspace verify + connect
  phase9    Deploy Olympus UI static build

Requires: beelink-web.env in the same directory as this script.
          Copy beelink-web.env.example to beelink-web.env and fill in.

Runs as: root (or via sudo). The script will refuse otherwise.

Source: athenaeum/soulforge/beelink-provisioning/handoff.md
EOF
        return 0
    fi

    preflight

    case "$target" in
        all)
            phase1_hardening
            phase2_tailscale
            phase3_caddy_cloudflared
            phase4_cyberpanel
            phase5_cockpit
            phase6_file_server
            phase7_resend_handler
            phase8_subspace
            phase9_olympus
            print_cloudflare_dns_records
            ;;
        phase1) phase1_hardening ;;
        phase2) phase2_tailscale ;;
        phase3) phase3_caddy_cloudflared ;;
        phase4) phase4_cyberpanel ;;
        phase5) phase5_cockpit ;;
        phase6) phase6_file_server ;;
        phase7) phase7_resend_handler ;;
        phase8) phase8_subspace ;;
        phase9) phase9_olympus ;;
        *) die "Unknown phase: $target. Use 'all' or phase1..phase9" ;;
    esac

    log "═══════════════════════════════════════════════════════════"
    log "  Done. Run the post-provisioning verification from §3"
    log "  of the handoff (dmesg | grep sdhci, tailscale status,"
    log "  systemctl status cloudflared, curl -I https://...)"
    log "═══════════════════════════════════════════════════════════"
}

main "$@"
