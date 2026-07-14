# Ledger — Drift Remediation Build Plan

> **Status:** OPERATOR-LOCKED — pending Konan sign-off
> **Date:** 2026-06-21 (updated 2026-06-21 — two-way calendar sync scope + Vaultwarden security isolation)
> **Author:** Hephaestus
> **Trigger:** Tier-1 Acceptance Gate audit (2026-06-21) — zero Docker images built, zero containers running, Vaultwarden/DocuSeal never deployed
> **Project root:** `/home/konan/projects/theoforge-ledger/`
> **Supersedes:** Nothing — this is a remediation plan, not a new feature plan
> **Governing spec:** `~/athenaeum/Codex-Forge/build/ledger-founder-cohort-blueprint.md` (Phases A-F)
> **Key decision:** Optimized stack — 7 services, ~2.8 GB RAM (down from 8.5 GB). DocuSeal runs on SQLite (no separate DB). Vaultwarden runs on built-in SQLite (completely isolated from shared PostgreSQL). Pantheon Core (Hermes + Practice Manager god + Ichor + Athenaeum) runs as a single container inside the stack. One package, not two.
> **L8 scope decision (2026-06-21):** Two-way calendar sync is mandatory — one-way push is insufficient. Phase L8 expanded from verification-only (S) to implementation + verification (M). Adds busy-time reads, polling reconciliation, OAuth2 connection flow, and two-way E2E tests.

---

## 0. Provenance

| Source | What it told us |
|---|---|
| **Build blueprint Phases A-F** | Phase A: Infra templates (Traefik, docker-compose, provision scripts). Phase B: Ledger Core deploy (ERPNext + DocuSeal + Vaultwarden + Pantheon + practice manager). Phase F: Client Intake + Admin MVPs. |
| **Acceptance gate audit (2026-06-21)** | Docker images (`theoforge/erpnext`, `theoforge/conductor`) — NOT BUILT. Vaultwarden — compose entry only, never deployed. DocuSeal — compose entry only, never deployed. Zero running containers. .env.example only, no real config. provision-firm.sh never tested. Ledger intake/admin code exists on disk but never integrated into a running ERPNext instance. |
| **Tier-1 expanded gates (2026-06-21)** | Item 9 now mandatory — system must demonstrably work end-to-end. "Done" = operator can use it. |

---

## 1. Tier Routing Summary

**Specialists:** Marvin (Docker builds, Frappe custom app installs, infra scripting), Hephaestus (architecture review, Tier-1 spec-conformance + acceptance), Konan (DNS, accounts, Stripe, domain ownership)
**Pattern:** Strictly sequential L0→L7. L8 (admin scheduling) can begin once L4 completes (apps installed). L8 implementation (L8.2–L8.4) and L9/L10 verification can run in parallel once L7 completes.
**Complexity:** High — Docker image builds, Frappe bench operations, DNS, TLS, multi-service orchestration

---

## 2. Foundation — What Exists

| Asset | Status |
|---|---|
| `infra/_templates/docker-compose.yml` | ⚠️ Needs rewrite — current spec is 8 services, 8.5 GB. Optimized target: 7 services, ~2.8 GB. |
| `infra/_templates/traefik/docker-compose.yml` + `traefik.yml` | ✅ |
| `infra/_templates/scripts/provision-firm.sh` | ✅ Template exists, needs testing |
| `infra/_templates/scripts/monitor-firm.sh` | ✅ |
| `infra/_templates/webhooks/stripe-listener.py` + `.service` | ✅ |
| `frappe-bench/apps/ledger_brand/` | ✅ Custom Frappe app with branding + practice manager |
| `src/ledger_intake/` (17 files) | ✅ Code-complete, tests pass |
| `src/ledger_admin/` (17 files) | ⚠️ Code-complete, tests pass — but **one-way calendar sync only**. Two-way sync (busy reads + reconciliation) not yet implemented. |
| Docker installed (v29.4.3) | ✅ |
| `theoforge/erpnext:v16.22.0-ledger-1` image | ❌ NOT BUILT |
| `theoforge/pantheon-core:ledger-1` image | ❌ NOT BUILT (new — Hermes + Practice Manager god + Ichor + Athenaeum) |
| `theoforge/conductor:latest` image | ❌ NOT BUILT |
| `.env` with real secrets | ❌ `.env.example` only |
| Running Ledger instance | ❌ Zero containers |
| Beelink host (8GB RAM, ~3.1GB free) | ⚠️ Optimized stack fits (~2.8 GB). Original stack (8.5 GB) would not. |

### Optimized Service Topology

```
                    Traefik (64 MB, TLS termination)
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
   ledger.{domain}    sign.{domain}     vault.{domain}
        │                  │                  │
   ┌────┴────┐      ┌─────┴─────┐     ┌─────┴──────┐
   │ Frappe  │      │ DocuSeal  │     │ Vaultwarden│
   │ 1 GB    │      │ 256 MB    │     │ 256 MB     │
   └────┬────┘      │ (SQLite)  │     │ (SQLite)   │
        │           └───────────┘     └────────────┘
   ┌────┴────────────────────┐
   │    PostgreSQL (shared)  │
   │    512 MB               │
   └─────────────────────────┘

   ┌─────────────────────────┐
   │    Pantheon Core        │
   │    512 MB               │
   │  ┌───────────────────┐  │
   │  │ Hermes Agent      │  │
   │  │ Practice Mgr God  │──┼──→ Frappe REST API
   │  ├───────────────────┤  │     (ledger_intake,
   │  │ Ichor (memory)    │  │      ledger_admin,
   │  │ Athenaeum (KB)    │  │      ERPNext)
   │  └───────────────────┘  │
   └─────────────────────────┘

   ┌──────┐  ┌──────────┐
   │Redis │  │Conductor │
   │128MB │  │ 128 MB   │
   └──────┘  └──────────┘
```

| Service | RAM | Image | Notes |
|---|---|---|---|
| Traefik v3 | 64 MB | `traefik:latest` | TLS termination, routing |
| PostgreSQL 16 | 512 MB | `postgres:16-alpine` | Shared — Frappe + Conductor |
| Redis 7 | 128 MB | `redis:7-alpine` | Cache + Frappe queue |
| Frappe/ERPNext | 1 GB | `theoforge/erpnext:v16.22.0-ledger-1` | Ledger-branded, 3 custom apps |
| DocuSeal | 256 MB | `docuseal/docuseal:latest` | SQLite mode — no separate DB |
| Vaultwarden | 256 MB | `vaultwarden/server:latest` | Built-in SQLite |
| **Pantheon Core** | **512 MB** | `theoforge/pantheon-core:ledger-1` | Hermes + Practice Manager god + Ichor + Athenaeum |
| Conductor v2 | 128 MB | `theoforge/conductor:latest` | Workflow engine |
| **Total** | **~2.8 GB** | | Fits in 3.1 GB available |

**7 services** — dropped docuseal-db. DocuSeal runs on SQLite inside its own container.

### Database Isolation Boundaries

Each service's data is physically isolated — compromise of one database does not expose others:

| Service | Database | Storage | Isolation mechanism |
|---|---|---|---|
| Frappe/ERPNext | PostgreSQL (shared) | Named volume `postgres_data` | Separate database `frappe` within PG instance |
| Conductor v2 | PostgreSQL (shared) | Named volume `postgres_data` | Separate database `conductor` within PG instance |
| **Vaultwarden** | **Built-in SQLite** | **Named volume `vaultwarden_data`** | **Physically separate — different volume, different engine, different process. No PostgreSQL connection string configured.** |
| **DocuSeal** | **Built-in SQLite** | **Named volume `docuseal_data`** | **Physically separate — different volume, different engine, different process. `DATABASE_URL` env var explicitly NOT set.** |
| **Pantheon Core** | **Ichor SQLite** | **Named volume `pantheon_data`** | **Physically separate — Ichor DB inside Pantheon container, never exposed.** |

**Key:** If PostgreSQL is compromised, Vaultwarden, DocuSeal, and Pantheon Core are untouched. If the Vaultwarden container is compromised, PostgreSQL is untouched. All SQLite databases are encrypted at rest by the application layer (Vaultwarden encrypts all secrets; DocuSeal encrypts documents).

**The Docker compose change for Vaultwarden:** No `DATABASE_URL` env var. The container defaults to its built-in SQLite backend (`/data/db.sqlite3`). The only thing touching that database is the Vaultwarden API, which requires authentication.

**Pantheon Core** is the new service. It's a single Docker container that runs:
- **Hermes Agent** — the multi-agent runtime
- **Practice Manager god** — conversational AI that talks to Frappe's REST API. "Schedule this client," "what's AR look like," "send the engagement letter."
- **Ichor** — god memory layer (SQLite-backed, already built + QA'd)
- **Athenaeum** — firm knowledge base (markdown files, FTS5 indexed)

It replaces the standalone "Ops Manager" profile idea. One container, one package, one docker-compose service. The Practice Manager god is the primary agent; other gods (Thoth for research, Iris for design) are available but dormant.

### RAM Savings Breakdown

| What changed | Savings |
|---|---|
| DocuSeal SQLite mode (drop docuseal-db container) | 512 MB |
| Frappe from 3 GB → 1 GB (single-firm, 1-5 users) | 2 GB |
| PostgreSQL from 2 GB → 512 MB (single-firm DB) | 1.5 GB |
| DocuSeal from 1 GB → 256 MB (SQLite, low volume) | 768 MB |
| Vaultwarden from 512 MB → 256 MB | 256 MB |
| Conductor from 1 GB → 128 MB (thin API) | 872 MB |
| Redis from 512 MB → 128 MB | 384 MB |
| Pantheon Core (new) | +512 MB |
| **Net savings** | **~5.7 GB** |

### Hermes Agent Skill Profile for Practice Manager God

The Practice Manager god gets a focused skill set — everything needed to run a firm, nothing else:

**Installed & ON:** Pantheon core, Frappe REST API client, Email (Resend), Calendar (Google/Outlook), Note-taking (Athenaeum), Browser (for web research)

**Installed but OFF (toggle-on when needed):** Creative, Marketing, Social Media, PM skills

**Cut entirely:** DevOps, Gaming, ML Ops, Autonomous agents, Red-teaming, Smart Home, GitHub, Data Science, Code generation, Kanban orchestration

This keeps the image small and the god focused on firm operations.

---

## 3. Phased Implementation Plan

```
Phase L0: Rewrite docker-compose.yml (optimized 7-service stack)
  ↓
Phase L1: Build Docker images (ERPNext + Pantheon Core + Conductor)
  ↓
Phase L2: Configure .env + provision first firm
  ↓
Phase L3: Deploy full stack → verify Traefik routes all services
  ↓
Phase L4: Install Frappe custom apps (ledger_brand, ledger_intake, ledger_admin)
  ↓
Phase L5: Verify Vaultwarden reachable
  ↓
Phase L6: Verify DocuSeal reachable + test e-sign flow
  ↓
Phase L7: Verify Client Intake end-to-end (portal upload)
  ↓
Phase L8: Admin Scheduling — two-way calendar sync (implement + verify)
  ↓
Phase L9: Verify Pantheon Core — Practice Manager god converses with Frappe
  ↓
Phase L10: Acceptance gate — full founder walkthrough
```

### Phase Plan Summary

| Phase | Owner(s) | Size | Status |
|---|---|---|---|
| L0 | Marvin (compose) + Hephaestus (review) | M | ⏳ |
| L1 | Marvin (builds) | L | ⏳ |
| L2 | Marvin + Konan (DNS) | M | ⏳ |
| L3 | Marvin + Konan | M | ⏳ |
| L4 | Marvin | M | ⏳ |
| L5 | Hephaestus | S | ⏳ |
| L6 | Hephaestus | S | ⏳ |
| L7 | Hephaestus | S | ⏳ |
| L8 | Marvin (L8.2–L8.4 code) + Hephaestus (L8.1 + L8.5 verify) | M | ⏳ |
| L9 | Hephaestus | M | ⏳ |
| L10 | Hephaestus | M | ⏳ |

---

## 4. File-by-File Changes

### Phase L0 — Rewrite docker-compose.yml (Optimized Stack)

| # | Path | Action | Owner |
|---|---|---|---|
| L0.1 | `infra/_templates/docker-compose.yml` | REWRITE. Drop docuseal-db service. DocuSeal → SQLite mode. Reduce all memory limits per the optimized table above. Add Pantheon Core service. 7 services total. | Marvin |
| L0.2 | `infra/_templates/.env.example` | UPDATE. Add Pantheon Core env vars (HERMES_SESSION_TOKEN, PRACTICE_MANAGER_API_KEY, ATHENAEUM_PATH, ICHOR_DB_PATH). Remove docuseal-db vars. | Marvin |
| L0.3 | Architecture review | Hephaestus reviews the compose for correctness: service topology, network isolation, volume mounts, healthchecks, Traefik labels. | Hephaestus |

**Size:** M
**Gate:** Compose file passes `docker compose config` validation. 7 services, all with healthchecks, all RAM limits at optimized values.

| # | Path | Action | Owner |
|---|---|---|---|
| L1.1 | `frappe_docker/` or Dockerfile | BUILD custom ERPNext image with ledger_brand app pre-installed. Tag: `theoforge/erpnext:v16.22.0-ledger-1`. | Marvin |
| L1.2 | `pantheon-core/Dockerfile` | BUILD Pantheon Core image. Hermes Agent + Practice Manager god profile + Ichor DB + Athenaeum. Tag: `theoforge/pantheon-core:ledger-1`. | Marvin |
| L1.3 | `conductor/Dockerfile` | BUILD Conductor image from Pantheon conductor v2. Tag: `theoforge/conductor:latest`. | Marvin |
| L1.4 | Verify all three images exist in `docker images` | Hephaestus |

**Size:** L (Docker builds are slow; Frappe image is the largest)
**Gate:** `docker images | grep theoforge` shows all three images: erpnext, pantheon-core, conductor.

### Phase L2 — Configure .env + Provision First Firm

| # | Path | Action | Owner |
|---|---|---|---|
| L2.1 | `infra/_templates/.env` | CREATE from `.env.example`. Generate strong passwords. Set FIRM_SLUG=`ledger-demo`, DOMAIN=`theoforge.app` (or a test domain). | Marvin + Konan |
| L2.2 | DNS | Konan creates A record for `*.theoforge.app` → Beelink IP. Or use a test subdomain on Tailscale. | Konan |
| L2.3 | `provision-firm.sh` | TEST the script. It should: create Docker networks, start Traefik, start the full stack. | Marvin |
| L2.4 | Verify all containers healthy (`docker ps` shows all 8 services with healthy status) | Hephaestus |

**Size:** M (Konan must do DNS; the rest is scripting)
**Gate:** `docker ps` shows postgres, redis, frappe, docuseal, docuseal-db, vaultwarden, conductor all healthy.

### Phase L3 — Deploy Full Stack

| # | Path | Action | Owner |
|---|---|---|---|
| L3.1 | Run `provision-firm.sh ledger-demo` | START the full stack. Wait for all healthchecks. | Marvin |
| L3.2 | Verify Traefik dashboard or logs show routes active | Hephaestus |
| L3.3 | Verify `https://ledger.theoforge.app` (or test domain) reaches Frappe login | Hephaestus |
| L3.4 | Verify `https://sign.theoforge.app` reaches DocuSeal | Hephaestus |
| L3.5 | Verify `https://vault.theoforge.app` reaches Vaultwarden | Hephaestus |

**Size:** M
**Gate:** All three subdomains respond with HTTPS 200.

### Phase L4 — Install Frappe Custom Apps

| # | Path | Action | Owner |
|---|---|---|---|
| L4.1 | `frappe-bench/apps/ledger_brand/` | INSTALL into running Frappe instance: `bench get-app ledger_brand` → `bench install-app ledger_brand` | Marvin |
| L4.2 | `frappe-bench/apps/ledger_intake/` | INSTALL intake app: `bench get-app ledger_intake` → `bench install-app ledger_intake` | Marvin |
| L4.3 | `frappe-bench/apps/ledger_admin/` | INSTALL admin app: `bench get-app ledger_admin` → `bench install-app ledger_admin` | Marvin |
| L4.4 | Verify all three apps appear in Frappe Apps list and site dashboard | Hephaestus |

**Size:** M
**Gate:** Frappe site shows ledger_brand, ledger_intake, ledger_admin as installed apps with no errors.

### Phase L5 — Verify Vaultwarden

| # | Action | Owner |
|---|---|---|
| L5.1 | Navigate to `https://vault.theoforge.app` → verify login page renders | Hephaestus |
| L5.2 | Use ADMIN_TOKEN to access admin panel → verify org configured | Hephaestus |
| L5.3 | Create a test credential → verify it persists | Hephaestus |

**Gate:** Vaultwarden is operational. Can store and retrieve credentials.

### Phase L6 — Verify DocuSeal

| # | Action | Owner |
|---|---|---|
| L6.1 | Navigate to `https://sign.theoforge.app` → verify DocuSeal loads | Hephaestus |
| L6.2 | Create a test document template → send for test signing → verify e-sign flow works | Hephaestus |
| L6.3 | Verify DocuSeal is reachable from Frappe (same Docker network) | Hephaestus |

**Gate:** DocuSeal is operational. Can create, send, and sign documents.

### Phase L7 — Verify Client Intake End-to-End

| # | Action | Owner |
|---|---|---|
| L7.1 | Navigate to portal upload page at `https://ledger.theoforge.app/c/test-client` | Hephaestus |
| L7.2 | Upload a test document → verify it creates a Client Intake Request in ERPNext | Hephaestus |
| L7.3 | Send a test email to `intake+test-client@theoforge.app` → verify email forwarding creates intake record | Hephaestus |
| L7.4 | Trigger SMS reminder → verify Twilio sends (test mode) or console logs the message | Hephaestus |

**Gate:** Client Intake MVP works. Portal upload, email forwarding, and SMS reminders all functional.

### Phase L8 — Admin Scheduling — Two-Way Calendar Sync

**Context:** The shipped `ledger_admin` app (17 files, Phase F) has one-way calendar sync: booking → founder's Google/Outlook. This is insufficient. A business owner who manually adds a dentist appointment to Google Calendar must not get double-booked because Ledger doesn't see it. Two-way sync is required before declaring Cal.com "replaced."

**Approach:** Polling-based reconciliation (no webhook registration required). Every 5 minutes, `ledger_admin` reads the founder's live Google/Outlook calendar via `get_freebusy`, compares to Booking Slot rows, and reconciles. Webhooks deferred to v1.1.

| # | Path | Action | Owner |
|---|---|---|---|
| **L8.1** | Booking page | VERIFY one-way flow still works: navigate to booking page → book slot → calendar event appears in Google/Outlook. Confirmation email sent. Booking appears in ERPNext. | Hephaestus |
| **L8.2** | `src/ledger_admin/api/availability.py` | MODIFY `get_available_slots` to call `get_freebusy` on the founder's connected Google/Outlook calendars. Merge busy intervals from live calendars with booked Booking Slot rows. Slots that conflict with ANY busy interval (either from Ledger bookings OR from external calendar events) are excluded. | Marvin |
| **L8.3** | `src/ledger_admin/api/calendar_sync.py` | ADD `reconcile_calendar_events()` — a Frappe scheduler job (every 5 min) that: (a) reads events from the founder's calendar since last sync, (b) compares to Booking Slot rows, (c) reconciles: deleted event → free the slot, moved event → update slot time, new external event → mark overlapping slots as busy. | Marvin |
| **L8.4** | `src/ledger_admin/public/booking/` + settings page | ADD OAuth2 connection UI. The founder needs a settings page in the Ledger sidebar where they click "Connect Google Calendar" or "Connect Outlook Calendar." `ledger_admin` already has `build_authorize_url` + `exchange_code_for_tokens`. Need the UI to trigger them. | Marvin |
| **L8.5** | Two-way E2E test | (a) Book a slot → verify it appears in Google Calendar. (b) Delete that event from Google Calendar → wait 5 min → verify slot is freed in Ledger. (c) Book a slot → move it in Google Calendar → wait 5 min → verify slot time updates. (d) Add a manual dentist appointment in Google Calendar → verify that time slot no longer appears as available in Ledger. | Hephaestus |

**Size:** M (was S — verification only. Now includes 3 code changes + OAuth UI + E2E test)
**Gate:** All four two-way scenarios pass. Double-booking is impossible.

### Phase L9 — Verify Pantheon Core

| # | Action | Owner |
|---|---|---|
| L9.1 | Verify Pantheon Core container is healthy (`docker ps` shows pantheon-core with healthy status) | Hephaestus |
| L9.2 | Verify Hermes Agent gateway responds: `curl http://pantheon-core:8787/health` → 200 | Hephaestus |
| L9.3 | Verify Practice Manager god is registered and reachable via Hermes messaging | Hephaestus |
| L9.4 | Send a natural-language command to the Practice Manager god: "What's the status of Client Intake for the demo firm?" → verify it queries Frappe API and returns a coherent response | Hephaestus |
| L9.5 | Verify Ichor memory is writable/readable: store a test memory, retrieve it | Hephaestus |
| L9.6 | Verify Athenaeum KB is accessible: read a codex, write a test note | Hephaestus |

**Gate:** Practice Manager god can receive a conversational command, query Frappe's REST API, and return a useful response. Ichor and Athenaeum are operational.

### Phase L10 — Acceptance Gate

| # | Action | Owner |
|---|---|---|
| L9.1 | Full founder walkthrough: sign up → Stripe → see dashboard → submit doc via intake → book via admin | Hephaestus |
| L9.2 | Verify all 8 services healthy after 24h uptime | Hephaestus |
| L9.3 | Verify backup script runs and produces a restic snapshot | Hephaestus |
| L9.4 | Verify monitor-firm.sh alerts on service failure | Hephaestus |

**Gate:** System passes the "first 10 minutes" test from the blueprint Phase D: a founder can sign up, see their dashboard, submit a doc, book a meeting.

---

## 5. Tests + Verification Gates

| Phase | Gate | Method |
|---|---|---|
| L1 | Docker images built | `docker images \| grep theoforge` |
| L2 | .env configured + provision runs | `provision-firm.sh ledger-demo` → all containers healthy |
| L3 | All subdomains reachable | curl `https://{ledger,sign,vault}.theoforge.app` → 200 |
| L4 | Frappe apps installed | Frappe dashboard shows 3 custom apps |
| L5 | Vaultwarden operational | Create/retrieve test credential |
| L6 | DocuSeal operational | Create/send/sign test document |
| L7 | Client Intake works | Portal upload + email forwarding + SMS |
| L8 | Admin Scheduling works — two-way sync | Booking page + calendar sync + busy reads + reconciliation + two-way E2E |
| L9 | Full acceptance sweep | Founder walkthrough end-to-end |

---

## 6. Guardrails

- Do NOT modify the docker-compose.yml service topology.
- **L8 exception:** `ledger_admin` app code may be changed for two-way calendar sync (L8.2–L8.4) — Konan explicitly directed this. All other Frappe app code (ledger_brand, ledger_intake) remains unchanged.
- Do NOT commit `.env` or secrets to git.
- Do NOT expose services without Traefik TLS.
- If Beelink RAM is insufficient for full stack (needs ~8GB, has ~3.1GB free), escalate to Konan — options: add swap, use external VPS, or deploy lighter stack.

---

## 7. Pitfalls

| # | Risk | Mitigation |
|---|---|---|
| 1 | **Beelink OOM** — full Ledger stack needs ~8GB RAM, Beelink has 3.1GB free | Run only core services (ERPNext + DocuSeal), skip Vaultwarden/Conductor for initial test. Or deploy to external VPS. |
| 2 | **Frappe Docker build is complex** — custom image requires frappe_docker build chain | Clone `frappe/frappe_docker`, customize Dockerfile, build. May take 30-60 min. |
| 3 | **DNS not ready** — `theoforge.app` domain not configured | Use `.localhost` or Tailscale MagicDNS for initial test. |
| 4 | **DocuSeal requires email delivery for sign flow** | Configure Resend SMTP in DocuSeal. Konan must set up Resend account. |
| 5 | **Twilio 10DLC registration takes 1-2 weeks** | Use Twilio test credentials for Phase L7. Real SMS requires completed registration. |
| 6 | **Docker overlay2 needs ext4** — `/mnt/space` is VFAT | Keep Docker data on main drive. Move Frappe site files to external drive if space needed. |
| 7 | **Double-booking from manual calendar entries** — founder adds dentist appointment in Google Calendar, Ledger shows slot as free | **Mitigated by L8.2–L8.3**: `get_freebusy` reads live calendar + 5-min reconciliation job. Two-way E2E test (L8.5) verifies this. |
| 8 | **OAuth2 token expiration** — founder's calendar connection expires, sync silently breaks | **Mitigated by L8.3**: reconciliation job logs failures. `calendar_connection.is_token_valid()` + `refresh_token_if_needed()` already built. L8.4 adds UI for reconnection. |
| 9 | **Sync latency** — client books a slot, but reconciliation job hasn't run yet, so availability is stale | Acceptable — 5-min polling is reasonable for scheduling. No webhook infrastructure required. |

---

## 8. Phase Scope

| Phase | Tasks | Owner(s) | Size | Status |
|---|---|---|---|---|
| L1 | Build 2 Docker images | Marvin | L | ⏳ |
| L2 | .env + provision + DNS | Marvin + Konan | M | ⏳ |
| L3 | Full stack deploy | Marvin + Konan | M | ⏳ |
| L4 | Install 3 Frappe apps | Marvin | M | ⏳ |
| L5 | Vaultwarden verify | Hephaestus | S | ⏳ |
| L6 | DocuSeal verify | Hephaestus | S | ⏳ |
| L7 | Client Intake E2E | Hephaestus | S | ⏳ |
| L8 | Admin Scheduling — two-way calendar sync | Marvin (L8.2–L8.4 code) + Hephaestus (L8.1 + L8.5 verify) | M | ⏳ |
| L9 | Full acceptance sweep | Hephaestus | M | ⏳ |

---

## 9. Post-Build

When all phases ship:
1. One Ledger instance running with all 8 services healthy
2. Vaultwarden operational at `vault.{domain}`
3. DocuSeal operational at `sign.{domain}`
4. Client Intake MVP demonstrable (portal upload + email forwarding)
5. Admin Scheduling MVP demonstrable with **two-way** calendar sync (booking page + calendar push + busy reads + reconciliation)
6. `provision-firm.sh` tested and documented for per-founder replication
7. Backup + monitoring verified
8. Acceptance gate log written
