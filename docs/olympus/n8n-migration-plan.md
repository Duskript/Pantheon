# n8n Integration — Migration Plan

> Written: 2026-05-29  
> Replaces: Composio (Stream B/C auth layers)  
> Target: n8n self-hosted Docker container at `http://localhost:5678`

---

## Why This Exists

Composio has exactly **2 working connections** (Gmail, GitHub) out of 8 providers, with 6 **silently dropped**. The user connected Notion, Google Drive, and Google Calendar in Composio's UI — their API reports them as non-existent. The `connections.json` sync config shows all 8 as `"enabled": false` with `"composio_account_id": null`. Composio is broken at the product level.

n8n is running and verified: 449 built-in credential types, OAuth works in one click, full REST API, MCP server at `http://localhost:5678/mcp-server/http`.

---

## Phase 1 — Sidebar Cleanup + Admin Access

### 1.1 Move Settings Gear Next to User Card

**Current (collapsed rail, bottom):**
```
[Admin Shield]
[spacer]
[Settings Gear]   ← at very bottom
[Profile Avatar]
```

**Target:**
```
[spacer]
[Admin Shield]    ← moves here (easy access, bottom position)
[Settings Gear] [Profile Avatar]  ← settings next to user card
```

**Files to change:**
- `src/components/shell/Sidebar.tsx` — swap positions of Admin shield and Settings gear in the collapsed rail section (~lines 584-608). Move Settings `IconBtn` to sit beside the Profile button instead of above it.

### 1.2 Same Change in Expanded Drawer

The expanded sidebar bottom cluster also needs the swap. Settings label moves next to the user card row.

### 1.3 Remove Settings Title Text

The expanded sidebar Settings label currently reads "Settings" — remove the label text, keep the gear icon only. The collapsed rail already uses icon-only.

---

## Phase 2 — n8n Sidebar Item (Feature-Flagged)

### 2.1 Add `n8n` Feature Toggle

**Files to change (5 locations — per the feature-flag pitfall pattern):**
1. `src/stores/feature-flag-store.ts` — add `'n8n'` to `FeatureToggle` type union
2. Same file — add `{ key: 'n8n', label: 'n8n Automation', description: 'Enable n8n workflow automation and OAuth connections', adminOnly: false }` to `FEATURE_TOGGLES` array
3. Same file — add `n8n: false` to `DEFAULTS` object
4. `src/components/admin/AdminPanel.tsx` — add `n8n` to the FeatureFlags tab's `allToggles` list
5. `src/components/admin/AdminPanel.test.tsx` — update toggle count assertion

### 2.2 Add n8n Icon to Sidebar Rail

- Icon: A workflow/automation icon from lucide-react (e.g., `Workflow` or `Zap`)
- Position: Between Athenaeum and Tools in collapsed rail
- New order: `Mark → GodPicker → NewChat → Search → Athenaeum → n8n → Stream → Tools → spacer → Admin → Settings+Profile`
- Feature-flag gated: `if (!isEnabled('n8n')) return null`
- Click → opens `http://localhost:5678` in a new tab (n8n has its own UI)

**Files:**
- `src/components/shell/Sidebar.tsx` — add `IconBtn` for n8n in collapsed rail + `LabelBtn` in expanded drawer
- Import `useIsFlagEnabled` hook

### 2.3 Add Expanded Drawer Entry

Same node: `LabelBtn icon={Workflow} label="n8n Automation"` in the expanded tools section, gated behind the same feature flag.

---

## Phase 3 — n8n API Client (Olympus Backend)

### 3.1 Create n8n API Wrapper

New file: `~/pantheon/webui/api/n8n_client.py`

```python
# Minimal wrapper around n8n REST API
N8N_BASE = "http://localhost:5678/api/v1"
N8N_API_KEY = os.environ.get("N8N_API_KEY")

def list_credentials() -> list[dict]
def get_credential(credential_id: str) -> dict
def create_credential(name: str, type: str) -> dict  # type = "githubOAuth2Api", "gmailOAuth2Api", etc.
def delete_credential(credential_id: str)
def get_credential_status(credential_id: str) -> str  # "connected" | "error" | "pending"
```

All calls use `X-N8N-API-KEY` header.

### 3.2 Add Olympus Routes

New endpoints in `~/pantheon/webui/api/routes.py`:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/n8n/status` | GET | Health check — is n8n reachable? |
| `/api/n8n/credentials` | GET | List all credentials + their connection status |
| `/api/n8n/credentials/{provider}` | GET | Get single credential status |
| `/api/n8n/credentials/{provider}/connect` | POST | Initiate OAuth for a provider |

### 3.3 Environment Variable

Add `N8N_API_KEY` to the Pantheon webui environment. The key is stored in n8n's settings and never leaves the server.

---

## Phase 4 — Onboarding Integration

### 4.1 Replace Composio with n8n in Onboarding Step 4

Current file: `src/routes/onboarding/integrations.lazy.tsx`

**What changes:**
- Replace the provider list (hardcoded with BrandIcon SVGs) with the same UI but backed by n8n API calls
- Each provider card shows:
  - Brand icon (keep existing SVGs)
  - Provider name
  - "Connect" button → calls `POST /api/n8n/credentials/{provider}/connect`
  - Once connected → green checkmark + "Connected" badge
- "Skip for now" button remains unchanged

**Providers to show:**
- Gmail, GitHub, Google Calendar, Google Drive, Notion, Slack, Discord, Outlook

**Flow per provider:**
1. User clicks "Connect Gmail"
2. Olympus → `POST /api/n8n/credentials/gmail/connect`
3. Backend calls n8n API to initiate OAuth, returns n8n's OAuth URL
4. User completes Google consent in a popup/redirect
5. Olympus polls `GET /api/n8n/credentials/gmail` until status = "connected"
6. Card updates to ✅ green

### 4.2 Settings → Integrations Tab

The existing `ConnectionManager.tsx` in Settings → Integrations should also switch from Composio to n8n. Same API, same UI pattern.

**Files:**
- `src/routes/onboarding/integrations.lazy.tsx` — replace Composio provider logic with n8n API calls
- `src/components/settings/integrations/ConnectionManager.tsx` — same replacement
- `src/components/settings/integrations/useOAuth.ts` — repurpose or replace with n8n hook

---

## Phase 5 — n8n MCP Server for Hermes Agents

### 5.1 Register n8n as MCP Server in Hermes

Add to Hermes MCP config:
```yaml
# ~/.hermes/mcp-servers/n8n.yaml
name: n8n
transport: http
url: http://localhost:5678/mcp-server/http
auth:
  type: token
  token: ${N8N_MCP_TOKEN}
```

This makes n8n workflows available as tools to every Pantheon god.

### 5.2 Create Core Workflows

| Workflow | Trigger | What it does | Exposed as MCP tool |
|---|---|---|---|
| `github_fetch_profile` | Webhook | Fetch GitHub user profile + repos | `github_profile` |
| `gmail_search_recent` | Webhook | Search recent emails by query | `gmail_search` |
| `gmail_fetch_thread` | Webhook | Get full email thread | `gmail_thread` |
| `calendar_today` | Webhook | Get today's events | `calendar_today` |
| `notion_search` | Webhook | Search Notion pages | `notion_search` |
| `drive_search` | Webhook | Search Google Drive files | `drive_search` |

### 5.3 Sync Scheduler as n8n Workflow

Replace the Python `sync_scheduler.py` cron with an n8n Schedule Trigger workflow:

```
Every 20 minutes:
  → For each active credential:
    → Fetch recent items (emails, commits, events, etc.)
    → Format as canonical markdown
    → POST to Pantheon ingest endpoint
```

The Codex-Stream pipeline still runs as Python — n8n just feeds it data.

---

## Phase 6 — Deprecate Composio

### Remove:
- `composio-cli` skill (mark as deprecated)
- Composio API key from `.env`
- `connections.json` references to Composio
- `~/pantheon/cron/pantheon-sync/sync_scheduler.py` → replaced by n8n workflow
- `~/athenaeum/Codex-God-thoth/research/openhuman-pantheon-integration-spec-2026-05-26/PROGRESS.md` → mark as superseded

### Keep:
- `~/pantheon/docs/olympus/composio-setup.md` — archive as "what we tried"
- Codex-Stream ingest pipeline (`~/athenaeum/Codex-Stream/ingest/`) — still Python, just fed by n8n instead of Composio
- The 3 wiki plugins (WikiGuard, Provenance, Dedup) — they operate at the write boundary, unaffected by the auth layer change

---

## BUILD_TRACKER Impact

| Task | Current Status | Change |
|---|---|---|
| I2 (Composio research) | ✅ | Archive — superseded |
| T11 (Sync Scheduler) | ✅ | Rebuild as n8n workflow |
| T12 (Adapters: Gmail/GitHub/Slack) | ✅ | Rebuild as n8n workflows |
| T13 (Codex-Stream Pipeline) | ✅ | Unchanged (Python, fed by n8n) |
| T14 (OAuth Flow UI) | ✅ | Replace Composio with n8n backend |
| T15 Step 4 (Integrations) | ✅ | Replace Composio with n8n |
| T21-T24 (Tier 6) | 🔲 | n8n-native implementation |

---

## Execution Order

1. **Phase 1** — Sidebar cleanup (no dependencies, 1 file)
2. **Phase 2** — n8n feature flag + sidebar icon (depends on Phase 1)
3. **Phase 3** — n8n API client (can run parallel with Phase 2)
4. **Phase 4** — Onboarding + Settings integration (depends on Phase 3)
5. **Phase 5** — MCP server + workflows (can run parallel with Phase 4)
6. **Phase 6** — Composio deprecation (last, after everything is verified)

---

## Risks

- **n8n Docker container must be running** on the host. Add to systemd for auto-start.
- **n8n session expiry** in the browser (sessions are short-lived — cookies expire). Olympus calls use API keys, so this only affects the web UI.
- **n8n community edition** has no SSO/audit logs. Fine for personal use, may matter later.
- **Callback URL for OAuth**: `localhost:5678` works for local dev but needs a real domain for production OAuth. Register a Tailscale Funnel or use n8n's cloud OAuth proxy for production.
