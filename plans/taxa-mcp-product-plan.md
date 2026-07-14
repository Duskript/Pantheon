# TAXA MCP Server — Product Plan

## Elevator Pitch
An MCP server that any AI agent can query for authoritative tax research. Free tier hooks anyone. Pro tier rolls into Talli. Nobody else offers the data as an MCP endpoint.

---

## Architecture

```
                   ┌─────────────────────────┐
                   │    TAXA MCP Server       │
                   │   (taxa-mcp)             │
                   │                          │
                   │  Tools:                  │
                   │   taxa_research(query)   │
                   │   taxa_cite(code)        │
                   │   taxa_history(case)     │
                   │                          │
                   │  Resources:              │
                   │   taxa://irc/$1          │
                   │   taxa://reg/$1          │
                   └──────────┬──────────────┘
                              │
                 ┌────────────┴────────────┐
                 │                         │
          ┌──────▼──────┐          ┌───────▼───────┐
          │  Ichor Core  │          │  Tax Data     │
          │  (Pantheon)   │          │  Athenaeum    │
          │              │          │               │
          │  FTS5        │          │  Codex-Tax-US │
          │  Vector       │          │   • IRC       │
          │  Graph        │          │   • CFR 26    │
          │  Events       │          │   • Tax Court │
          └──────────────┘          │   • Rulings   │
                                    └───────────────┘
```

## Data Pipeline (P0)

| Source | Method | Size | Frequency |
|---|---|---|---|
| IRC Title 26 | govinfo.gov API → XML → chunk → embed | ~5K sections | Quarterly on codification |
| 26 CFR (Treasury Regs) | eCFR.gov API → JSON → chunk → embed | ~15K sections | Monthly |
| Tax Court (Regular) | CourtListener API → text → chunk → embed | ~8K opinions | Weekly sync |
| Tax Court (Memo) | CourtListener API → text → chunk → embed | ~15K opinions | Weekly sync |
| Rev. Rulings | IRS.gov scrape → text → chunk → embed | ~3K rulings | On IRB release |
| Rev. Procedures | IRS.gov scrape → text → chunk → embed | ~2K procs | On IRB release |

**Total initial load:** ~40K-50K documents, ~5-10GB embedded

## Tiers

### Free — `taxa-mcp` (standalone SaaS)
- **Data:** IRC + CFR 26 only
- **Rate:** 100 queries/month per API key
- **Tools:** `taxa_research`, `taxa_cite`
- **Distribution:** Public MCP endpoint, `npx taxa-mcp` optional
- **Goal:** Lead gen. Any firm/agent tries it for free, hits the limit, upgrades.

### Pro — Built into Talli
- **Data:** Everything + Rev. Rulings + Rev. Procs + Tax Court + CCA
- **Rate:** Unlimited via Talli subscription
- **Tools:** Full toolset + `taxa_history` + entity graph (what-cites-what)
- **Distribution:** Native Talli feature + bundled MCP endpoint
- **Goal:** Core Talli differentiator. No other practice management platform has this.

### Enterprise — Standalone (optional)
- **Data:** Everything + state tax codes + private MCP server
- **Rate:** Unlimited, self-hosted or dedicated endpoint
- **Price:** Custom

## Build Phases

### Phase 1 — Data Foundation (week 1)
- [ ] Scrape/load IRC Title 26 into Athenaeum as `Codex-Tax-US`
- [ ] Scrape/load 26 CFR into same codex
- [ ] Tune retrieval: FTS5 boosted for exact section cites, vector for semantic
- [ ] Validate citation accuracy on 50 test queries

### Phase 2 — MCP Server (week 2)
- [ ] Build `taxa-mcp` server (Python, MCP SDK)
- [ ] Implement `taxa_research(query)` — NL → retrieve → synthesize → cite
- [ ] Implement `taxa_cite(code)` — exact section lookup with full text
- [ ] Implement resource URIs: `taxa://irc/§162`, `taxa://reg/1.162-1`
- [ ] Add rate limiting + API key auth
- [ ] Deploy to relay-7 or VPS

### Phase 3 — Moats (week 3)
- [ ] Load Tax Court cases from CourtListener API
- [ ] Load Rev. Rulings + Rev. Procs from IRS.gov
- [ ] Build entity graph: which ruling cites/modifies/overrules which
- [ ] Tune prompt for "verdict + rule + application" format

### Phase 4 — Talli Integration (week 4)
- [ ] Bundle Pro tier into Talli's subscription
- [ ] Ship MCP endpoint that Talli users get automatically
- [ ] Expose via Talli browser extension ("Ask Talli about this deduction")
- [ ] Client portal: auto-answer "What does this mean?" on client docs

## Business Model

```
Free tier:    100 queries/mo   →  lead gen
Pro (Talli):  unlimited        →  $600-1,750/mo (bundled)
Enterprise:   unlimited + sso   →  custom
```

The free tier is a product in its own right. Someone running Claude Code, Cursor, or Hermes does `taxa_research("QBI phaseout 2026 S Corp")` and gets a cited answer. That's immediately valuable. When they hit 100 queries, they have two options: upgrade to Pro (which comes with Talli) or buy standalone Enterprise access.

## Why This Wins

1. **Nobody offers tax research as an MCP endpoint** — every competitor is a web app.
2. **Ichor's existing architecture handles this** — multi-backend, entity graph, fused scoring. We're not building from scratch.
3. **Talli becomes the only platform with this built in** — that's the differentiator LedgerOS can't touch.
4. **The free tier is distribution** — every agent user who tries it is a potential Talli customer.
