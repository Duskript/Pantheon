# Olympus BTST on relay-7 — Setup Roadmap

**Created:** 2026-07-10T21:28:36-06:00  
**Owner:** Cybermage / Hermes  
**Target install host:** `relay-7` — **not** the current Hermes host  
**Roadmap status:** Planning document, not yet executed  

---

## 0. Executive decision

We are exploring **BTST (`better-stack-ai/better-stack`) as the foundation for the next Olympus web surface** because it matches the direction Cybermage wants:

- fully open-source / self-hostable foundation;
- plugin-style application architecture;
- existing AI Chat, Auth, CMS, Blog, UI Builder, Media, Forms, Comments-style plugin surfaces;
- React-first component registry, so we can pull in **Astryx**, **React Flow**, and custom Olympus/TheoForge components;
- enough structure that Hermes/Iris can later manipulate pages via API/MCP tools instead of hand-editing every screen.

This roadmap assumes:

1. **BTST/Olympus installs on `relay-7`.**  
   Hermes gateways and god profiles stay on the current Hermes/Pantheon host unless a later plan explicitly migrates them.
2. **Ghost remains the publishing/blog authority.**  
   BTST’s blog plugin is not replacing Ghost unless we deliberately choose that later.
3. **New Olympus integrations should become plugins.**  
   When we build plugins, each meaningful plugin gets its own git repo so it can version, test, and ship independently.
4. **TheoForge VE should eventually be designed/composed with the UI Builder.**  
   React Flow and Astryx should be registered as builder components; Cybermage should be able to visually shape the interface.
5. **n8n is not the target architecture.**  
   TheoForge VE remains the replacement direction for n8n-style workflow composition.

---

## 1. relay-7 deployment baseline

### Verified host state

From live SSH inspection of `relay-7`:

| Item | Current state |
|---|---|
| SSH alias | `relay-7` |
| Tailscale host/IP in ssh config | `100.100.46.52` |
| LAN IP pinged | `192.168.1.7` |
| CPU | Intel i3-5005U @ 2.00GHz, 2 cores / 4 threads |
| RAM | 7.2GiB total, ~4.4GiB available at check time |
| Root disk after resize | 466G total, 425G free, 5% used |
| Existing reverse proxy | Caddy |
| Existing tunnel | Cloudflare Tunnel (`theoforge`) |
| Existing services | Nextcloud, Collabora, MySQL, Clawforge services, TheoForge server, NATS, Caddy, cloudflared, tailscaled |

### Deployment rule

All BTST/Olympus runtime services from this plan must be installed on:

```bash
ssh relay-7
```

Preferred app root:

```bash
/srv/olympus-btst
```

Preferred service user:

```bash
konan
```

Do **not** accidentally install the app on `/home/konan` of the Hermes host. Any setup command in implementation must start with a host proof:

```bash
hostname
lsblk
free -h
df -h /
```

Expected relay-7 proof includes the i3-5005U and ~466G root filesystem.

---

## 2. Target architecture

```text
                           Public / Tailnet Users
                                   │
                                   ▼
                          Cloudflare Tunnel / Caddy
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────┐
│ relay-7                                                           │
│                                                                  │
│  /srv/olympus-btst                                                │
│  ├── olympus-btst-app                                             │
│  │   ├── BTST stack config                                        │
│  │   ├── Auth plugin                                              │
│  │   ├── CMS plugin                                               │
│  │   ├── UI Builder plugin                                        │
│  │   ├── plugin package imports                                   │
│  │   └── systemd service                                          │
│  │                                                               │
│  ├── SQLite first, Postgres optional later                        │
│  ├── Caddy route                                                  │
│  └── plugin package working copies / symlinks during dev          │
│                                                                  │
│  Existing relay-7 services stay in place:                         │
│  Nextcloud, Collabora, Clawforge, NATS, Caddy, cloudflared        │
└──────────────────────────────────────────────────────────────────┘
                 │                         │
                 │ Tailscale/API           │ Ghost Content/Admin API
                 ▼                         ▼
┌──────────────────────────────┐   ┌──────────────────────────────┐
│ Current Hermes/Pantheon host │   │ Existing Ghost blog          │
│                              │   │                              │
│ Hermes Gateway               │   │ Public blog/editor remains   │
│ god profiles                 │   │ the source of truth for      │
│ Pantheon MCP                 │   │ publishing                   │
│ OmniRoute                    │   │                              │
└──────────────────────────────┘   └──────────────────────────────┘
```

---

## 3. Repo strategy

### Rule

The app shell and each durable plugin should have its own git repo.

Why:

- each plugin can be tested independently;
- plugins can be versioned/published independently;
- future commercial/client deployments can choose a plugin bundle;
- Hermes/Iris skills can scaffold one plugin without touching unrelated plugins;
- repo boundaries prevent the “everything salad” problem.

### Initial repos

| Repo | Purpose | Package name suggestion | Required now? |
|---|---|---|---|
| `olympus-btst-app` | Actual installed app on relay-7; imports BTST and Olympus plugins | private app | Yes |
| `olympus-plugin-hermes-agent` | Fork/replace BTST AI Chat so it talks to Hermes Gateway/API instead of direct LLM calls | `@olympus/plugin-hermes-agent` | Yes |
| `olympus-plugin-ghost-bridge` | Bridge Ghost Content/Admin API into BTST blocks/tools/sync endpoints | `@olympus/plugin-ghost-bridge` | Yes |
| `olympus-plugin-astryx-registry` | Register Astryx components in the UI Builder component registry | `@olympus/plugin-astryx-registry` | Yes |
| `olympus-plugin-theoforge-ve` | React Flow / TheoForge VE UI Builder components and runtime wiring | `@olympus/plugin-theoforge-ve` | Yes, after base proof |
| `olympus-plugin-ui-builder-mcp` | MCP server exposing UI Builder/CMS/plugin operations to Hermes/Iris | `@olympus/plugin-ui-builder-mcp` | Yes, but after API proof |
| `olympus-plugin-auth-bridge` | Optional future bridge between Ghost members, BTST auth, and Pantheon users | `@olympus/plugin-auth-bridge` | Later |
| `olympus-btst-skill` | Hermes skill documenting how to build/wire BTST plugins | Hermes skill repo or skill folder | Later, after first plugin works |

### Standard repo skeleton for every plugin

Each plugin repo should include:

```text
README.md
LICENSE
package.json
tsconfig.json
src/
  index.ts
  api/
  client/
  schemas.ts
  types.ts
tests/
  *.test.ts
examples/
  minimal-app/
CHANGELOG.md
```

Minimum CI/test contract per plugin:

```bash
pnpm install
pnpm typecheck
pnpm test
pnpm build
```

---

## 4. Phase roadmap

## Phase 0 — Confirm platform decision and cut the branch plan

**Goal:** Lock the architecture before touching relay-7 runtime services.

Locked answers from Cybermage on 2026-07-10:

1. BTST remains the active foundation candidate.
2. Repos remain private. The proposed naming convention is accepted.
3. First preview is **Tailscale-only**. Public Caddy/Cloudflare exposure waits until the rest of the stack works.
4. Initial DB is **SQLite**.
5. Auth is primarily for Cybermage/admin use, but the design must support invited users later:
   - Tallon should eventually be able to log in and connect to **his own Pantheon install**.
   - Amber may be invited after the system is stable.
   - The public is not the target audience.
   - A stripped-down customer version may exist later as a modular frontend customized per install.
6. Ghost bridge must have **full access**. Read-only Content API is not enough. The plugin should support Ghost Content API plus Ghost Admin API, with safety gates for write operations.

Repo owner locked on 2026-07-10:

- GitHub owner/org: `Duskript`
- Private repos created:
  - `https://github.com/Duskript/olympus-btst-app`
  - `https://github.com/Duskript/olympus-plugin-astryx-registry`
  - `https://github.com/Duskript/olympus-plugin-hermes-agent`
  - `https://github.com/Duskript/olympus-plugin-ghost-bridge`
  - `https://github.com/Duskript/olympus-plugin-theoforge-ve`
  - `https://github.com/Duskript/olympus-plugin-ui-builder-mcp`

Remaining Phase 0 details to confirm later:

1. Exact user-to-install identity mapping design for Tallon/Amber/customer installs. This does not block Phase 1 host prep.
2. Exact public domain/subdomain when moving beyond Tailscale-only preview.

Deliverables:

- accepted roadmap;
- repo list approved;
- deployment hostname/subdomain decision recorded.

Verification:

- no runtime changes yet;
- document updated with decisions.

---

## Phase 1 — relay-7 host preparation

**Goal:** Prepare relay-7 for a supervised BTST/Olympus app without disturbing existing services.

Tasks:

1. SSH into relay-7 and prove host identity:

   ```bash
   ssh relay-7
   hostname
   lscpu | grep 'Model name'
   df -h /
   free -h
   ```

2. Create install root:

   ```bash
   sudo mkdir -p /srv/olympus-btst
   sudo chown -R konan:konan /srv/olympus-btst
   ```

3. Verify Node/pnpm versions already present or install via the standard Node toolchain.

4. Create env directory:

   ```bash
   mkdir -p /srv/olympus-btst/env
   chmod 700 /srv/olympus-btst/env
   ```

5. Create log directory:

   ```bash
   mkdir -p /srv/olympus-btst/logs
   ```

6. Decide whether Docker is used.
   - Recommended first pass: no Docker for the app server; use systemd + Node directly.
   - Docker remains available, but Nextcloud/relay services are already doing enough on the box.

Deliverables:

- `/srv/olympus-btst` exists;
- runtime prerequisites checked;
- no ports opened yet.

Verification:

```bash
ssh relay-7 'test -d /srv/olympus-btst && df -h / && free -h'
```

Rollback:

```bash
ssh relay-7 'rm -rf /srv/olympus-btst'
```

Only run rollback before any production data exists.

---

## Phase 2 — Create `olympus-btst-app`

**Goal:** Stand up the app shell on relay-7 with BTST installed but minimal plugins enabled.

Tasks:

1. Create repo `olympus-btst-app`.
2. Scaffold the app in `/srv/olympus-btst/olympus-btst-app`.
3. Add BTST dependency.
4. Add basic stack config:
   - base API path: `/api/data`;
   - initial plugin: health/status route only or minimal CMS plugin;
   - database: SQLite file under `/srv/olympus-btst/data/olympus.db`.
5. Add environment file:

   ```bash
   /srv/olympus-btst/env/olympus-btst.env
   ```

6. Add a systemd unit:

   ```text
   /etc/systemd/system/olympus-btst.service
   ```

7. Bind app to localhost first:

   ```text
   HOST=127.0.0.1
   PORT=31xx
   ```

8. Add Caddy route only after local smoke passes.

Deliverables:

- repo created;
- app boots locally on relay-7;
- systemd unit can start/stop/restart;
- Caddy route drafted but not public until smoke passes.

Verification:

```bash
ssh relay-7 'systemctl status olympus-btst --no-pager'
ssh relay-7 'curl -sS http://127.0.0.1:<PORT>/health'
ssh relay-7 'journalctl -u olympus-btst -n 100 --no-pager'
```

Acceptance gate:

- app returns health 200;
- service restarts cleanly;
- memory delta under ~500MB after warm start.

---

## Phase 3 — Create plugin repos and local workspace wiring

**Goal:** Set up plugin repos before implementing features so repo boundaries are real from the start.

Tasks:

1. Create repos:
   - `olympus-plugin-hermes-agent`
   - `olympus-plugin-ghost-bridge`
   - `olympus-plugin-astryx-registry`
   - `olympus-plugin-theoforge-ve`
   - `olympus-plugin-ui-builder-mcp`

2. Clone them under relay-7 dev workspace:

   ```text
   /srv/olympus-btst/plugins/<repo-name>
   ```

3. In `olympus-btst-app`, add local workspace references during development.

4. Each plugin starts with:
   - package manifest;
   - empty exported plugin function;
   - one typecheck test;
   - README describing scope/non-scope.

Deliverables:

- each plugin is independently buildable;
- app can import a no-op plugin from local workspace.

Verification:

```bash
pnpm -r typecheck
pnpm -r test
pnpm -r build
```

Acceptance gate:

- no plugin implementation begins until the no-op plugin import path works.

### Phase 3 execution log — 2026-07-10 22:48 MDT

Status: **complete and live on relay-7**.

Implemented:

1. Created the remaining private Duskript plugin repos:
   - `olympus-plugin-hermes-agent`
   - `olympus-plugin-ghost-bridge`
   - `olympus-plugin-theoforge-ve`
   - `olympus-plugin-ui-builder-mcp`
2. Added one read-only relay-7 deploy key per new repo.
3. Cloned all new repos under `/srv/olympus-btst/plugins/<repo-name>`.
4. Added typed no-op manifests + no-op factory exports for each plugin.
5. Added README scope/non-scope docs and Vitest manifest tests for each plugin.
6. Added local `file:../plugins/<repo>` references in `olympus-btst-app`.
7. Added `src/lib/plugin-manifests.ts` in the app to import all five private plugin boundaries.
8. Updated `/api/health` and the home page to expose/render all five plugin manifests.
9. Committed deterministic pnpm lockfiles for app and new plugins.
10. Restarted `olympus-btst.service` after successful build.

Verification evidence:

```text
plugin gates: typecheck/test/build passed for all five plugin repos
app gates: typecheck/test/build passed
service=active
tailnet=https://relay7.tail164759.ts.net/ -> http://127.0.0.1:3137
health.pluginManifests.length=5
root page contains Plugin boundaries plus Hermes/Ghost/TheoForge/UI Builder MCP package names
relay repo heads:
  app=099e3b1
  astryx=d40ccce
  hermes-agent=747b09f
  ghost-bridge=aa7ac16
  theoforge-ve=d1b35cb
  ui-builder-mcp=629c6a8
```

Known follow-up: BTST 2.12.2 does not expose an obvious SQLite adapter package. The current runtime still uses `@btst/adapter-memory`; SQLite persistence needs either an upstream-compatible adapter implementation or a confirmed BTST persistence package before Phase 4 stores real UI Builder/CMS data.

---

## Phase 4 — UI Builder + Astryx component registry

**Goal:** Make the UI Builder useful as the design surface for Olympus.

Tasks:

1. Enable BTST CMS + UI Builder plugin in `olympus-btst-app`.
2. In `olympus-plugin-astryx-registry`, register Astryx primitives as UI Builder components.
3. Start with a small set:
   - Button
   - Card
   - Tabs
   - Modal/Dialog
   - Table
   - Sidebar/Nav
   - Form/Input/Select
   - Toast/Alert
4. Define Zod schemas for props.
5. Add field overrides where needed for better property editing.
6. Create one proof page:

   ```text
   /builder/pages/olympus-home-proof
   ```

7. Render that page publicly/protected through `PageRenderer`.

Deliverables:

- UI Builder is live;
- Astryx components appear in the component registry;
- one saved page renders through BTST.

Verification:

- create page in UI Builder;
- reload page;
- verify saved JSON layers persist;
- verify rendered output uses Astryx styles;
- check console/network errors through browser/live dogfood.

Acceptance gate:

- Cybermage can visually modify layout without code changes.

---

## Phase 5 — Hermes Agent plugin

**Goal:** Fork/replace BTST AI Chat into an Olympus/Hermes Agent surface.

Repo:

```text
olympus-plugin-hermes-agent
```

Tasks:

1. Study BTST AI Chat plugin structure:
   - `api/plugin.ts`
   - `client/plugin.tsx`
   - schemas/types/query keys/components.
2. Keep useful pieces:
   - conversation routes;
   - conversation persistence;
   - auth hooks;
   - streaming UI shape;
   - page context/tool schema idea.
3. Replace direct `streamText()` model call with Hermes Gateway/API call.
4. Support Hermes session fields:
   - profile/god;
   - model/provider;
   - conversation/session id;
   - tool events;
   - media attachments later.
5. Register `<HermesChat />` as a UI Builder component.
6. Add route:

   ```text
   /chat
   /chat/:id
   ```

7. Add initial Hermes API config in env:

   ```env
   HERMES_GATEWAY_BASE_URL=http://<hermes-host-tailnet>:<port>
   HERMES_GATEWAY_TOKEN=...
   ```

Deliverables:

- Hermes chat plugin can send a real message to Hermes Agent;
- streaming response appears in Olympus UI;
- conversation history persists in BTST DB;
- no god gateway runs on relay-7 unless explicitly planned later.

Verification:

```bash
curl -sS http://127.0.0.1:<PORT>/api/data/hermes/health
```

Then live UI smoke:

1. open chat;
2. send a simple message;
3. verify streamed response;
4. verify tool-call/event rendering does not break layout;
5. refresh and verify history persists.

Acceptance gate:

- one successful real Hermes roundtrip from relay-7 app to current Hermes host.

---

## Phase 6 — Ghost bridge plugin

**Goal:** Keep Ghost as the publishing source while giving Olympus full Ghost bridge capability. This is not a read-only widget: Cybermage wants the bridge to be useful for real blog operations, so it needs Content API reads plus Admin API write/control surfaces with safety gates.

Repo:

```text
olympus-plugin-ghost-bridge
```

Tasks:

1. Implement Ghost Content API client for public/published reads.
2. Implement Ghost Admin API client for authenticated operations.
3. Keep write operations gated:
   - explicit authenticated user required;
   - draft-first defaults;
   - preview/diff before update where practical;
   - audit log entry for every Admin API call;
   - no bulk destructive operation in the first version.
4. Add backend endpoints:

   ```text
   GET  /api/data/ghost/posts
   GET  /api/data/ghost/posts/:slug
   GET  /api/data/ghost/pages
   POST /api/data/ghost/posts/draft
   PATCH /api/data/ghost/posts/:id
   POST /api/data/ghost/posts/:id/publish
   POST /api/data/ghost/posts/:id/unpublish
   POST /api/data/ghost/sync
   POST /api/data/ghost/webhook
   ```

5. Add frontend hooks/components:
   - `useGhostPosts`
   - `useGhostPostBySlug`
   - `useGhostDraftPost`
   - `GhostPostList`
   - `GhostPostPreview`
   - `GhostDraftEditorLauncher`
6. Register Ghost content and admin blocks in the UI Builder registry.
7. Do **not** prescribe final UI. Keep components low-level and styleable with Astryx.

Deliverables:

- Ghost posts can be fetched from BTST;
- selected Ghost content can be placed in UI Builder pages;
- authenticated Olympus actions can create/update/publish Ghost content through the Admin API;
- Ghost remains publishing source of truth.

Verification:

```bash
curl -sS http://127.0.0.1:<PORT>/api/data/ghost/posts | jq '.items | length'
```

Admin smoke test should create a draft only, never publish on the first pass:

```bash
curl -sS -X POST http://127.0.0.1:<PORT>/api/data/ghost/posts/draft \
  -H 'content-type: application/json' \
  -d '{"title":"Olympus Ghost Bridge Smoke Test","body":"draft smoke test"}'
```

Acceptance gate:

- latest Ghost post appears in a BTST-rendered page without iframe hacks;
- one authenticated draft can be created in Ghost through Olympus;
- no publish/update/delete action is available without explicit authenticated intent and audit logging.

---

## Phase 7 — TheoForge VE plugin

**Goal:** Use the UI Builder and React Flow to improve TheoForge VE without rebuilding blindly from prose.

Repo:

```text
olympus-plugin-theoforge-ve
```

Tasks:

1. Register React Flow as a controlled UI Builder component:
   - `TheoForgeCanvas`
   - `TheoForgeNodePalette`
   - `TheoForgeInspectorPanel`
   - `TheoForgeExecutionLog`
2. Define Zod schemas for layout/config props.
3. Keep workflow graph data separate from page layout data.
   - UI Builder controls where panels/canvas live.
   - TheoForge runtime controls nodes/edges/execution state.
4. Add TheoForge API bridge endpoints or client hooks to existing TheoForge server.
5. Create a first composed page:

   ```text
   /tools/theoforge-ve
   ```

Deliverables:

- TheoForge VE layout can be rearranged visually;
- React Flow canvas renders in Olympus page;
- runtime wiring remains testable and separate.

Verification:

- create test workflow;
- drag/reposition UI panels in builder;
- run workflow through existing TheoForge backend;
- verify execution log updates.

Acceptance gate:

- Cybermage can improve the TheoForge VE UI layout visually without asking Hermes to recode panel positions.

---

## Phase 8 — UI Builder MCP for Hermes/Iris

**Goal:** Give Hermes/Iris safe tool access to UI Builder and CMS data.

Repo:

```text
olympus-plugin-ui-builder-mcp
```

Tasks:

1. Build an MCP server that talks to the BTST app API.
2. Start with read-only tools:

   ```text
   ui_builder_list_pages
   ui_builder_get_page
   ui_builder_list_components
   cms_list_content_types
   cms_get_content_item
   ```

3. Add write tools only after read tools are proven:

   ```text
   ui_builder_create_page
   ui_builder_update_page_layers
   ui_builder_update_component_props
   ui_builder_duplicate_page
   cms_create_content_item
   cms_update_content_item
   ```

4. Add safety gates:
   - diff preview before destructive writes;
   - no delete tool at first;
   - schema validation of layers before update;
   - audit log of agent changes.
5. Register MCP server with Hermes profiles that need it.
   - Hermes first.
   - Iris second.

Deliverables:

- Hermes can inspect UI Builder pages;
- Hermes can create/update draft pages;
- Iris can later participate in page/layout iteration.

Verification:

- MCP manifest lists tools;
- one `ui_builder_get_page` roundtrip succeeds;
- one draft page create succeeds;
- UI Builder opens the generated page without crashing.

Acceptance gate:

- no agent write access to published pages until draft-page writes are proven safe.

---

## Phase 9 — Deployment hardening

**Goal:** Make the relay-7 service durable enough for daily use.

Tasks:

1. Add systemd unit with restart policy.
2. Add Caddy route.
3. Add Cloudflare tunnel route if public access is desired.
4. Add health endpoint.
5. Add log rotation.
6. Add backup plan:
   - SQLite DB backup;
   - env file backup policy;
   - plugin repo backup via git remotes.
7. Add resource monitor:

   ```bash
   systemctl status olympus-btst
   journalctl -u olympus-btst -n 100 --no-pager
   free -h
   df -h /
   ```

8. Add deployment script:

   ```text
   /srv/olympus-btst/scripts/deploy.sh
   ```

Deliverables:

- app restarts on boot;
- app has stable URL;
- backups are documented;
- logs don’t grow forever.

Verification:

```bash
ssh relay-7 'sudo systemctl restart olympus-btst && sleep 2 && systemctl is-active olympus-btst'
ssh relay-7 'curl -sS http://127.0.0.1:<PORT>/health'
```

Acceptance gate:

- reboot-safe, URL reachable, no major memory spike.

---

## Phase 10 — Dogfood and migration path

**Goal:** Move from proof-of-concept to actual Olympus daily-use surface.

Tasks:

1. Dogfood core flows:
   - login;
   - chat with Hermes;
   - open UI Builder;
   - edit a page;
   - render a page;
   - fetch Ghost posts;
   - open TheoForge VE proof page.
2. Compare against current Olympus UI feature parity docs.
3. Decide which current Olympus surfaces become:
   - BTST UI Builder pages;
   - registered components;
   - standalone plugins;
   - deprecated surfaces.
4. Create migration cards for each surface.
5. Keep old Olympus UI live until BTST Olympus passes parity gates.

Deliverables:

- dogfood report;
- parity matrix;
- migration sequence;
- go/no-go decision for making BTST Olympus the primary web UI.

Acceptance gate:

- no cutover until the new surface proves superior for real daily tasks.

---

## 5. Plugin build order

Recommended sequence:

1. `olympus-btst-app` — must boot first.
2. `olympus-plugin-astryx-registry` — makes UI Builder worth using.
3. `olympus-plugin-hermes-agent` — core Olympus purpose.
4. `olympus-plugin-ghost-bridge` — connects current publishing stack.
5. `olympus-plugin-theoforge-ve` — uses React Flow and builder composition.
6. `olympus-plugin-ui-builder-mcp` — enables Hermes/Iris agent access.
7. `olympus-plugin-auth-bridge` — only if Ghost/BTST user identity needs unification.

Reasoning:

- UI Builder without Astryx is too generic.
- Hermes chat is the core product loop.
- Ghost bridge is valuable but not blocker for Hermes chat.
- TheoForge VE depends on React Flow/component registry patterns learned in earlier phases.
- MCP write access should wait until page data contracts stabilize.

---

## 6. Resource budget on relay-7

Expected added load:

| Component | Expected RAM |
|---|---:|
| BTST/Next app server | 150–300MB |
| SQLite | tiny / process-local |
| Postgres if added later | 100–250MB |
| Plugin overhead | negligible beyond app bundle |
| MCP server | 50–150MB |

Budget rule:

- Keep Hermes god gateways off relay-7 for now.
- Keep database SQLite first unless concurrency/data size forces Postgres.
- Check `free -h`, `df -h /`, and app RSS after each phase.

Relay-7 currently has enough headroom after disk expansion:

- ~425GB free disk;
- ~4.4GiB available RAM at inspection;
- idle CPU load at inspection.

---

## 7. Security and access rules

1. No public unauthenticated Hermes chat.
2. Environment secrets live in `/srv/olympus-btst/env/*.env`, mode `600` or directory `700`.
3. Ghost Admin API key is optional and should not be added until needed.
4. MCP write tools start draft-only.
5. Caddy/Cloudflare routes should start protected or tailnet-only unless explicitly opened.
6. Plugin repos must not commit secrets.
7. Every API bridge gets a health endpoint and a no-secret smoke test.

---

## 8. Decisions and remaining questions before implementation

| Area | Current answer | Build impact |
|---|---|---|
| Repo visibility | Private repos | Proceed |
| Repo naming | Proposed `olympus-*` names accepted | Proceed |
| GitHub owner/org | Still confirm at creation time; default to same owner/org as other Olympus/TheoForge repos | Blocks remote repo creation only; local scaffolding can proceed |
| First exposure | Tailscale-only first; public route later | Proceed |
| DB | SQLite first | Proceed |
| Auth audience | Primarily Cybermage/admin; Tallon later with his own Pantheon install; Amber later; possible stripped-down customer frontend later | Proceed for admin-only base; identity mapping needed before multi-install user support |
| Ghost bridge scope | Full access: Content API + Admin API | Update Phase 6 scope; requires stronger safety gates |
| UI aesthetic | Cybermage designs via UI Builder; Hermes wires behavior | Proceed |
| MCP write access | Draft-only until safe | Proceed later |

Remaining design question that does **not** block Phase 1:

> How exactly should a logged-in user map to a Pantheon install?

Candidate model for later: each user/account has an `InstallConnection` record with `name`, `baseUrl`, `ownerUserId`, auth token/secret reference, status, and allowed plugin capabilities. Tallon logs in to Olympus and selects/uses his own Pantheon install rather than Cybermage's.

---

## 9. First implementation wave checklist

When Cybermage says “do it,” start with only this wave:

1. SSH to relay-7 and prove host identity.
2. Create `/srv/olympus-btst`.
3. Create `olympus-btst-app` repo.
4. Scaffold minimal BTST app.
5. Start local-only service.
6. Verify health endpoint.
7. Create no-op `olympus-plugin-astryx-registry` repo and import it.
8. Commit all scaffolding.
9. Report:
   - repo URLs/paths;
   - service status;
   - memory/disk delta;
   - next exact wave.

Do **not** start all plugin builds in parallel before the app shell is proven on relay-7.

### Wave 1 execution log — 2026-07-10 22:20 MDT

Status: **complete and live on relay-7**.

Implemented:

1. Proved target host identity: `relay7`, Intel i3-5005U, 466G root filesystem.
2. Created `/srv/olympus-btst` on relay-7 with `plugins/`, `env/`, `logs/`, `data/`, and `tmp/` runtime directories.
3. Created private Duskript repos:
   - `olympus-btst-app`
   - `olympus-plugin-astryx-registry`
4. Built `olympus-btst-app` as a minimal Next/BTST app:
   - BTST backend mounted at `/api/data`
   - health endpoint at `/api/health`
   - imports `@olympus/plugin-astryx-registry`
5. Built `olympus-plugin-astryx-registry` as an independently tested no-op plugin package.
6. Installed dependencies with Corepack/pnpm on relay-7.
7. Verified on relay-7:
   - plugin `typecheck` passes
   - plugin `test` passes
   - plugin `build` passes
   - app `typecheck` passes
   - app `test` passes
   - app `build` passes
8. Installed systemd service:
   - unit: `/etc/systemd/system/olympus-btst.service`
   - bind: `127.0.0.1:3137`
   - status: active/running
9. Exposed tailnet-only via Tailscale Serve:
   - `https://relay7.tail164759.ts.net/`
   - proxy: `http://127.0.0.1:3137`

Verification evidence:

```text
service=active
local_health=True relay-7 @olympus/plugin-astryx-registry
tailscale_serve=https://relay7.tail164759.ts.net (tailnet only)
root_disk=466G total / 424G free / 5% used
available_ram=4.3Gi
node_processes=corepack pnpm start + next-server v16.2.10
```

Follow-up — 2026-07-10 22:29 MDT: relay-7 GitHub pull access is configured.

- Added one read-only deploy key per private repo because GitHub deploy keys are repo-scoped:
  - `relay7-olympus-btst-app-read-only`
  - `relay7-olympus-plugin-astryx-registry-read-only`
- Added relay-7 SSH host aliases:
  - `github.com-duskript-olympus-btst-app`
  - `github.com-duskript-olympus-plugin-astryx-registry`
- Updated relay-7 git remotes to SSH alias URLs.
- Verified from relay-7:
  - `git ls-remote origin HEAD` works for both repos.
  - `git pull --ff-only` returns `Already up to date` for both repos.
  - working trees are clean.

Deploy posture: relay-7 can now pull private code directly. It does **not** have repo write access through these deploy keys.

---

## 10. Definition of success

This setup is successful when:

- relay-7 runs a stable BTST/Olympus app under systemd;
- Cybermage can visually build Olympus pages using Astryx components;
- a Hermes chat component can be dropped into a UI Builder page and talk to the real Hermes Gateway;
- Ghost content can be consumed by Olympus through a plugin without replacing Ghost;
- TheoForge VE can be redesigned visually using React Flow + Astryx components;
- Hermes/Iris can inspect and eventually edit UI Builder draft pages via MCP tools;
- each major plugin is isolated in its own git repo with tests and documented boundaries.

---

## 11. Explicit non-goals for this roadmap

- Do not migrate Ghost off Ghost.
- Do not deploy Hermes god gateways to relay-7.
- Do not replace TheoForge VE with n8n.
- Do not make UI Builder MCP writes unrestricted.
- Do not cut over current Olympus UI until BTST Olympus passes dogfood and parity checks.
- Do not merge all plugins into one repo unless Cybermage explicitly reverses the per-plugin repo decision.
