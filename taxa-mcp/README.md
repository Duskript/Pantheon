# taxa-mcp

**Citation-grade US tax research as a pluggable AI service.**

An MCP (Model Context Protocol) server that gives any AI agent — Hermes, Claude Code, Cursor, Copilot, any MCP-compatible client — instant access to US tax law: IRC, Treasury Regulations, Tax Court opinions, and IRS guidance. Natural language query → verdict + rule + application + inline citations. No web app. No tab-switching.

## Status

**Phase 0 — Foundation** (in progress)

- [x] **0.1** Pull IRC Title 26 XML (US House Office of Law Revision Counsel)
- [x] **0.2** Pull 26 CFR XML (eCFR.gov public API, 2026-06-30 issue)
- [ ] **0.3** Parse IRC into ~5,000 sections
- [ ] **0.4** Parse 26 CFR into ~15,000 sections
- [ ] **0.5** Load into `Codex-Tax-US` (new Athenaeum codex)
- [ ] **0.6** Tune Ichor retrieval (FTS5 boost on exact citations)
- [ ] **0.7** Validate with 50 known test queries

**Phase 1 — MCP Server**

- [ ] Build Python MCP server entry point
- [ ] Implement `taxa_research(query)` tool
- [ ] Implement `taxa_cite(code)` tool
- [ ] Implement resource URIs (`taxa://irc/§162`, `taxa://reg/1.162-1`)
- [ ] API key auth + 100 query/month rate limit
- [ ] Containerize + deploy

**Phase 2 — Depth** (uses CourtListener's existing MCP for Tax Court opinions)

- [ ] Tax Court opinions (CourtListener MCP)
- [ ] Rev. Rulings, Rev. Procedures, Chief Counsel Advice
- [ ] Entity graph: citator (which case cites which code section, which overrules which)
- [ ] Tune synthesis prompt with 100 query test set

**Phase 3 — Talli Integration**

- [ ] Bundle Pro tier into Talli subscription
- [ ] Browser extension: "Ask Talli about this"
- [ ] Client portal integration
- [ ] Usage analytics

## Tiers

| Tier | Data | Limit | Price | Distribution |
|---|---|---|---|---|
| Free | IRC + 26 CFR | 100 q/mo per key | $0 | Public MCP endpoint |
| Pro (Talli) | + Tax Court + Rev Rulings/Procs + CCA | Unlimited | included in Talli ($600-1,750/mo) | Talli-native + MCP |
| Enterprise | + all 50 state codes | Unlimited | $199/mo or $1,999/yr | Dedicated endpoint |

## Install (later)

```bash
npx taxa-mcp
# or
pip install taxa-mcp
```

## Use (later)

From any MCP-compatible client:

```
mcp__taxa__research("QBI deduction phaseout for 2026 S Corp")
mcp__taxa__cite("§199A")
mcp__taxa__cite("1.162-1")
```

From CLI:

```bash
taxa "research QBI phaseout for 2026 S Corp"
taxa --cite "§199A"
```

## License

TBD. Default: server code AGPL-3.0, data public domain (it's US government work).

## Repo layout

```
taxa-mcp/
├── taxa_mcp/           # Python package
│   ├── __init__.py
│   ├── server.py       # MCP server entry point
│   ├── research.py     # taxa_research tool
│   ├── cite.py         # taxa_cite tool
│   ├── history.py      # taxa_history tool (Phase 2)
│   ├── ingest/         # Phase 0 — parse + load
│   │   ├── irc.py
│   │   ├── cfr.py
│   │   └── codex.py
│   └── retrieval.py    # Ichor integration
├── data/               # Raw downloads (gitignored)
├── tests/              # Test corpus
└── scripts/            # One-off scripts
```
