# Talli vs. LedgerOS — Feature-by-Feature Comparison

> **Style note:** This doc maps to LedgerOS's collapsible feature-tour layout — each feature is a heading with expandable detail. Copy the HTML `<details>` structure for Talli's landing page.

---

## Feature Map — Head-to-Head

### 1. 🤖 AI Document Processing

**LedgerOS:** "Drop in 40 messy uploads. Get back 40 perfectly named files." AI reads, renames, tags, flags duplicates, assembles bookmarked workpaper PDF. Saves 20+ min per engagement.

**Talli:** ✅ **Comparable — with a twist.** Talli's document pipeline routes through the Ichor/Athenaeum memory system. Uploads get auto-classified, entity-linked (client → document → engagement), and embedded into the firm's knowledge graph — not just named and filed but *connected* to everything else the firm knows about that client. The assembly step lives in an MCP tool (`talli_docs_assemble`) that any AI agent can call.

| Differentiator | LedgerOS | Talli |
|---|---|---|
| AI rename/tag/flag | ✅ | ✅ |
| Bookmarked workpaper PDF | ✅ | ✅ |
| Entity-linked knowledge graph | ❌ | ✅ |
| MCP-agent callable assembly | ❌ | ✅ |
| Cryptographic freeze on close | ✅ | ⏳ Phase 2 |

---

### 2. 📋 Pipeline & Workflow

**LedgerOS:** 5-stage Kanban + list view. Built-in templates (1040, 1065, 1120, 1120S, 990, 1041, Monthly Close, BOI). Per-location templates. AI-generated checklists. Conditional automation rules with visual rule builder.

**Talli:** ✅ **Strong match — with architectural difference.** Talli's pipeline lives in Conductor v2 (the Pantheon workflow engine), which is file-based, event-driven, and MCP-accessible. Template library can borrow from LedgerOS's list. The visual rule builder is a future-phase item.

| Differentiator | LedgerOS | Talli |
|---|---|---|
| Kanban board | ✅ | ✅ (via Pantheon kanban) |
| Tax form templates | ✅ | ⏳ Phase 1 (copy their list) |
| AI-generated checklists | ✅ | ✅ (Ichor entity graph → checklist) |
| Visual rule builder | ✅ | ⏳ Phase 2 |
| MCP-accessible workflow API | ❌ | ✅ |
| Multi-location templates | ✅ | ✅ |

---

### 3. 📄 Workpaper Assembly

**LedgerOS:** Automatic bookmarked PDF from all engagement docs. Re-flows when new docs arrive. Drill from return to workpaper in one click. Cryptographic integrity on close.

**Talli:** ✅ **Comparable core.** The assembly pipeline maps to the same concept — but Talli adds version-aware diffing (Ichor events track every change) and MCP-level access so agents can drill into workpapers programmatically.

| Differentiator | LedgerOS | Talli |
|---|---|---|
| Auto-assembled PDF | ✅ | ✅ |
| Re-flow on new docs | ✅ | ✅ |
| One-click return→workpaper drill | ✅ | ✅ |
| Cryptographic freeze | ✅ | ⏳ Phase 2 |
| Version-aware diffs | ❌ | ✅ |
| MCP-accessible drill API | ❌ | ✅ |

---

### 4. 🔍 Review & Annotation (TicTie Replacement)

**LedgerOS:** Tickmarks, auto-calculating ties with mismatch alerts, sticky notes on lines. Open review points queued for preparer. Saves $300/user/yr vs standalone TicTie.

**Talli:** ✅ **Phase 1 feature.** The annotation layer maps cleanly to Conductor handoff workflow: reviewer marks → preparer gets automated handoff with context. Tickmarks and tie-calculation are standard PDF-layer features.

| Differentiator | LedgerOS | Talli |
|---|---|---|
| Tickmarks | ✅ | ✅ |
| Auto-calculating ties | ✅ | ✅ |
| Sticky notes on lines | ✅ | ✅ |
| Review→preparer queue | ✅ | ✅ (via Conductor handoff) |
| MCP API on review points | ❌ | ✅ |
| Saves $300/user/yr | ✅ | ✅ (same math) |

---

### 5. 📚 Tax Research (TaxGPT / TheTaxBook Replacement)

**LedgerOS:** Natural language queries. Verdict + rule + client application. Cites IRC, Treasury Regs, Rev. Procs, Court cases. Saves answers into workpapers. Replaces TaxGPT + TheTaxBook at half the cost.

**Talli:** 🚀 **This is our MOONSHOT.** LedgerOS has a basic research feature. We have **Taxa MCP** — a full MCP server with Ichor/Athenaeum's entity-graph citator. Theirs is a web-UI feature. Ours is a tool *any agent can call* from *anywhere*.

| Differentiator | LedgerOS | Talli (Taxa MCP) |
|---|---|---|
| Natural-language queries | ✅ | ✅ |
| IRC + Treasury Regs | ✅ | ✅ (Free tier) |
| Rev. Rulings + Procs | ✅ | ✅ (Pro tier) |
| Tax Court cases | ✅ | ✅ (Pro tier) |
| Inline citations | ✅ | ✅ |
| Save into workpapers | ✅ | ✅ (MCP-callable) |
| **Entity graph citator** (what-cites-what) | ❌ | ✅ — **Unique moat** |
| **Any agent can call it** (Claude Code, Cursor, etc.) | ❌ | ✅ — **Unique** |
| Firm memory (remembers past research context) | ❌ | ✅ — **Unique** |
| Price | ~$99/mo bundled | **Included in Talli** ($0 marginal cost) |

---

### 6. 📬 Bulk Communications (Canopy Replacement)

**LedgerOS:** "247 emails in 4 seconds. No daily caps." White-label via Amazon SES. Real-time tracking. Replaces Canopy's 250/day throttle wall.

**Talli:** ✅ **Phase 1.** Bulk email via Composio (Gmail/SES connector). No daily cap (SES standard). The real differentiator: Talli's comms are also callable via MCP — agents can send personalized firm-wide emails programmatically.

| Differentiator | LedgerOS | Talli |
|---|---|---|
| Bulk send (no caps) | ✅ | ✅ (SES/Gmail) |
| White-label domain | ✅ | ✅ |
| Real-time tracking | ✅ | ✅ |
| Tax reminders, document requests | ✅ | ✅ |
| MCP-API for agent-driven sends | ❌ | ✅ |
| Meeting capture (auto-transcribe + entity link) | ❌ | ✅ — **Unique** |

---

### 7. 🚪 Client Portal

**LedgerOS:** 7-stage visual return status tracker. White-labeled. E-sign for 8879. Pay-to-unlock final return. Multi-location branding.

**Talli:** ✅ **Phase 1-2.** Portal maps to Pantheon's messaging/notification system + the existing gateway channel infrastructure. The status tracker feeds from the Conductor workflow state — automatically reflects real pipeline position.

| Differentiator | LedgerOS | Talli |
|---|---|---|
| Status tracker | ✅ (7-stage) | ✅ (Conductor-driven) |
| White-label portal | ✅ | ✅ |
| E-sign (8879) | ✅ | ⏳ Phase 2 |
| Pay-to-unlock | ✅ | ⏳ Phase 2 |
| Multi-office branding | ✅ | ✅ |
| Browser extension (client asks "what's this?" → AI answer) | ❌ | ✅ — **Unique** |
| Agent-driven client chat | ❌ | ✅ (via Telegram/discord gateways) |

---

### 8. 🎯 Talli Exclusives — Things LedgerOS Doesn't Have

| Feature | Why It Matters |
|---|---|
| **Taxa MCP** — research as a pluggable MCP endpoint | Any AI agent (Claude Code, Cursor, Hermes, Archon) can query. No other platform offers this. |
| **Ichor/Athenaeum firm memory** | Every decision, ruling, and client interaction becomes searchable context. The firm gets *smarter* over time. |
| **Browser extension** | Clients or staff can highlight any tax question on any website and get an instant AI-sourced answer. |
| **Meeting capture** | Auto-transcribes client meetings, links entities (e.g., "S Corp election discussed → saved to client's knowledge graph"). |
| **Password/tool management** | Credential pool for the firm's SaaS tools — one master key ring. |
| **Any-platform messaging** | Telegram, Discord, SMS, web UI — clients talk to the firm however they want. |
| **Single Ops Manager agent** | One agent runs the entire firm — research, pipeline, communications, client management. Not a multi-agent mess. |

---

## Pricing Comparison

| Plan | LedgerOS | Talli |
|---|---|---|
| **Solo** (1-3 staff) | $79-65/user/mo | **$49-39/user/mo** |
| **Firm** (3-25 staff) | $129-99/user/mo | **$99-79/user/mo** — includes Taxa MCP Pro |
| **Enterprise** (25+) | $179-149/user/mo | **$149-129/user/mo** — dedicated MCP endpoint |
| **Seasonal staff** | $399/4mo | **$299/4mo** |
| **Founding discount** | 50% off for life (100 firms) | **TBD** (match or beat) |

**The killer price comparison:**
> *8 staff + 2 seasonal = $13,182/yr on LedgerOS*
> *= **$10,302/yr on Talli** (same features + Taxa MCP + firm memory + browser extension)*

---

## The "Copy Their Layout" Section

LedgerOS uses collapsible `<details>` / `<summary>` HTML blocks for their 7 feature tours — each heading is clickable and expands to show bullet benefits. Here's the HTML pattern:

```html
<section class="feature-tours">
  <details>
    <summary>📄 Workpaper Assembly</summary>
    <div class="feature-detail">
      <p class="feature-tagline">"Drop in 40 messy uploads..."</p>
      <ul>
        <li>Automatically combines every engagement document into one</li>
        <li>Re-flows as new documents arrive</li>
        <li>Drill from return to workpaper in one click</li>
      </ul>
    </div>
  </details>
  <!-- repeat for each feature -->
</section>
```

**Recommendation for Talli's site:** Use the exact same pattern but with 10 sections (their 7 + our 3 exclusives: Taxa MCP, Firm Memory, Browser Extension). The familiarity makes the comparison feel natural — visitors recognize the format from LedgerOS.

---

## Build Priority

| Phase | Features | Time |
|---|---|---|
| **Phase 0** | Taxa MCP Free tier, Pipeline board, Document upload | Week 1-2 |
| **Phase 1** | Bulk comms, Workpaper assembly, Review/annotation, Client portal basics | Week 3-4 |
| **Phase 2** | Taxa MCP Pro, Firm memory portal, Browser extension, E-sign, Pay-to-unlock | Month 2 |
| **Phase 3** | Meeting capture, Seasonal licenses, Visual rule builder | Month 3 |
