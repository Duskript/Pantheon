# Relay-7 Audit & Tallon Access Plan

> Generated: 2026-06-23
> Host: relay-7 (100.100.46.52) — Ubuntu 26.04 LTS (Resolute Raccoon)
> Kernel: 7.0.0-22-generic
> Uptime: 12 days
> Role: Public-facing reverse proxy + static file server for theoforgesolutions.com

---

## 1. System Overview

| Metric | Value |
|---|---|
| CPU | x86_64 (multi-core) |
| RAM | 7.2 GB total, 1.2 GB used, 6.0 GB available |
| Disk | 98 GB (17 GB used, 77 GB free — 18%) |
| Swap | 4 GB (2 MB used) |
| Load | 0.01 — essentially idle |
| Tailscale | Connected via `beelink-relay` (100.100.46.52) |
| SSH | Tailscale-only (no public SSH). Key auth for user `konan` |
| Users | `root` (UID 0), `konan` (UID 1000) — only two human accounts |

## 2. Active Services

### Core Web Infrastructure

| Service | Status | Port | Description |
|---|---|---|---|
| **Caddy** | ✅ Active | :80 | Reverse proxy + static file server for `theoforgesolutions.com` |
| **Cloudflare Tunnel** | ✅ Active | — | Tunnels `theoforgesolutions.com` → relay-7 :80 (no direct internet exposure) |
| **NATS (JetStream)** | ✅ Active | :4222, :7422 | Message bus for Pantheon/Clawforge inter-service comms. TX/RX auth + leafnode peer |

### TheoForge Application Layer

| Service | Status | Port | Description |
|---|---|---|---|
| **TheoForge v9 (main)** | ✅ Active | :4321 | `/srv/theoforge/server.mjs` — Node.js landing page app |
| **TheoForge v9 (legacy)** | ✅ Active | :4322 | `node server.mjs` — archived `account-landing` route |
| **Form Handler** | ✅ Active | :8081 | Python HTTP server. Collects contact form submissions, forwards to Pantheon bridge |
| **Python HTTP server (demos)** | ✅ Active | :8767 | Serves `/var/www/theoforge/demos-site/` |
| **Python HTTP server** | ✅ Active | :8768 | Unidentified static file serving |

### Clawforge System (Pantheon God Package Manager)

| Service | Status | Port | Description |
|---|---|---|---|
| **Clawforge Registry** | ✅ Active | :20241 | HTTP server for god package registry |
| **Clawforge God Updater** | ✅ Active | — | Updates installed god packages |
| **Clawforge Skill Updater** | ✅ Active | — | Updates skills on relay-7 |
| **Clawforge Profile Updater** | ✅ Active | — | Updates profile registry |
| **Clawforge Pattern Requester** | ✅ Active | — | Requests patterns from other nodes |
| **Clawforge Pattern Aggregator Updater** | ✅ Active | — | Aggregates patterns |

### Other

| Service | Status | Port | Description |
|---|---|---|---|
| **Nextcloud (Snap)** | ✅ Active | — | Nextcloud 33.0.5 via snap, includes MySQL + PHP-FPM |
| **systemd-journald** | ✅ Active | — | Logging |
| **sshd** | ✅ Active | :22 | Tailscale-only SSH |
| **tailscaled** | ✅ Active | — | Tailscale daemon |
| **chrony** | ✅ Active | — | NTP client |

## 3. All Listening Ports

| Port | Service | Bind | Notes |
|---|---|---|---|
| :22 | SSH | All interfaces | Tailscale-only |
| :80 | Caddy | All interfaces | HTTP only (no auto HTTPS — Cloudflare handles TLS) |
| :4222 | NATS | All interfaces | Client connections |
| :4321 | Node (v9 main) | All interfaces | `server.mjs` |
| :4322 | Node (v9 legacy) | All interfaces | `node server.mjs` |
| :7422 | NATS leafnode | All interfaces | Leaf node peering |
| :8081 | Form Handler | 127.0.0.1 | Local only |
| :8767 | Python HTTP (demos) | All interfaces | Serves `/var/www/theoforge/demos-site/` |
| :8768 | Python HTTP | All interfaces | Unknown static serving |
| :8900 | Unknown | All interfaces | 🔍 Unidentified |
| :9090 | Unknown | All interfaces | 🔍 Unidentified |
| :11000 | Unknown | All interfaces | 🔍 Unidentified |
| :2019 | Caddy admin | 127.0.0.1 | Local admin API |
| :20241 | Clawforge Registry | 127.0.0.1 | Local only |

## 4. Filesystem Layout

```
/etc/caddy/Caddyfile                    # THE live routing config
/etc/nats/nats-server.conf              # NATS config (JetStream enabled, auth tokens)
/etc/cloudflared/                       # Cloudflare tunnel credentials
/etc/clawforge/                         # Clawforge config (profile-updater, tokens, validator)
/etc/systemd/system/                    # Custom service units:
  ├── nats.service                      #   NATS server
  ├── cloudflared-tunnel.service        #   Cloudflare tunnel
  ├── form-handler.service              #   Contact form handler
  └── clawforge-*.service               #   Various Clawforge services

/srv/theoforge/
  ├── server.mjs                        # Node v9 main app
  ├── public/index.html                 # Static root
  ├── lib/                              # Node module dependencies
  └── v9-4322.log                       # Legacy v9 log

/var/www/theoforge/
  ├── index.html                        # Root static page
  ├── demos-site/                       # Served at /demos/*
  ├── ledger-product-page/              # (when deployed)
  ├── pantheon-platform-page/           # (when deployed)
  ├── roadmap.html                      # Public roadmap
  ├── assets/                           # Shared assets
  ├── modal.css / modal.js              # Lead capture modal
  └── modal.js.bak-2026-06-20-21h10    # Backup before update

/home/konan/
  ├── nats-data/                        # NATS JetStream storage
  ├── .ssh/                             # SSH keys
  │   └── authorized_keys               # Currently empty — SSH via Tailscale SSH
  ├── .hermes/                          # Hermes profile (partial)
  └── clawforge-skill-updater.py        # Skill updater script

/etc/snap/nextcloud/53545/              # Nextcloud snap data
/var/snap/nextcloud/53545/mysql/        # Nextcloud MySQL data
```

## 5. Caddy Routing Summary

```
theoforgesolutions.com:80
  /webhook/*            → reverse_proxy 100.115.50.41:8088    (Pantheon Conductor)
  /demos/*              → file_server /var/www/theoforge/demos-site
  /account-landing/*    → reverse_proxy 127.0.0.1:4322        (legacy v9)
  /*                    → file_server /var/www/theoforge/

webhooks.theoforgesolutions.com:80
  /twilio-sms/*         → reverse_proxy 100.115.50.41:8090    (Twilio bridge)
  /*                    → reverse_proxy 100.115.50.41:8088    (Conductor)

sms.theoforgesolutions.com:80
  /*                    → reverse_proxy 100.115.50.41:8090    (Twilio bridge)
```

## 6. 🔍 Unidentified Services (Ports 8900, 9090, 11000)

Three listening ports have no identified process. These should be investigated:
- **:8900** — open on all interfaces, bound to port 8900
- **:9090** — open on all interfaces
- **:11000** — open on all interfaces

**Recommendation:** Identify these or add firewall rules to restrict them.

---

## 7. Tallon Access Plan — SSH to Relay-7

### Option A: Tailscale SSH (Recommended — Zero Config)

Tallon needs to be on the same Tailnet as relay-7. If Tallon's god process runs on a host that's already connected to the `Duskript@` Tailnet, SSH is automatic:

```bash
ssh konan@100.100.46.52
# or by hostname if DNS configured
ssh konan@relay-7
```

**Prerequisite:** Tallon's host must be joined to the `Duskript@` Tailnet (same network as relay-7, laptop, and beelink). Tailscale SSH handles auth automatically — no keys to manage.

### Option B: SSH Key Pair (If No Tailscale)

If Tallon runs on a host NOT on the tailnet:

**Step 1 — Generate a key pair** (on Tallon's machine):
```bash
ssh-keygen -t ed25519 -f ~/.ssh/relay-7 -C "tallon@pantheon"
```

**Step 2 — Add the public key to relay-7** (Konan runs this):
```bash
# Append Tallon's public key to authorized_keys
ssh konan@100.100.46.52 'echo "<paste_tallon_public_key_here>" >> ~/.ssh/authorized_keys'
```

**Step 3 — SSH in** (from Tallon's machine):
```bash
ssh -i ~/.ssh/relay-7 konan@100.100.46.52
```

**Step 4 — Add SSH config entry** (on Tallon's machine, `~/.ssh/config`):
```
Host relay-7
  HostName 100.100.46.52
  User konan
  IdentityFile ~/.ssh/relay-7
```

### Access Limitations

- **`konan` user only** — no separate accounts. Tallon would operate as `konan`, same as Hermes.
- **No `sudo` access** — system-level changes (service installs, package management) require coordination with Konan.
- **Tailscale-only SSH** — relay-7 has NO public SSH port. If Tallon isn't on Tailscale, Konan must add their SSH key.

### Recommended Approach

**Best:** Get Tallon's host on the Duskript@ Tailnet → Tailscale SSH just works (zero key management, automatic expiry, audit logs).

**Good:** Generate an SSH key pair, add the public key to `~/.ssh/authorized_keys` on relay-7, distribute the private key to Tallon securely.

---

## 8. Key Credentials (DO NOT COMMIT)

| Secret | Location |
|---|---|
| NATS client token | `/etc/nats/nats-server.conf` (auth token) |
| NATS leafnode password | `/etc/nats/nats-server.conf` (leafnodes auth) |
| Cloudflare tunnel token | `/etc/cloudflared/886dab98-a899-4dbb-9b74-4c361058a384.json` |
| Clawforge tokens | `/etc/clawforge/tokens.env` |

All credentials are already loaded on relay-7. Tallon would inherit `konan`'s access — no additional credential setup needed.
