# Pantheon → Beelink U55 Migration Guide

## Overview
Migrates the entire Pantheon ecosystem (Hermes profiles, Athenaeum, MCP server, AionUi, both gods) from the current Ubuntu machine to a bare-metal **Beelink U55** running Ubuntu 24.04 LTS headless.

**Primary interface after migration:** AionUi web UI via browser.  
**Secondary:** SSH access for you to manage the machine remotely.

---

## Phase 1: Prepare on Current Machine (at Work)

You run the export script on the current machine. It creates a single encrypted `pantheon-migration.tar.gz` containing everything.

### Step 1.1 — Commit any uncommitted work
```bash
cd ~/pantheon
git add -A
git commit -m "pre-migration checkpoint: $(date -I)"
```

### Step 1.2 — Stop running services (prevents dirty state)
```bash
# Stop MCP server
systemctl --user stop pantheon-mcp || true
# Stop Hermes gateways
systemctl --user stop hermes-gateway || true
systemctl --user stop hermes-gateway-hephaestus || true
# Stop Apollo's tmux session if running
tmux kill-session -t apollo-gateway 2>/dev/null || true
```

### Step 1.3 — Run the export script
```bash
cd ~/pantheon/migration
chmod +x pantheon-export.sh
./pantheon-export.sh
```

This produces: `~/pantheon-migration.tar.gz` (~50 MB, encrypted).

### Step 1.4 — Transfer the tarball
**Option A (preferred):** Copy to USB, take home.
**Option B:** SCP directly from work machine to Beelink if it's already on your home network:
```bash
# From current machine:
scp ~/pantheon-migration.tar.gz username@pantheon.local:~/
```

### Step 1.5 — Clean up (after migration confirmed working)
```bash
# Wipe the encrypted tarball
rm ~/pantheon-migration.tar.gz
# If you created a temp private GitHub repo, delete it.
```

---

## Phase 2: Set Up the Beelink (at Home)

### Step 2.1 — Flash Ubuntu Server 24.04 LTS
1. Download Ubuntu Server 24.04 LTS ISO
2. Use Rufus/Ventoy to create bootable USB
3. Install on Beelink — headless, no desktop
4. During install:
   - **Set hostname:** `pantheon`
   - **Your username:** `konan` (or whatever you used on the old machine)
   - **Enable SSH server** ✓
   - **Install OpenSSH** ✓
5. After first boot, `ssh konan@pantheon.local` (or use its LAN IP)

### Step 2.2 — Verify SSH connectivity
```bash
ssh konan@pantheon.local
# Update packages
sudo apt update && sudo apt upgrade -y
```

---

## Phase 3: Run the Install Script (on Beelink)

### Step 3.1 — Get the tarball onto the Beelink
If using USB:
```bash
# Mount USB to /mnt/usb (adjust as needed)
sudo mount /dev/sdb1 /mnt/usb
cp /mnt/usb/pantheon-migration.tar.gz.gpg ~/
```

If using SCP from your laptop (after Beelink is on the network):
```bash
scp pantheon-migration.tar.gz.gpg konan@pantheon.local:~/
```

### Step 3.2 — Decrypt and extract
The export is GPG-encrypted. Decrypt it with the passphrase you used (or the default):

```bash
cd ~
echo "PantheonMigration2026" | gpg --batch --yes --passphrase-fd 0 \
    --decrypt pantheon-migration.tar.gz.gpg > pantheon-migration.tar.gz

tar xzf pantheon-migration.tar.gz
ls pantheon-migration/            # should show README.md, profiles/, athenaeum/, etc.
```

### Step 3.3 — Run the install script
```bash
cd pantheon-migration/
chmod +x pantheon-install.sh
./pantheon-install.sh
```

The script runs for 5–15 minutes depending on network speed. It:
- Installs `git`, `curl`, `python3`, `nodejs`, `npm`, `bun`, `build-essential`
- Installs Hermes Agent
- Installs Ollama (your default model endpoint)
- Clones your AionUi fork
- Installs and configures AionUi standalone server
- Restores Pantheon repo, Athenaeum, Hermes profiles, shared state
- Starts services (MCP server via systemd, AionUi)

### Step 3.3 — Verify everything came up
After the script finishes:

```bash
# Check all services
systemctl --user status pantheon-mcp
systemctl --user status hermes-gateway  # Apollo's
systemctl --user status hermes-gateway-hephaestus || true
systemctl --user status aionui

# Check logs
journalctl --user -u pantheon-mcp --no-pager -n 20
journalctl --user -u aionui --no-pager -n 20

# Check endpoints
curl -s http://localhost:8010/mcp -X POST -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}},"id":1}'

# Check AionUi
curl -s http://localhost:3000 | head -5
```

### Step 3.4 — Access from your laptop
From your home laptop:
```bash
# Web UI
open http://pantheon.local:3000
# Or using LAN IP: http://192.168.xxx.xxx:3000

# SSH (for management)
ssh konan@pantheon.local
```

In AionUi settings: add MCP server pointing to `http://127.0.0.1:8010/mcp`.

---

## Phase 4: Post-Migration (on Current Machine, Optional)

Once everything is confirmed working on the Beelink:

1. **Delete the encrypted tarball** from both machines
2. **Delete temporary GitHub private repo** (if created)
3. **Optionally scrub the old machine** or keep it as a cold backup

---

## Rollback
If something breaks mid-migration, the old machine is unchanged until you manually wipe it. You can:
1. Stop services: `systemctl --user stop pantheon-mcp aionui hermes-gateway*`
2. Delete `~/pantheon-migration.tar.gz`
3. Resume normal usage

---

## Troubleshooting

### AionUi shows "502 Bad Gateway"
The web renderer bundle wasn't built. SSH to Beelink and:
```bash
cd ~/aionui
npm run build:renderer:web
systemctl --user restart aionui
```

### Hermes gateway won't start
Check stale PID files:
```bash
rm -f ~/.hermes/profiles/hephaestus/gateway.pid ~/.hermes/profiles/hephaestus/gateway.lock
rm -f ~/.hermes/profiles/apollo/gateway.pid ~/.hermes/profiles/apollo/gateway.lock
systemctl --user restart hermes-gateway
```

### MCP server unreachable
```bash
cd ~/pantheon/pantheon-core
python3 mcp_server.py --port 8010
# If it says 'port in use', kill the old process first
lsof -ti :8010 | xargs kill -9
```

### AionUi can't find Hermes
AionUi auto-detects `hermes` on PATH. Make sure:
```bash
which hermes
# → ~/.local/bin/hermes
# If not, logout/login or source ~/.bashrc
```

---

## Files in This Migration Package

| File | Purpose |
|------|---------|
| `README.md` | This guide |
| `pantheon-export.sh` | Run on current machine — exports everything into tarball |
| `pantheon-install.sh` | Run on Beelink — installs everything from tarball |
| `pantheon-mcp.service` | systemd unit for MCP server |
| `aionui.service` | systemd unit for AionUi web server |
| `config-examples/` | Reference configs (secrets are in the encrypted tarball) |

## Questions?

SSH to the Beelink and check logs:
```bash
journalctl --user -u aionui -u pantheon-mcp -u hermes-gateway* --no-pager -n 50
```
