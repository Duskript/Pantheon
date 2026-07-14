# Morning Briefing — Pantheon Example

A self-contained, configurable morning briefing workflow for your Pantheon deployment. Collects system health, nightly consolidation reports, project updates, and more — delivered daily on whatever platform you choose.

## How It Works

A cron job runs a script each morning that gathers data from your Pantheon subsystems, pipes it into an LLM prompt, and the agent composes a briefing in whatever personality you want — Hermes's fast talk, Athena's concise analysis, etc.

```
Pantheon Subsystems          cron job script              LLM Agent              You
┌──────────────┐     ┌───────────────────┐     ┌────────────────────┐     ┌────────┐
│ Hades report  │────▶│                   │     │                    │     │        │
│ Memory health │────▶│  Collect data     │────▶│  Compose briefing  │────▶│ 📱 DM │
│ Project ideas │────▶│  (example script) │     │  in god's voice    │     │        │
│ Git status    │────▶│                   │     │                    │     │        │
│ ... optional  │     └───────────────────┘     └────────────────────┘     └────────┘
```

**No personal info, API keys, or hardcoded paths leak into the repo** — everything is configured via environment variables on your machine.

## Files

| File | What it is |
|------|-----------|
| `morning-briefing.example.py` | Data-collection script — outputs structured context for the agent |
| `README.md` | This file — setup instructions |

## Quick Start

### 1. Place the script somewhere durable

```bash
cp examples/morning-briefing/morning-briefing.example.py ~/.hermes/scripts/morning-briefing.py
chmod +x ~/.hermes/scripts/morning-briefing.py
```

### 2. Configure your env vars

Edit `~/.hermes/.env` (or `~/.hermes/profiles/your-god/.env` if per-profile):

```bash
# ── Required ────────────────────────────────────
PANTHEON_DIR=$HOME/pantheon
ATHENAEUM_DIR=$HOME/athenaeum
HERMES_HOME=$HOME/.hermes

# ── Optional Components ─────────────────────────
# Comment out any you don't have or don't want.
# The script gracefully skips missing paths.
PROJECT_IDEAS_FILE=$PANTHEON_DIR/project-ideas.md
```

### 3. Register the cron job

```bash
hermes cron create \
  --schedule "0 6 * * *" \
  --name "Morning Briefing" \
  --script ~/.hermes/scripts/morning-briefing.py \
  --prompt "Compose an energetic morning briefing delivered in fast-talking Hermes style. Cover system health, any errors from last night, new project ideas, and what's on deck for today." \
  --deliver telegram
```

**Delivery options:**
- `--deliver telegram` — arrives in your DM
- `--deliver local` — saves to file only
- `--deliver origin` — back to wherever you created it from

### 4. Test it immediately

```bash
hermes cron run <job-id>
```

## What the Example Script Collects

The script gathers structured sections separated by `=== SECTION_NAME ===` markers. The LLM agent receives all this as context and composes the briefing:

| Section | Source | What it shows |
|---------|--------|---------------|
| `TIMESTAMP` | `date` | Current time in UTC and local |
| `HADES_REPORT` | `$ATHENAEUM_DIR/Codex-Pantheon/reports/` | Nightly consolidation — errors, stats, new codices |
| `ATHENAEUM_TRIAGE` | `$ATHENAEUM_DIR/scripts/athenaeum-triage.py` | Knowledge base health |
| `PROJECT_IDEAS` | `$PROJECT_IDEAS_FILE` | Pending project ideas |
| `HERMES_UPDATE` | `hermes --version` vs GitHub | Available updates |
| `GIT_STATUS` | `git status --short` | Uncommitted changes across repos |

**Customizing:** Add or remove sections by editing the `COLLECTORS` list in the script. Each section is a small shell command — swap them out for your own data sources.

## Design Philosophy

- **No credentials in scripts** — API keys live in `~/.hermes/.env`, loaded by the gateway, never in the script itself
- **No hardcoded paths** — everything uses `$PANTHEON_DIR`, `$ATHENAEUM_DIR`, etc.
- **Graceful degradation** — missing files or failed subprocesses don't crash the whole briefing
- **Example ≠ production** — fork and customize; this is a starting point, not a turnkey solution
