# Tallon Handoff: Pantheon Webhook Bridge + Confidence Decay System

> Generated: 2026-06-12 22:30 UTC
> From: Thoth (Pantheon — Olympus side)
> To: Tallon (Enterprise side)

---

## Contents

1. [Overview — The Two Sides](#1-overview--the-two-sides)
2. [Webhook Bridge — What It Does](#2-webhook-bridge--what-it-does)
3. [Confidence Decay System — What Was Built](#3-confidence-decay-system--what-was-built)
4. [Ichor Memory Architecture (The 3+1 Jobs)](#4-ichor-memory-architecture-the-31-jobs)
5. [Your Setup Checklist](#5-your-setup-checklist)
6. [API Reference](#6-api-reference)
7. [Troubleshooting](#7-troubleshooting)

---

## 1. Overview — The Two Sides

| Side | Who Runs It | Port | Service Name |
|------|------------|------|-------------|
| **Olympus** | Konan (us) | `8013` | `pantheon-webhook-olympus` |
| **Enterprise** | Tallon (you) | `8014` | `pantheon-webhook-enterprise` |

Both run the same Python script, just with `--side` flag to differentiate:

```bash
# Olympus (us)
python3 pantheon-webhook-bridge.py --side olympus --port 8013

# Enterprise (you)
python3 pantheon-webhook-bridge.py --side enterprise --port 8014
```

### How it connects

```
Tallon's NATS           Webhook                        Your Pantheon
┌──────────────┐   POST /webhook/incoming    ┌─────────────────────┐
│ relay-7 msg  ├───────────────────────────►  │ webhook-bridge:801X │
│              │   {from, to, subject, body}  │         │           │
└──────────────┘                              │  Writes to god inbox │
                                              │  Sends Telegram ping  │
                                              └─────────────────────┘
```

When a message arrives:
1. It's validated (JSON parse, `to` field required)
2. Written to `~/pantheon/gods/messages/{god}/{message_id}.json`
3. Telegram alert sent (if configured)

---

## 2. Webhook Bridge — What It Does

### Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/webhook/incoming` | POST | Receive relay messages from NATS |
| `/webhook/file` | POST | Receive file notifications from relay |
| `/health` | GET | Health check |

### POST /webhook/incoming

**Request body:**
```json
{
  "from": "tallon",
  "to": "thoth",
  "subject": "Brief: New client onboarding",
  "body": "Here's the summary of the discovery call...",
  "priority": "normal",
  "relay_id": "relay_1744567890"
}
```

**Response:**
```json
{
  "status": "ok",
  "message_id": "relay_1744567890_thoth",
  "delivered_to": "thoth"
}
```

### Configuration

Create `~/pantheon/webhook-{side}.json` or use the `.env` in the profile:

```json
{
  "TELEGRAM_BOT_TOKEN": "your_bot_token",
  "TELEGRAM_CHAT_ID": "your_chat_id"
}
```

If these are set, Telegram alerts fire on every incoming message. If omitted, the bridge still delivers to god inboxes — just no Telegram ping.

---

## 3. Confidence Decay System — What Was Built

### The Problem

Simon Scrapes' "I Built The Best Claude Memory System (Beats Hermes)" video (2 days old, 88K subs) popularized the idea that memory has **three independent jobs** — storage, injection, and recall — and that a confidence decay mechanism is essential for keeping memory systems from accumulating stale data.

His key insight: if you don't decay confidence, old irrelevant data ranks alongside fresh relevant data, and retrieval quality degrades over time.

### What We Added

Our Ichor memory system already had a **relationship weight decay** cycle (exponential decay with configurable half-life). We added the missing pieces:

#### A. Entity confidence decay (`entity_decay` in dream.py)

New sub-cycle that applies exponential decay to:
- **Entity confidence** — if an entity hasn't been touched in >7 days, its `confidence` halves per week. Below 0.1 → archived.
- **Entity facts** — same decay applied to facts attached to stale entities.
- **Cascade** — when an entity is archived, all its relationships are zeroed too.

Run it:
```bash
# Dry run
python3 -m lib.ichor.entities.dream --cycle=entity_decay

# Execute with custom half-life
python3 -m lib.ichor.entities.dream --cycle=entity_decay --half-life-days=14 --execute

# All four cycles
python3 -m lib.ichor.entities.dream --cycle=all --execute
```

#### B. Query-time recency reranker (`recency.py`)

New module that applies the **same** decay formula at query time. This is the "reranker pass" that Simon's system uses — results are boosted or penalized based on how recently the entity was accessed.

```python
from lib.ichor.entities.recency import recency_weight, rerank_results

# Score a single entity
w = recency_weight(
    last_accessed="2026-06-12 20:00:00",  # recently accessed → 1.0
    half_life_days=7
)

# Rerank a list of search results
ranked = rerank_results(
    search_results,
    get_recency_field=lambda r: (r.get("last_accessed"), r.get("updated_at")),
    score_field="confidence",
)
# Results sorted by recency_adjusted_score descending
```

#### C. Touch wiring (graph_query in traversal.py)

Every call to `graph_query()` now automatically updates `last_accessed` on every entity traversed. This means:
- Entities you query frequently stay "fresh" and don't decay
- The recency score at query time reflects actual usage patterns
- The dream cycle archives only entities nobody looked at

#### D. Recency score formula

```
weight = 2^(-Δt / half_life_days)

At Δt = 0 days:   weight = 1.0
At Δt = 7 days:   weight = 0.5   (half-life)
At Δt = 14 days:  weight = 0.25
At Δt = 30 days:  weight = 0.05  → clamped to min_weight=0.1
```

---

## 4. Ichor Memory Architecture (The 3+1 Jobs)

### Storage (3 backends)

| Backend | What it stores | Query method |
|---------|---------------|-------------|
| **FTS5** | Events, facts, decisions | Keyword search via `ichor_retrieve` |
| **Entities/Relationships** | Entity graph (people, orgs, projects) | Graph traversal via `ichor_graph_query` |
| **WARM table** | Pre-computed entity summaries | FTS5 via `athenaeum_graph_search` |

### Injection (what gets loaded at session start)

- `ichor_retrieve` fetches top-N results fused across all backends
- `ichor_graph_query` walks the entity graph from a named start
- `session_search` finds relevant past conversations

### Recall (query-time refinement)

- Recency reranker (new — module `recency.py`)
- 3-stage entity resolution (exact → prefix → warm_entities fallback)
- Adaptive depth in graph traversal

### Decay (background maintenance)

| Cycle | Frequency | What it does |
|-------|-----------|-------------|
| dedup | Daily | Merge duplicate entities by (type, name) |
| contradiction | Daily | Flag conflicting facts/relationships |
| decay (rels) | Weekly | Decay relationship weights |
| entity_decay | Weekly | Decay entity + fact confidence, archive stale |

---

## 5. Your Setup Checklist

### Step 1: Deploy the webhook bridge

```bash
# Copy the script
scp user@pantheon-server:~/pantheon/scripts/pantheon-webhook-bridge.py ./

# Create the service file at ~/.config/systemd/user/pantheon-webhook-enterprise.service
mkdir -p ~/.config/systemd/user

# Write the service:
cat > ~/.config/systemd/user/pantheon-webhook-enterprise.service << 'EOF'
[Unit]
Description=Pantheon Webhook Bridge — Enterprise side (port 8014)
After=network.target

[Service]
Type=simple
WorkingDirectory=%h/pantheon
ExecStart=%h/.hermes/hermes-agent/venv/bin/python3 %h/pantheon/scripts/pantheon-webhook-bridge.py --side enterprise --port 8014
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
EOF

# Start it
systemctl --user daemon-reload
systemctl --user enable --now pantheon-webhook-enterprise
loginctl enable-linger  # required for user services to start on boot

# Verify
curl http://127.0.0.1:8014/health
# → {"status":"healthy","side":"enterprise","telegram_enabled":false}
```

### Step 2: Configure Telegram (optional)

Create `~/pantheon/webhook-enterprise.json`:
```json
{
  "telegram_bot_token": "YOUR_BOT_TOKEN",
  "telegram_chat_id": "YOUR_CHAT_ID"
}
```

Restart the service:
```bash
systemctl --user restart pantheon-webhook-enterprise
```

### Step 3: Install the confidence decay system

The decay system is part of the Ichor entities package at `lib/ichor/entities/`. It requires:

- SQLite3 (bundled with Python)
- `~/.hermes/ichor.db` with entity tables (run migration if needed)

```bash
# Run the dream cycle daily
python3 -m lib.ichor.entities.dream --cycle=dedup,contradiction --execute

# Run decay weekly
python3 -m lib.ichor.entities.dream --cycle=decay,entity_decay --execute
```

### Step 4: Configure NATS to POST to the webhook

On your relay-7 NATS server, configure a subscriber that POSTs to:

```
POST http://<enterprise-server-ip>:8014/webhook/incoming
Content-Type: application/json

{
  "from": "<sender>",
  "to": "<target-god>",
  "subject": "...",
  "body": "...",
  "relay_id": "relay_<timestamp>"
}
```

---

## 6. API Reference

### Dream Cycle CLI

```bash
# Usage
python3 -m lib.ichor.entities.dream [--cycle=CYCLES] [--execute] [--half-life-days=N] [--archive-threshold=N]

# Dry run (default, no writes)
python3 -m lib.ichor.entities.dream

# Daily cycles (dedup + contradiction)
python3 -m lib.ichor.entities.dream --cycle=dedup,contradiction --execute

# Weekly decay cycles
python3 -m lib.ichor.entities.dream --cycle=decay,entity_decay --half-life-days=7 --execute

# All four cycles
python3 -m lib.ichor.entities.dream --cycle=all --execute
```

### Recency Reranker (Python API)

```python
from lib.ichor.entities.recency import recency_weight, rerank_results

# Single entity weight
recency_weight(last_accessed, updated_at=None, half_life_days=7, min_weight=0.1)
# Returns: float in [0.1, 1.0]

# Batch rerank
rerank_results(results, get_recency_field, half_life_days=7, score_field="confidence")
# Returns: results sorted by recency_adjusted_score
```

### Graph Query (auto-touch)

```python
from lib.ichor.entities import graph_query
import lib.ichor.entities.schema as schema

conn = schema.get_conn()
result = graph_query(conn, "EntityName", depth=2)
# Side effect: all visited entities get last_accessed updated to now
conn.close()
```

---

## 7. Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `Connection refused` on port 8014 | Bridge not running | Check `systemctl --user status pantheon-webhook-enterprise` |
| Message not delivered | Invalid JSON or missing `to` field | Check the body has `from`, `to`, `subject`, `body` |
| Decay cycle finds 0 entities | No entities in DB, or all recent | Run `python3 -c "import sqlite3; c=sqlite3.connect(str(Path.home()/'.hermes'/'ichor.db')); print(c.execute('SELECT count(*) FROM entities').fetchone()[0])"` |
| Telegram alerts not firing | Token/chat_id not configured | Set `telegram_bot_token` and `telegram_chat_id` in config |
| `ichor.db not found` | DB path doesn't exist | Run the entity migration first |
| Dream cycle error on `entity_decay` | Old dream.py without the function | Update to latest version |

### File Locations

| File | Path |
|------|------|
| Webhook bridge script | `~/pantheon/scripts/pantheon-webhook-bridge.py` |
| Entity schema | `~/pantheon/lib/ichor/entities/schema.py` |
| Dream cycle | `~/pantheon/lib/ichor/entities/dream.py` |
| Recency reranker | `~/pantheon/lib/ichor/entities/recency.py` |
| Graph traversal | `~/pantheon/lib/ichor/entities/traversal.py` |
| Entity DB | `~/.hermes/ichor.db` |
| God inboxes | `~/pantheon/gods/messages/{god}/` |

---

### Quick verification

```bash
# Test bridge health
curl http://127.0.0.1:8014/health

# Test message delivery
curl -X POST http://127.0.0.1:8014/webhook/incoming \
  -H "Content-Type: application/json" \
  -d '{"from":"tallon","to":"thoth","subject":"Test","body":"Hello from Enterprise!","relay_id":"relay_test_1"}'

# Verify inbox
ls ~/pantheon/gods/messages/thoth/

# Run a dry-run dream cycle to confirm decay system works
cd ~/pantheon && python3 -m lib.ichor.entities.dream --cycle=all
```
