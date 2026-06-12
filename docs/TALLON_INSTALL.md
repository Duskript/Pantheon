# Tallon Install — Update + Memory Activation + Clawforge Connect

**Audience:** Tallon's default Hermes agent (Data, the primary god on the
enterprise side). Run these steps from a fresh shell on his Pantheon host.
**Time estimate:** 30-45 minutes total. Most of it is the `git pull` and
the Ichor migration.
**Last updated:** 2026-06-12 (post-GitHub push `ff4807e`).

## TL;DR

```bash
# 1. Update Pantheon to the post-push HEAD
cd ~/pantheon && git pull

# 2. Update the hermes-agent submodule to the Pantheon-pinned SHA
cd ~/pantheon/hermes-agent && git fetch && git checkout 26dcc0e556110d7cc607045801d716430a6c2dc3 && cd ..
pip install -e ~/pantheon/hermes-agent

# 3. Re-run the install script (idempotent — picks up new files)
bash ~/pantheon/scripts/install-pantheon.sh

# 4. Activate memory (3 layers, in order)
hermes config set memory.ichor.cadence.full_recall 3
hermes config set memory.ichor.cadence.fast_recall 1
hermes config set memory.ichor.cadence.extract_every 1
hermes config set memory.ichor.cadence.synthesis 10
hermes config set memory.ichor.nudge_interval 5
hermes config set memory.ichor.flush_min_turns 6

# 5. Connect to Clawforge (one-time provisioning + verify)
# ... see "Clawforge Connect" below
```

If any step fails, see the per-section "If something goes wrong" notes at
the bottom. Don't improvise — every step has a reason.

---

## Part 1: Update Pantheon to the latest GitHub HEAD

### What's being updated

The GitHub push on 2026-06-12 (commits `c1a3fad` → `4fdcf00` → `c0555f3`
→ `ff4807e`, 121 files, +28,071 / -2,954 lines) shipped:

- **Entity-Relationship Graph** (`lib/ichor/entities/`): schema
  migration, L0/L1/L2 extraction pipeline, graph traversal, dream
  cycle. Adds `relationship_types` table (5 canonical types seeded
  automatically) and `warm_entities` + `cold_events` for the
  5-tier memory architecture.
- **Clawforge Pass 3** (`lib/clawforge/` + `scripts/clawforge-*`):
  memory API, 3 exporters (pattern/learning/adjustment),
  outcome backfill, effectiveness validator, federation stats,
  6 god coordination tools, the registry HTTP server.
- **Package refactor**: `lib/ichor/` package now contains
  `schema_v2.py`, `llm.py`, and the entities/ subpackage. The
  old flat `lib/ichor_schema_v2.py` and `lib/ichor_tier_a_plus.py`
  are gone. Imports of `from lib.ichor_tier_a_plus import _call_llm`
  must be updated to `from lib.ichor.llm import _call_llm`.
- **Tier A confidence seeding**: `TYPE_IMPORTANCE` dict
  (blocker:70, commitment:60, decision:55, correction:50, …,
  reference:35) seeds importance at insert time.
- **Deletions**: `lib/ichor_graph_query.py` (superseded by the
  package). 12 `webui/static/assets/*.js` files (Vite build outputs
  that should never have been tracked).

### Steps

```bash
# 1.1. Verify current state — what commit are you on?
cd ~/pantheon
git log --oneline -1

# Expected: if you have the old Pantheon, you'll be on 8801c4f or earlier.
# After the update, you'll be on ff4807e.

# 1.2. Pull the new commits
cd ~/pantheon
git pull origin main

# If this fails with "local changes would be overwritten", STOP and read
# "If something goes wrong" section. Don't force-pull.

# 1.3. Update the hermes-agent submodule to the pinned SHA
# (the submodule pointer is at 26dcc0e5 in the new commit)
cd ~/pantheon/hermes-agent
git fetch
git checkout 26dcc0e556110d7cc607045801d716430a6c2dc3
cd ~/pantheon
git status  # should show clean (no modified submodule)

# 1.4. Re-install hermes-agent in editable mode
pip install -e ~/pantheon/hermes-agent

# 1.5. Verify
hermes --version  # should report v2026.5.29-4346-g26dcc0e55 or newer
cd ~/pantheon && git log --oneline -1  # ff4807e
```

### Why this is a "pull + re-install" instead of a clean reinstall

`install-pantheon.sh` is idempotent — it checks what's installed
before re-installing. So `git pull` + `pip install -e ...` covers
the code; running the install script at the end catches any new
systemd units, cron jobs, or env files that the new code needs.

```bash
# 1.6. Run the install script (idempotent)
bash ~/pantheon/scripts/install-pantheon.sh

# It will:
# - Skip Hermes Agent (already installed)
# - Clone the god packages to ~/.hermes/profiles/ (if new ones exist)
# - Deploy new plugins via symlink
# - Re-link the MCP server
# - Install any new systemd units (clawforge-* services)
# - Start the gateway
```

### If something goes wrong

**`git pull` fails with "local changes would be overwritten":**
You have uncommitted changes in some files. Stash them first:
```bash
cd ~/pantheon
git status -s  # see what's modified
git stash
git pull origin main
git stash pop  # re-apply your changes; resolve any conflicts manually
```

**`pip install -e ...` fails with "no module named X":**
Your venv is missing deps. Re-run the install script from
`install-pantheon.sh` which sets up the venv:
```bash
bash ~/pantheon/scripts/install-pantheon.sh
```

**`hermes --version` reports a much older version:**
The venv isn't pointing at the right Python. Find the right interpreter:
```bash
find ~ -name "hermes" -path "*/bin/*" 2>/dev/null | head -5
# Use the one inside the hermes-agent venv
~/pantheon/hermes-agent/.venv/bin/hermes --version
```

---

## Part 2: Activate Memory — All 3 Layers + the New Cadence

Memory in Hermes has 4 layers. The marvin profile (the one Marvin uses)
already has all 4 active. **The default profile** (which is what
Tallon's default agent uses) has them too, but with slightly different
cadence numbers. This section makes sure they're set correctly.

### What's being activated

| Layer | What it does | Already on? |
|---|---|---|
| **Hot cache** (MEMORY.md) | Per-session 2,200-char scratchpad for the agent's working context. Auto-injected every turn. | ✅ Yes, by default |
| **User profile** (USER.md) | Per-user 1,375-char scratchpad for user preferences, pet peeves, correction history. | ✅ Yes, by default |
| **Ichor events** (FTS5 + Graph + Events backends) | Cross-session long-form memory: every event/decision/insight is FTS5-indexed for retrieval. | ✅ Yes, by default |
| **Athenaeum long-form** | Structured knowledge bases (codexes) at `~/athenaeum/` for durable facts that don't fit in hot cache. | ✅ Yes, by default |
| **NEW: Cadence + nudge + flush** | Self-maintaining memory: every 5 turns a "what to remember?" prompt, every 15 turns a "is this also a profile/digest/entity update?" prompt, every 6 turns a pressure-relief flush. | ❌ **Not on by default** — needs the 6 config sets below |

### Steps

```bash
# 2.1. Verify the 3 base layers are on
hermes config get memory.memory_enabled        # true
hermes config get memory.user_profile_enabled  # true
hermes config get memory.provider              # ichor

# If any return "false" or "default", run:
hermes config set memory.memory_enabled true
hermes config set memory.user_profile_enabled true
hermes config set memory.provider ichor
hermes config set memory.ichor.cadence.full_recall 3
hermes config set memory.ichor.cadence.fast_recall 1

# 2.2. Add the NEW cadence + nudge + flush (this is the 0.16 feature set)
hermes config set memory.ichor.cadence.extract_every 1
hermes config set memory.ichor.cadence.synthesis 10
hermes config set memory.ichor.nudge_interval 5
hermes config set memory.ichor.flush_min_turns 6

# 2.3. Verify everything is set
hermes config get memory.ichor
# Expected output:
#   cadence:
#     extract_every: 1
#     fast_recall: 1
#     full_recall: 3
#     synthesis: 10
#   flush_min_turns: 6
#   nudge_interval: 5

# 2.4. Sanity check: does Ichor load?
python3 -c "from lib.ichor.schema_v2 import migrate, DB_PATH; print('Ichor DB at:', DB_PATH)"
# Expected: "Ichor DB at: /home/<you>/.hermes/ichor.db"
```

### What the cadence numbers mean (so you can tune them later)

- **`full_recall: 3`** — every 3 turns, do a full FTS5+Graph+Events
  query. Cost: ~200ms per turn. Lower = more frequent = better recall,
  more tokens spent on memory retrieval.
- **`fast_recall: 1`** — every turn, do a fast FTS5-only query.
  Cost: ~30ms per turn.
- **`extract_every: 1`** — every turn, run Tier A regex extraction
  on the conversation. Cost: ~50ms per turn.
- **`synthesis: 10`** — every 10 turns, run Tier A+ LLM extraction
  (if enabled). Cost: ~1-2s per turn, ~500 tokens.
- **`nudge_interval: 5`** — every 5 turns, inject a "what should you
  remember from this turn?" prompt into the agent's context.
- **`flush_min_turns: 6`** — every 6 turns, check MEMORY.md size
  and trigger a routing flush if it's near the 2,200-char cap.

If you find the agent is "forgetting" between turns, lower `full_recall`
to 2. If it's spending too many tokens on memory, raise it to 5.

### If something goes wrong

**`hermes config get` says "memory" doesn't exist:**
Run any `hermes config set` first to create the block, then `get` will
work. Or edit `~/.hermes/config.yaml` directly to add the block.

**The Ichor DB doesn't exist yet (`migrate()` will create it):**
```bash
python3 -c "from lib.ichor.schema_v2 import migrate, DB_PATH; migrate()"
# Creates ~/.hermes/ichor.db with the 5-tier schema
```

**`from lib.ichor.schema_v2 import migrate` fails with ModuleNotFoundError:**
The hermes-agent venv doesn't have Pantheon's lib/ on sys.path. Either:
```bash
# Option A: add to PYTHONPATH for the current shell
export PYTHONPATH="$HOME/pantheon:$PYTHONPATH"

# Option B: install Pantheon as editable (preferred for Tallon's enterprise side)
pip install -e ~/pantheon
```

---

## Part 3: Connect to Clawforge

Clawforge is the cross-instance learning system. You connect by:
1. Running the `clawforge-proxy` daemon (the SkillClaw-equivalent)
2. Provisioning a per-instance client token
3. Verifying the registry sees you
4. Opting in to the public federation dashboard

### 3.1. Install the proxy + god tools

The push shipped `scripts/clawforge-proxy.py`, `scripts/clawforge-god-publisher.py`,
`scripts/clawforge-god-puller.py`, `scripts/clawforge-god-register.py`,
`scripts/clawforge-god-updater.py`, `scripts/clawforge-skill-updater.py`,
and `scripts/clawforge-messenger.py`. They're on disk after Part 1's
`git pull`. The install script (Part 1.6) should have symlinked them
into `~/.local/bin/` or similar.

```bash
# 3.1.1. Verify the binaries are on PATH
which clawforge-proxy.py clawforge-god-publisher.py clawforge-god-puller.py
# If empty, add ~/.local/bin to PATH or symlink manually:
mkdir -p ~/.local/bin
for s in ~/pantheon/scripts/clawforge-*.py; do
  ln -sf "$s" ~/.local/bin/"$(basename "$s")"
done

# 3.1.2. Create the proxy config
mkdir -p ~/.hermes/clawforge

cat > ~/.hermes/clawforge.yaml << 'YAML'
# Clawforge Proxy v0.1.0 — Tallon instance config
# Read by clawforge-proxy daemon AND the clawforge CLI.

relay:
  host: "100.100.46.52"   # Tailscale IP for relay-7 (replace if your tailnet differs)
  port: 4222
  # Token loaded from ~/.hermes/clawforge-tokens.env (CLAWFORGE_CLIENT_TOKEN)

instance:
  id: "tallon"  # ← CHANGE THIS to a unique instance ID
  display_name: "Tallon's Pantheon"
  god_registry: "/home/<you>/pantheon/gods/gods.yaml"  # ← CHANGE <you>

heartbeat_interval_seconds: 300
peers_cache: "/home/<you>/.hermes/clawforge/known-instances.json"
log_file: "/home/<you>/.hermes/clawforge/proxy.log"
YAML

# 3.1.3. Replace <you> with your actual username
sed -i "s|<you>|$(whoami)|g" ~/.hermes/clawforge.yaml
```

### 3.2. Get a Clawforge client token

The token authorizes your instance to write to the public registry
and read from the federation. **You need to ask Konan for one** —
they're issued manually on relay-7 (not auto-provisioned). Konan
needs to:

1. SSH to relay-7 (`ssh konan@beelink-relay`)
2. Run: `sudo /usr/local/bin/clawforge-issue-client-token.py tallon`
3. Send you the resulting `~/.hermes/clawforge-tokens.env` contents
   over a secure channel (NOT Telegram plaintext, NOT email — use
   the tailscale file send, or paste into a 1Password share link)

You then:

```bash
# 3.2.1. Save the token file
nano ~/.hermes/clawforge-tokens.env
# Paste the contents Konan sent you. Format:
#   CLAWFORGE_CLIENT_TOKEN=tkn_xxxxxxxxxxxxxxxxxxxxxxxx
#   CLAWFORGE_INSTANCE_ID=tallon

chmod 600 ~/.hermes/clawforge-tokens.env

# 3.2.2. Verify the token is loadable
python3 -c "import os; from dotenv import load_dotenv; load_dotenv(os.path.expanduser('~/.hermes/clawforge-tokens.env')); print('token prefix:', os.environ.get('CLAWFORGE_CLIENT_TOKEN', '?')[:8] + '...')"
# Expected: "token prefix: tkn_xxxx..."
```

### 3.3. Start the proxy daemon

```bash
# 3.3.1. Install the systemd unit (it's in scripts/clawforge-proxy.py --install
# OR you can copy the .service file from the repo)
cp ~/pantheon/scripts/clawforge-proxy.service ~/.config/systemd/user/ 2>/dev/null
# (if the .service file doesn't exist in scripts/, skip this and use the manual launch)

# Manual launch (no systemd):
nohup python3 ~/pantheon/scripts/clawforge-proxy.py > ~/.hermes/clawforge/proxy.log 2>&1 &
echo $! > ~/.hermes/clawforge/proxy.pid

# Or with systemd (preferred):
systemctl --user daemon-reload
systemctl --user enable --now clawforge-proxy.service
systemctl --user status clawforge-proxy.service
# Expected: active (running)
```

### 3.4. Verify registration

```bash
# 3.4.1. Check that the proxy is connected to NATS
grep -E "connected|registered|instance_id" ~/.hermes/clawforge/proxy.log | tail -10
# Expected: "registered instance 'tallon' with NATS subject clawforge.profile.tallon"

# 3.4.2. Check the public registry sees you
curl -s https://federation.theoforgesolutions.com/INDEX.json | python3 -m json.tool | grep -A 3 "tallon"
# Expected: a block like:
#   "tallon": {
#     "display_name": "Tallon's Pantheon",
#     "first_seen": "2026-06-12T...",
#     "patterns_contributed": 0,
#     "submissions": 0
#   }

# Note: the federation dashboard updates every 5 min
# (the federation-stats.py cron on relay-7). Wait 5-10 min if you don't
# see yourself immediately.
```

### 3.5. Opt in to the public federation

The federation INDEX.json exposes aggregate stats (not raw data) at
`https://federation.theoforgesolutions.com/INDEX.json`. Privacy
contract: 18 fields are stripped (see `_privacy` block in the
INDEX.json). To opt in:

```bash
# 3.5.1. Edit your proxy config
echo "federation_opt_in: true" >> ~/.hermes/clawforge.yaml

# 3.5.2. Restart the proxy
systemctl --user restart clawforge-proxy.service
# OR kill the manual process and restart it
```

If you DON'T want to be in the public federation, skip 3.5.1. The
internal NATS bus still works (you can publish patterns and pull
patterns from other instances), but you won't appear in
`federation.theoforgesolutions.com/INDEX.json`.

### 3.6. Publish your first god (optional but recommended)

This is the "data into the bus" side. Once your proxy is running,
you can publish a god from your instance to the registry so other
instances can pull it.

```bash
# 3.6.1. Pick a god to publish (Data is your primary)
clawforge-god-publisher.py ~/.hermes/profiles/data/ --instance tallon --dry-run
# Shows what would be uploaded. Read the output, then:
clawforge-god-publisher.py ~/.hermes/profiles/data/ --instance tallon
# Uploads the tar.zst + manifest, publishes a NATS notification.

# 3.6.2. Verify the publish
clawforge who  # should show your instance + the data god
```

### If something goes wrong

**`clawforge-god-publisher.py` fails with "no token found":**
The env file isn't loaded. Either:
```bash
# Source it manually before running:
set -a; source ~/.hermes/clawforge-tokens.env; set +a
clawforge-god-publisher.py ~/.hermes/profiles/data/ --instance tallon
```

**`curl https://federation.theoforgesolutions.com/INDEX.json` times out:**
You're not on the Tailscale tailnet. Options:
- Join the konan tailnet (ask Konan for an invite link)
- Use a NATS-over-public-TCP route (Konan would need to add the
  cloudflared TCP tunnel for the federation subdomain; not done yet)

**Proxy keeps restarting in a loop:**
Check the log: `tail -50 ~/.hermes/clawforge/proxy.log`. Common causes:
- Wrong relay.host (you're not on the same tailnet)
- Token expired or invalid
- Port 4222 blocked by firewall

---

## Part 4: Final Verification

After Parts 1-3, run this checklist:

```bash
# 4.1. Pantheon is current
cd ~/pantheon && git log --oneline -1
# Expected: ff4807e chore(infra): update install scripts...

# 4.2. hermes-agent is at the pinned SHA
cd ~/pantheon && git submodule status
# Expected: "26dcc0e556110d7cc607045801d716430a6c2dc3 hermes-agent (v2026.5.29-4346-g26dcc0e55)"

# 4.3. Memory is activated
hermes config get memory.ichor
# Expected: full block with cadence + nudge_interval + flush_min_turns

# 4.4. Tests pass
cd ~/pantheon && python3 -m pytest tests/ --ignore=tests/test_ichor_gates.py 2>&1 | tail -3
# Expected: "639 passed" or close to it (may be lower if you don't have
# all the test fixtures; the 542 baseline is OK)

# 4.5. Clawforge proxy is running
systemctl --user status clawforge-proxy.service
# Expected: active (running)

# 4.6. Federation sees you
curl -s https://federation.theoforgesolutions.com/INDEX.json | grep -c "tallon"
# Expected: 1 or more (count of "tallon" occurrences in the index)
```

If any of these fail, the most likely cause is a missing dep or
wrong path. Re-run `install-pantheon.sh` — it catches most cases.

## What this does NOT do (out of scope)

- **A2.6 docs** (the Phase 6 enterprise docs). Those are blocked on
  Tallon's GitHub delta. Once Tallon has shipped his repos, ask
  Konan to write the docs.
- **E2.1-E2.4 deployment to relay-7** (Konan's side). Already done.
  Tallon doesn't need to touch relay-7.
- **The `lib/ichor_score.py` unified-score refactor** (5 of 7 formulas
  still need migrating). Not blocking anything; defer to a future
  pass.
- **6 password-reset utilities** at `scripts/reset_*.py` + `update_n8n_pass.py`.
  Held because they have hardcoded default passwords. If you need
  them, ask Konan to scrub + add tests.

## Next steps (for Tallon's first session after install)

1. **Verify federation dashboard** at
   `https://federation.theoforgesolutions.com/INDEX.json` — you
   should see `tallon` in the `instances` block within 5-10 min.
2. **Publish your first god** (Data) via `clawforge-god-publisher.py`.
3. **Pull a god from another instance** as a smoke test:
   `clawforge-god-puller.py konan:hermes@0.16.0` (or whatever the
   current version tag is).
4. **Register the pulled god** in your local `gods/gods.yaml`:
   `clawforge-god-register.py hermes`.
5. **Verify the god shows up in `clawforge who`**.

## Support

- **Tallon-specific questions:** DM Konan on the
  konan-Pantheon Telegram channel
- **Hermes Agent questions:** github.com/NousResearch/hermes-agent/issues
- **Pantheon / Clawforge questions:** github.com/Duskript/Pantheon/issues
  (or the Pantheon #support channel if it exists by then)
- **Clawforge federation dashboard:**
  https://federation.theoforgesolutions.com/INDEX.json

---

**Document version:** 2026-06-12 (post-push `ff4807e`)
**Maintainer:** Konan (Marvin's owner)
**Last verified by:** Konan's Marvin session, 2026-06-12
