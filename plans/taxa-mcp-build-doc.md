# Taxa MCP — Tax Research as a Pluggable AI Service

## The Idea

An MCP server that gives any AI agent instant, citation-grade tax research. Ask a natural language question — get back a verdict with IRC sections, Treasury Regulations, and court cases cited inline. No web app to open. No chat interface to learn. Just a tool any agent can call.

## Why This Exists

Tax professionals currently have two choices:

1. **Legacy tools** (Checkpoint, CCH) — $2,000–5,000+/yr, accurate but slow, desktop-era UX
2. **AI chat apps** (Blue J at $195/mo, Hive at $79/mo, TaxGPT at $49–99/mo) — faster but locked inside their own web UI

Neither option lets you plug the research layer directly into your own workflow. If your firm uses Claude Code, Cursor, Hermes, or any AI agent to manage operations, you can't get a cited tax answer without leaving your terminal and opening a separate app.

**Taxa MCP fixes that.** One `npx taxa-mcp` and any agent can query the full IRC, Treasury Regulations, and Tax Court case law. No tab-switching. No separate subscription. Just a tool in the toolbox.

## Architecture

```
User's AI Agent                  Taxa MCP Server                   Tax Data
(Hermes, Claude Code,            (taxa-mcp)                        (Athenaeum)
 Cursor, Copilot, etc.)                                           
                              ┌─────────────────┐              ┌──────────────┐
  "Research §179              │ taxa_research()  │◄──────────►│  Codex-Tax-US │
   depreciation               │ taxa_cite()      │              │               │
   limits for 2026"           │ taxa_history()   │              │  • IRC        │
       │                      └────────┬────────┘              │  • CFR 26     │
       └───────────────────────────────┘                       │  • Tax Court  │
                                                                  │  • Rulings   │
                                                                  └──────────────┘
```

The server is thin — just query + citation tools. The heavy lifting (retrieval, embedding, entity relationships) is handled by the existing Ichor/Athenaeum memory system already running in Pantheon.

## Tiers

### Free — Standalone MCP (lead gen)
- **Data:** IRC (Title 26) + Treasury Regulations (26 CFR)
- **Limit:** 100 queries/month per API key
- **Tools:** `taxa_research`, `taxa_cite`
- **Access:** Public MCP endpoint, can be called by any agent
- **Price:** $0
- **Goal:** Let any firm try it. When they hit the limit, they see the value and upgrade.

### Pro — Built into Talli
- **Data:** Everything + Tax Court cases + Rev. Rulings + Rev. Procedures + Chief Counsel Advice
- **Limit:** Unlimited via Talli subscription
- **Tools:** Full set + `taxa_history` + entity graph (what-cites-what)
- **Access:** Native Talli feature + bundled MCP endpoint
- **Price:** Included in Talli ($600–1,750/mo)
- **Goal:** Make Talli the only platform with built-in, citation-grade tax research

### Enterprise — Standalone (optional)
- **Data:** Everything + state tax codes (all 50) + dedicated endpoint
- **Limit:** Unlimited
- **Price:** Custom ($199/mo or $1,999/yr)
- **Goal:** Capture firms that don't need the full Talli platform

## Market Context

| Competitor | Price | Format | Taxa MCP Advantage |
|---|---|---|---|
| Blue J | $195/mo | Web app | MCP = any agent, not just their UI |
| Hive Tax AI | $79/mo | Web app | MCP + Talli bundle crushes value |
| TaxGPT | $49–99/mo | Web app | MCP = embeddable anywhere |
| Checkpoint (TR) | $2k–5k+/yr | Web app | 90% cheaper, always updating |
| CCH AnswerConnect | ~$75k/yr site | Web app | 95% cheaper |
| **Taxa Free** | **$0** | **MCP** | **Free + MCP = no barrier to try** |
| **Taxa Pro (Talli)** | **$600–1,750/mo** | **MCP + platform** | **Research is a feature, not a line item** |

## Build Phases

### Phase 0 — Foundation (Week 1)
Goal: Get the core tax data loaded and searchable

- [ ] **Scrape the IRC** — Download Title 26 of the US Code from govinfo.gov API as XML. Parse into individual sections (§1 through §8999+). Expected: ~5,000 sections.
- [ ] **Scrape Treasury Regs (26 CFR)** — Download from eCFR.gov API as JSON/XML. Parse into individual regulation sections (1.1-1 through 899.1+). Expected: ~15,000 sections.
- [ ] **Load into Athenaeum** — Both sources go into a new codex called `Codex-Tax-US`. Each section becomes a document with its full text, citation metadata, and source tag.
- [ ] **Tune retrieval** — Ichor's FTS5 backend should be boosted for exact citation lookups (when someone asks about "§179" it should match the actual section). Vector search handles semantic queries ("what deductions are available for heavy equipment").
- [ ] **Validate** — Run 50 test queries covering common tax research questions. Verify citations are real and accurate.

**Data sources:**
| Source | URL | Format | Size |
|---|---|---|---|
| IRC Title 26 | govinfo.gov API | XML | ~5K sections |
| 26 CFR | eCFR.gov API | JSON | ~15K sections |

**Both are free, public, and have REST APIs.**

### Phase 1 — MCP Server (Week 2)
Goal: A working MCP endpoint anyone can call

- [ ] **Build the server** — Python using the MCP SDK. Thin layer on top of the existing Ichor retrieval system.
- [ ] **Implement `taxa_research(query)`** — Accepts a natural language tax question. Runs retrieval against the Athenaeum codex. Synthesizes a response with: verdict, rule, how it applies, and exact citations.
- [ ] **Implement `taxa_cite(code)`** — Exact lookup of a specific IRC section or regulation. Returns full text with metadata.
- [ ] **Implement resource URIs** — `taxa://irc/§162`, `taxa://reg/1.162-1` — standard MCP resource protocol for linking to specific sections.
- [ ] **Add rate limiting** — Free tier gets 100 queries/month. Track via API key.
- [ ] **Add API key auth** — Simple token-based access.
- [ ] **Deploy** — Containerized, hosted on relay-7 or a lightweight VPS ($10–20/mo).

### Phase 2 — Depth (Week 3)
Goal: Match or beat the data coverage of tools like Hive and Blue J

- [ ] **Load Tax Court opinions** — CourtListener API (free, non-profit). Pull all Regular and Memorandum opinions. ~20,000+ documents.
- [ ] **Load Revenue Rulings** — Scrape IRS.gov Internal Revenue Bulletins. ~3,000 rulings.
- [ ] **Load Revenue Procedures** — Same source as rulings. ~2,000 procedures.
- [ ] **Load Chief Counsel Advice** — FOIA-released, available in bulk from IRS.gov.
- [ ] **Build the entity graph** — Track which ruling cites which code section, which case overrules which, which procedure modifies which. Ichor's graph backend handles this natively. This is the seed of a citator.
- [ ] **Tune the synthesis prompt** — The response format should be: verdict → rule → application → citations. Test against 100 queries. Track citation accuracy.

### Phase 3 — Talli Integration (Week 4)
Goal: Pro tier ships as a built-in Talli feature

- [ ] **Bundle the Pro endpoint** — Every Talli subscriber gets automatic access to the full research layer.
- [ ] **Browser extension integration** — "Ask Talli about this" button that runs `taxa_research` on whatever the user is looking at.
- [ ] **Client portal integration** — When a client asks "what does this mean?" about a document in the portal, the system auto-generates an explanation.
- [ ] **Usage analytics** — Track which queries are most common. Feed back into data tuning.

## What Success Looks Like

**Week 4:** A CPA firm using Claude Code runs `opencode run "research QBI phaseout for 2026 S Corp"` and gets back:

> **Verdict:** The QBI deduction under §199A begins phasing out at $232,500 (single) / $464,950 (married filing jointly) in 2026.
>
> **Rule:** IRC §199A(b)(3) specifies the phase-in range for specified service trades or businesses (SSTBs), indexed for inflation.
>
> **Application:** For an S Corp with $500K taxable income, the SSTB phaseout eliminates the deduction entirely.
>
> **Sources:** IRC §199A(b)(3); Rev. Proc. 2025-45 (inflation adjustments).

All from one command. No web app. No tab-switching.

---

## Quick Questions for Konan

1. **Hosting** — Relay-7 VPS or a dedicated $10–20/mo cloud box?
2. **Name** — "Taxa" works, or something else?
3. **Order** — Phases 0→1→2→3 sequentially, or overlap anything?
4. **Phase 0 go** — Should I start scraping the IRC this week?
