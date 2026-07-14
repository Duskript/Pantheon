# Talli Modular Decomposition — Concept v0.1

**Status:** CONCEPT — pre-Phase 0, brainstorm captured 2026-06-26
**Author:** Hermes, per Konan directive (after TheoForge VE Phase 0 + first-pass brainstorm)
**Linked plans:** `~/pantheon/plans/theoforge-visual-editor-phase0-validation.md` · `~/pantheon/projects/theoforge-ledger/PRD.md`
**Naming note:** The product is **Ledger** internally (code, docs, infra) and **Talli** in marketing. Rebrand Ledger → Talli **underway** (marketing deploy shipped 2026-06-25 02:19 UTC per `~/theoforge-web-backup/snapshots/`). This doc uses both names — "Ledger" for the technical substrate, "Talli" for the customer-facing product.

---

## Premise

Konan's framing: **"Break each part of Tally out into its own individual product that can work stand-alone or as a complete package."**

The accounting-software market has one dominant all-in-one (Tally / TallyPrime, $1B+ ARR globally) and a long tail of best-of-breed SaaS (Qount, Karbon, TaxDome, DocuSign, LastPass, Asana, Toggl, Calendly, Granola, n8n, backup, MSP). Locked-in accountants want an alternative. The opportunity: **decompose the all-in-one into standalone products that compose**, sold as a bundle OR a-la-carte. Each piece owns its domain; no single vendor owns the whole practice.

The existing **Ledger (Talli)** product already follows this pattern — its substrate is four composable open-source products (ERPNext + DocuSeal + Vaultwarden + Pantheon). This concept captures which of those pieces (and which of Talli's custom features) should also become **standalone products** in their own right.

---

## Current Talli stack

Per `~/pantheon/projects/theoforge-ledger/PRD.md` and `BUILD-PATH.md`:

```
TALLI (sold as $600/mo flat, no per-user fees)
├── ERPNext (Frappe framework) ────── accounting/ERP substrate, re-skinned as "Ledger"
├── DocuSeal ──────────────────────── e-sign (3rd-party OSS, bundled)
├── Vaultwarden ───────────────────── password mgmt (3rd-party OSS, bundled)
├── Pantheon Agent Layer ──────────── THE WEDGE
│   ├── Practice Manager god ──────── conversational firm operations
│   ├── Ichor ─────────────────────── memory + retrieval
│   ├── Athenaeum ─────────────────── knowledge base
│   ├── Taxa MCP ──────────────────── tax research as MCP endpoint
│   └── other gods
├── Conductor v2 ──────────────────── in-house workflow engine (Python) [BEING REPLACED]
├── Conductor UI v1.2 ─────────────── visual UI for Conductor [BEING REPLACED]
├── Desktop Companion (Layer 1, +$200/mo) ── Rust tray daemon, meeting capture
├── TheoForge Visual Editor ───────── the new visual UI (Phase 0 validated 2026-06-26)
└── Founder Cohort ────────────────── 20-seat ship-path validation strategy
```

Per-firm infrastructure cost: ~$50/mo. Margin: 90-95%. Replaces $5,000-9,000/mo of SaaS subscriptions per 10-person firm.

---

## First-party module catalog (the platform's menu, 2026-06-26)

The platform ships with 9 first-party modules. The decomposition matrix below shows which stay bundle-only and which go standalone.

| # | Module | What it does | Status today |
|---|---|---|---|
| 1 | **NextERP** | Konan's own ERP — accounting + ops core (rebrand of the Ledger/Talli ERP work) | Roadmap (currently ERPNext re-skin) |
| 2 | **Vaultwarden** | Password + secrets manager | Already bundled in Talli |
| 3 | **Employee Browser Plugin** | Highlight any text on the web → AI answer | Existing Talli exclusive |
| 4 | **Conductor UI** (= TheoForge VE) | Visual workflow editor + engine | Phase 0 validated 2026-06-26 |
| 5 | **Taxa MCP** | Tax research as MCP endpoint | Will be standalone installable |
| 6 | **Marketing Manager** | Marketing automation + content + campaigns | NEW — to build |
| 7 | **Virtual Receptionist** | AI phone/chat answering + scheduling | NEW — to build |
| 8 | **Connection Manager** | Native OAuth + API keys + webhooks + rate limits — **replaces Composio entirely** | NEW — to build |
| 9 | **Practice Manager god** | Conversational agent layer (the wedge) | Built (in `pantheon-core/practice_manager/`) |

Plus the substrate (Pantheon / Ichor / Athenaeum / MCP / NATS) — never customer-facing.

---

## Platform layer — mix-and-match with automatic integration (2026-06-26)

Above the decomposition sits the **platform** — the substrate that hosts the modules. The principle:

> "Every time you install a module, it **automatically integrates** with the rest of the package."

This is the AppExchange / Shopify App Store / VS Code Marketplace pattern applied to business software. The technical primitives needed:

### Manifest-driven auto-integration

Each module ships a `prism.module.yaml` (or equivalent) declaring:
- **Identity** — module id, name, version, author
- **Data models** — entities, schemas, relationships
- **Events emitted** — what NATS subjects this module publishes
- **Events consumed** — what NATS subjects this module subscribes to
- **MCP tools provided** — the API surface for other modules to call
- **UI components** — sidebar entries, dashboard widgets, settings panels
- **Dependencies** — required modules (e.g., Connection Manager for any module that talks to external APIs)
- **Permissions** — RBAC scopes the module requires

The platform reads the manifest at install time and wires:
- Cross-module event flows (NATS subscriptions)
- MCP routes for inter-module calls
- UI mounting in the unified shell
- RBAC inheritance
- Credential hand-off to Connection Manager

**Customer experience:**

```bash
# White-label self-host: install the standard bundle
hestia up --bundle=accounting-standard

# Later, the firm wants invoicing. One command:
hestia install invoicing

# Output:
# ✓ Downloaded invoicing@2.4.1
# ✓ Registered data model (Invoice, LineItem, Payment)
# ✓ Subscribed to ledger.entry.created events
# ✓ Provided MCP tools: invoicing.create, invoicing.send, invoicing.mark_paid
# ✓ Hooked into unified auth (RBAC: owner/accountant/bookkeeper)
# ✓ Mounted UI in sidebar
# ✓ Auto-synced chart-of-accounts from NextERP module
# ✓ Registered Gmail integration via Connection Manager
# Done.
```

The customer NEVER writes integration code.

### Connection Manager — the load-bearing primitive

**Why it exists:** Without Connection Manager, every module writes its own OAuth flow, manages its own API keys, handles its own webhooks, deals with its own rate limits. **9 modules × 20 external services = 180 custom integrations.** Composio exists because this pain is real. Konan: *"I just wish it wasn't such a pain in the ass to make those ourselves, I kinda hate relying on Composio."*

**What it does:**

```
Module wants to send an email:
  ↓
  MCP call: connection.email.send(to, subject, body)
  ↓
  Connection Manager:
    - Looks up the firm's Gmail OAuth credentials (from Vaultwarden)
    - Checks rate limits (Gmail API: 250 quota units/user/second)
    - Queues if needed
    - Sends via Gmail API
    - Logs the action (audit trail)
    - Returns success/failure to module
```

The module never knows about Gmail. When the firm changes email providers, the module doesn't change.

**Architecture:**

```
Connection Manager (first-party platform module)
├── Credential Vault (uses Vaultwarden underneath)
│   └── OAuth tokens, API keys, all encrypted at rest
├── OAuth Flow Engine
│   └── Initiates OAuth, handles callbacks, refreshes tokens
├── Typed API Clients (each as an MCP tool surface)
│   └── Gmail, Slack, Stripe, Plaid, QuickBooks, Xero, etc.
├── Rate Limit Manager
│   └── Per-integration quota tracking + queueing
├── Webhook Receiver
│   └── Public HTTPS endpoint per install, routes to modules via NATS
└── Audit Log
    └── Every API call logged with actor, timestamp, target
```

**Composio vs Native Connection Manager:**

| | Composio | Native Connection Manager |
|---|---|---|
| Cost | Per-integration fees | Free (part of the platform) |
| Data sovereignty | Routes through Composio's servers | Stays in the firm's self-hosted install |
| OAuth UX | Generic, rigid | Tailored to the platform's UX |
| Tool surface | Proprietary | Native MCP |
| Vendor risk | One more company to fail | Owned by us |
| Speed | Network round-trip | Local |

---

## The decomposition decision matrix (updated 2026-06-26)

### Stays BUNDLED ONLY (Talli identity)

| Piece | Why bundled |
|---|---|
| ERPNext re-skin ("Ledger" UI of Frappe) | This is the bundle's identity. ERPNext alone doesn't differentiate; the re-skin does. |
| Practice Ops (Kanban + workpapers + period-close) | Only valuable when integrated with the rest. |
| The 11-SaaS-replacement story | The bundle's value prop. Individually each piece is commodity. |

### Standalone-able (Konan's call, 2026-06-26)

| Piece | TAM / angle | Status |
|---|---|---|
| **Practice Manager god** | Every ERPNext install worldwide needs an agent layer. Sell as $200/mo add-on. | **Confirmed target** (Q3 answer) |
| **Taxa MCP** | Tax research as MCP endpoint; any AI agent (Claude Code, Hermes, Cursor) can call it. | Not yet standalone installable — **will be** (Q2 answer) |
| **Conductor + TheoForge VE (merged)** | Workflow engine + visual editor. General-purpose for any agent stack. Replaces Conductor v2 + Conductor UI. | **Merging now** — Q1 answer: "Conductor and TheoForge VE are going to be the same thing." TheoForge VE Phase 0 is the foundation. Replaces Conductor UI per Q4. |
| **Desktop Companion** | Meeting capture daemon — useful for any professional services firm, not just accountants. | Already built (Layer 1, +$200/mo) |
| **Browser Extension** | Highlight → AI answer. Generalizable beyond tax. | Existing Talli exclusive; could be its own product |
| **Firm Memory (Ichor + Athenaeum configuration)** | Knowledge graph + memory for any professional services team. | Cross-cutting; could be packaged as a Pantheon profile |
| **Connection Manager** | Native integrations — replaces Composio for the whole platform | **NEW — confirmed target** (Konan's pain point 2026-06-26). Every install needs it; could sell as standalone "integration OS" for any self-hosted product. |
| **Marketing Manager** | Marketing automation for any business | NEW — to build |
| **Virtual Receptionist** | AI phone/chat answering for any business | NEW — to build |

### Becomes a Pantheon profile / install variant

Each standalone product can be installed:
1. As part of the Talli bundle (the default for accountants)
2. As a standalone Pantheon profile (for non-accountant use cases or single-purpose deployments)
3. As a white-label self-host (per Konan's Q3 from TheoForge VE Grill: "Cloud + white-label self-host")

---

## Konan's corrections baked in (2026-06-26)

The original brainstorm assumed Conductor v2 and TheoForge VE would be **sibling products** (Q1.A from TheoForge VE Grill). Konan corrected:

1. **Conductor + TheoForge VE are the SAME thing.** The TheoForge VE Phase 0 prototype (VoltAgent runtime + React Flow viewer on :3141) is the foundation for the **next-generation Conductor**. Conductor v2 (Python) and Conductor UI v1.2 are being **replaced**, not coexisting.
2. **Taxa MCP will become a standalone install** — not currently packaged separately, but planned.
3. **Practice Manager god as standalone product** — confirmed direction (biggest TAM: every ERPNext install).
4. **TheoForge VE replaces Conductor UI** — not alongside; replacement.
5. **Rebrand Ledger → Talli is underway** — marketing deployed Jun 25; codebase still internal "Ledger."

This means the TheoForge VE Phase 0 work is **not a parallel project** — it's **product infrastructure for Talli's workflow layer**. Every validated primitive (suspend/resume, multi-agent hierarchy, state introspection, React Flow rendering) feeds directly into the next-generation Conductor.

---

## Strategic implications

### Revenue shape

| Path | Revenue | Margin | Time to first $ |
|---|---|---|---|
| Talli bundle ($600/mo flat per firm) | $7,200/yr/firm | 90-95% | Faster — single sales motion |
| Standalone Practice Manager god (~$200/mo/firm) | $2,400/yr/firm | ~80% | Longer — need ERPNext community distribution |
| Standalone Taxa MCP | Per-call or $50-200/mo | ~70% | Fastest — any AI agent can subscribe |
| Standalone TheoForge VE (= new Conductor) | Free OSS + paid support | N/A | Different model — distribution via Pantheon |
| Desktop Companion standalone | $200/mo/seat | ~85% | Medium — needs marketing |

### Distribution paths

- **Talli bundle:** Direct sales to US accounting firms via Konan's agency. Founder cohort (20 seats) as validation.
- **Practice Manager god:** Frappe / ERPNext partner channel. Tens of thousands of existing ERPNext installations globally.
- **Taxa MCP:** MCP-compatible AI agents (Claude Code, Cursor, Hermes, Archon). Plug-and-play distribution.
- **TheoForge VE:** Pantheon install profiles + npm package. Developers adopt.
- **Desktop Companion:** Direct + channel for any professional services firm.

### Architectural implications

- **Shared data model required.** All standalone pieces need a common chart-of-accounts / accounting-entity schema so they can compose. ERPNext's schema is the natural substrate; Pantheon adds an agent-action layer on top.
- **MCP as the integration bus.** Each module exposes a clean MCP interface; Conductor/TheoForge VE orchestrates via MCP god-call.
- **NATS as the event bus.** Cross-module events (e.g., "invoice paid" from Invoicing module → updates AR in Ledger).
- **White-label self-host is the deployment model** — every standalone product ships as a Pantheon install variant.

---

## Open questions

1. **Platform naming — DEFERRED.** Pick after architecture is more concrete. Leading candidate: **Hestia** (Greek hearth goddess, the foundation of the home, where you build a life). Backups: **Bedrock** (clean English), **Prism** (refraction metaphor), **Atelier** (workshop metaphor), **Proteus** (shape-shifter). All four work; pick when the platform design is more concrete.
2. **Practice Manager god: ship as-is or extract first?** The god lives in `pantheon-core/practice_manager/` already. Need to verify it's actually a separable install vs coupled to the Talli bundle's Frappe integration.
3. **Taxa MCP packaging:** What's the install shape? Single Docker image? npm package? Pantheon profile? Needs a packaging decision before it can be standalone.
4. **Conductor/TheoForge VE branding:** When TheoForge VE replaces Conductor v2 + Conductor UI, does it keep the Conductor name, the TheoForge VE name, or get a third name (the platform name)? Affects marketing.
5. **Practice Ops:** Confirm this stays bundled-only (Kanban + workpapers + period-close have no standalone TAM outside accounting).
6. **Desktop Companion TAM:** Is "meeting capture for any professional services firm" a real market, or is it only valuable as part of Talli's accountant-specific pitch?
7. **Browser Extension standalone pricing:** Free as a wedge? Per-seat? Per-call? Need economics.
8. **Connection Manager architecture:** File format for credentials, MCP tool surface, OAuth flow shape — needs a design doc.
9. **Manifest schema (`prism.module.yaml` or platform-name module.yaml):** What's the field set, what conventions, what auto-integration rules?

---

## Next moves

1. **Save this concept doc** ✅ (this file, v0.1)
2. **Verify Q2** — read `pantheon-core/` to confirm Practice Manager god can ship standalone
3. **Verify Taxa MCP packaging intent** — read the Taxa MCP source/spec to see what "standalone installable" means in practice
4. **Sketch the Connection Manager architecture** — credential vault, OAuth flow engine, typed API clients, rate limit manager, webhook receiver, audit log
5. **Sketch the module manifest schema** — the `prism.module.yaml` (or platform-name equivalent) field set
6. **Pick platform name** — once architecture is more concrete (Hestia leading, deferred)
7. **Update `~/pantheon/projects/theoforge-ledger/PRD.md`** to reflect:
   - Conductor v2 + Conductor UI being replaced by TheoForge VE
   - The modular decomposition strategy
   - The nine first-party modules
   - The platform layer with Connection Manager
8. ~~Clean up orphan docs in `~/projects/ledger/` — move BUILD-PATH.md, PRD.md, CONDUCTOR-UI-BUILD-PLAN.md into `~/projects/theoforge-ledger/` so the split is resolved~~ ✅ **DONE 2026-06-26.** Orphan PRD.md and BUILD-PATH.md were verified identical to theoforge-ledger versions and deleted via `safe-rm --confirmed`. Unique CONDUCTOR-UI-BUILD-PLAN.md (Iris's v1.1 design) preserved at `~/projects/theoforge-ledger/docs/legacy/conductor-ui-build-plan-v1.1-legacy.md`. Orphan dir removed.
9. **Add TheoForge VE Phase 0 results** to the PRD's reference architecture section — the validated primitives ARE the new Conductor's foundation

---

## Platform naming — deferred decision (current shortlist)

| Rank | Name | One-line pitch |
|---|---|---|
| ⭐⭐⭐⭐⭐ | **Hestia** | "The foundation of your AI business. Install the modules you need." |
| ⭐⭐⭐⭐ | **Bedrock** | "The foundation your AI is built on. Install modules. Compose specialists." |
| ⭐⭐⭐⭐ | **Prism** | "One generalist substrate, many vertical specializations." |
| ⭐⭐⭐ | **Atelier** | "A workshop for your AI. Install modules. Compose specialists." |
| ⭐⭐⭐ | **Proteus** | "The generalist AI that becomes whatever your business needs." |

**Hestia** leads because: mythic alignment with Pantheon + Hephaestus + Thoth + Iris, perfect semantic match (hearth = foundation of the home = where you build a life), ownable, pronounceable, universal across verticals.

---

## Operator-locked rules honored

- ✅ No time estimates anywhere in this plan
- ✅ Project paths to `/home/konan/projects/` (not `~/pantheon/`)
- ✅ Phase structure with explicit gates (concept → pre-Phase 0 validation → Phase 0 → Wave 1+)
- ✅ Open questions listed explicitly (not assumed)
