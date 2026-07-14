---
name: taxa-mcp
description: Build the Taxa MCP server — citation-grade US tax research as a pluggable AI service. Thin Python MCP server over the existing Ichor/Athenaeum memory system. Loads IRC, 26 CFR, Tax Court opinions, and IRS guidance. Exposes taxa_research, taxa_cite, taxa_history tools. Phased build, see Phases below.
triggers:
  - "build taxa"
  - "tax research MCP"
  - "taxa_research"
  - "talli tax"
---

# Taxa MCP — Build Plan (from 2026-07-02 spec)

## The Product

**One line:** An MCP server that gives any AI agent instant, citation-grade US tax research. Query → verdict + IRC sections + Regs + court cases inline. No web app, no tab-switching. Just a tool any agent can call.

**Why it wins:**
- $0 free tier, 100 queries/month, IRC + 26 CFR
- Pro tier bundled into Talli ($600-1,750/mo) — unlimited, includes Tax Court + Rev Rulings + Rev Procs + CCA
- Enterprise: state tax codes (all 50), $199/mo or $1,999/yr

**Competitor crush:**
- Blue J $195/mo, Hive $79/mo, TaxGPT $49-99/mo → all web apps, no MCP
- Checkpoint $2-5k/yr, CCH ~$75k/yr/site → 90-95% cheaper, always updating

## Architecture (from spec)

```
User's AI Agent              Taxa MCP Server                Tax Data (Athenaeum)
(Hermes, Claude Code,        (taxa-mcp Python pkg)
 Cursor, Copilot)
                          ┌─────────────────┐           ┌──────────────┐
 "Research §179            │ taxa_research() │◄────────►│ Codex-Tax-US │
  depreciation             │ taxa_cite()     │           │              │
  limits for 2026"         │ taxa_history()  │           │  • IRC       │
                          └────────┬────────┘           │  • 26 CFR    │
                                   │                    │  • Tax Court │
                                   │                    │  • Rulings   │
                                   │                    └──────────────┘
```

Thin server. Heavy lifting already runs in Ichor/Athenaeum (FTS5 + vector + graph).

## Phase 0 — Foundation (THIS WEEK)

**Goal:** Core tax data loaded and searchable.

### 0.1 — Scrape the IRC (Title 26 of US Code)
- Source: govinfo.gov API (public, free)
- Format: XML
- Expected: ~5,000 sections
- Action: download, parse into §1 through §8999+, store as individual docs

### 0.2 — Scrape 26 CFR (Treasury Regulations)
- Source: eCFR.gov API (public, free, JSON)
- Expected: ~15,000 sections
- Action: download, parse into 1.1-1 through 899.1+

### 0.3 — Load into new Athenaeum codex: `Codex-Tax-US`
- Each section = one document
- Metadata: section number, parent title, source URL, last-updated, citation form
- Sources properly attributed

### 0.4 — Tune retrieval
- FTS5 boost on exact citations (when query has "§179" or "1.162-1", match the section)
- Vector search handles semantic queries ("deductions for heavy equipment")
- Test with 50 known queries, verify citations real

**Sources (both free + public + REST):**
| Source | URL | Format | Size |
|---|---|---|---|
| IRC Title 26 | govinfo.gov API | XML | ~5K sections |
| 26 CFR | eCFR.gov API | JSON | ~15K sections |

## Phase 1 — MCP Server (WEEK 2)

**Goal:** Working MCP endpoint, callable by any agent.

- Python using MCP SDK
- Thin layer on Ichor retrieval
- Tools:
  - `taxa_research(query: str)` — natural language, returns verdict + rule + application + citations
  - `taxa_cite(code: str)` — exact lookup, e.g. `taxa_cite("§199A")` or `taxa_cite("1.162-1")`
- Resource URIs: `taxa://irc/§162`, `taxa://reg/1.162-1` (standard MCP resource protocol)
- Rate limiting: 100 queries/month on free tier
- API key auth (token-based, simple)
- Containerized deploy: relay-7 or $10-20/mo VPS

## Phase 2 — Depth (WEEK 3)

**Goal:** Match Hive/Blue J coverage.

- Tax Court opinions (CourtListener API, free) — ~20K docs
- Rev. Rulings (IRS Internal Revenue Bulletins) — ~3K
- Rev. Procedures — ~2K
- Chief Counsel Advice (FOIA-released, bulk)
- Entity graph: track which ruling cites which section, which case overrules which, which procedure modifies which. Ichor graph backend handles this. **This is the seed of a citator — the differentiator that no AI tax tool has.**
- Tune synthesis prompt: verdict → rule → application → citations
- Test 100 queries, track citation accuracy

## Phase 3 — Talli Integration (WEEK 4)

**Goal:** Pro tier ships as built-in Talli feature.

- Bundle Pro endpoint into every Talli subscription
- Browser extension: "Ask Talli about this" → runs `taxa_research` on current page
- Client portal: "what does this mean?" auto-explanation
- Usage analytics: which queries are most common, feed back into data tuning

## Definition of Done (Week 4)

A CPA using Claude Code runs:
```
opencode run "research QBI phaseout for 2026 S Corp"
```
Gets back:
> **Verdict:** The QBI deduction under §199A begins phasing out at $232,500 (single) / $464,950 (married filing jointly) in 2026.
>
> **Rule:** IRC §199A(b)(3) specifies the phase-in range for specified service trades or businesses (SSTB), indexed for inflation.
>
> **Application:** For an S Corp with $500K taxable income, the SSTB phaseout eliminates the deduction entirely.
>
> **Sources:** IRC §199A(b)(3); Rev. Proc. 2025-45 (inflation adjustments).

All from one command. No web app. No tab-switching.

## Open Questions (from spec)

1. Hosting — relay-7 VPS or $10-20/mo cloud box?
2. Name — "Taxa" or something else?
3. Order — phases 0→1→2→3 sequential, or overlap?
4. Phase 0 go — start scraping IRC this week?

## Build Repository

- `~/pantheon/taxa-mcp/` — Python package, MCP server entry point
- `~/athenaeum/Codex-Tax-US/` — tax data codex
- `~/pantheon/taxa-mcp/tests/` — test corpus (50-100 known queries)

## Dependencies (already in Pantheon)

- ✅ Ichor (FTS5 + vector + graph) — retrieval backbone
- ✅ Athenaeum filesystem — codex storage
- ✅ MCP SDK — server framework
- ✅ Hermes image pipeline — if we need section diagrams later
- ✅ Composio (some integrations, not blocking)
- ⏳ Talli platform — Phase 3 dependency, not blocking Phase 0
