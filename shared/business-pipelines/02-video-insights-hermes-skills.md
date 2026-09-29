# Video Notes — 10 Hermes Agent Skills

**Video:** 10 Hermes Agent Skills You NEED To Install Today
**URL:** https://youtu.be/5WQk9WiWcYQ
**Uploader:** Sharbel A.
**Length:** 13:19
**Watched:** 2026-08-16

## Core Takeaway

Skills are free to install. What costs you is burying the good ones under 40 you never use. The list changes every month — what matters is the habit of installing a few, testing them against real work, and keeping only the ones that earn their place.

> The first three skills pay for themselves the same day. Install them tonight.

## The 10 Skills (in video order)

### Cost-cutters (install first — all three)

1. **Defuddle** — strips any webpage to clean reader-mode markdown before the agent reads it. Kills nav/footer/cookie-banner/ads/newsletter-popup token waste. "Pays for itself on the first page you read."
2. **Caveman** — ultra-compressed output mode. Repo claims ~65% output-token cut. Output is the expensive side on every model AND output gets re-sent every turn, so savings compound. Same info, no preamble/recap/summary/"can I help with anything else."
3. **Codebase Memory** (MCP server, not a skill file) — indexes a repo into a graph once; agent queries the map instead of re-reading files. Claim: 99% fewer exploration tokens across 158 languages. Creator's own test: 95%.

### Ability-adders

4. **Humanizer** (29.6KB — the big one, be careful) — strips AI tells out of agent writing; scrapes the Wikipedia page on signs of AI-generated writing and auto-updates. Keep for anything published. Rule: invoke late, invoke once; long session → do the writing pass in a fresh session. (M-dash = dead giveaway.)
5. **Agent Reach** — X, Reddit, GitHub, and many social networks with zero API fees. Fixes the "agent goes blind" problem (X paid API, Reddit 403s cloud IPs). Killer feature: failover route maps when platforms change rules — agent never notices the outage.
6. **Marketing Skills** — 49 skills in one pack: SEO, paid ads, conversion, copywriting, buyer psychology. Not tools — judgment. "If you sell anything, this is the one I'd install first, before the clever infrastructure."

### Doers / Producers

7. **Composio** — connects 1,000+ tools (Gmail, Sheets, Slack, Notion, HubSpot, Salesforce) in one install. No API-key juggling, no reverse-engineered OAuth.
8. **OpenMontage** — open-source agentic video production system: 12 pipelines, 100+ tools, 700+ skill/knowledge files. Paste a video → agent reads transcript, analyzes pacing/scene/tone → returns 2-3 concepts + exact tool path + cost estimate + preview **before** generating. Negotiates before spending.

### Team / Methodology

9. **Oh My Claude Code** (`omc`) — teams-first multi-agent orchestration for Claude Code: decomposes tasks into subtasks, assigns specialist agents, parallel or staged pipelines, verifies results instead of stopping at half-done answers. Quality gate for irreversible work: shipping, migration, client proposals.
10. **Superpowers** — 260K+ stars on GitHub. Not a single skill — a skills framework with a real methodology for how work gets broken down and executed. "Closest thing to an operating system for your agent." Takes an afternoon; worth the afternoon.

## Honorable Mentions (his own)

- **Mission Control** — his Hermes Agent Fleet dashboard: task dispatch, agent health, live cost tracking, one screen.
- **Nova** — his YouTube skill: researches ideas, checks performance data, drafts video ideas. Suggested this very video; reason half the list exists (every skill tested against real work).

## Portfolio Implication For Konan

Direct tooling map for the multi-pipeline portfolio:

- **Already in our stack** (confirmed in this profile): Caveman ✓, Humanizer ✓, Marketing Skills pack ✓, Superpowers ✓, Composio automations ✓, Codebase Memory MCP ✓ (wired & live per config + logs) — the video's A-list is largely already installed.
- **Gap install log (2026-08-16):** Defuddle ✓ (`npm i -g defuddle` + skill in `devops/defuddle`, live-tested), Agent Reach ✓ (v1.5.0, `~/.agent-reach-venv`, 5/15 channels active, skill in `research/agent-reach`), OpenMontage ✓ (cloned `~/tools/OpenMontage`, AGPL-3.0 — license note for commercial use), Oh My Claude Code ✓ (`omc` 4.15.10 via `npm i -g --prefix=~/.npm-global`).
- **Defuddle** = web research cost; **Agent Reach** = social/Reddit research (feeds lead-gen + content pipelines; credential-gated channels pending Konan choice); **OpenMontage** = directly powers **Pipeline 5 — YouTube Agency Lite** (needs API keys from `.env.example`).
- **Video is itself a zero-click asset template:** a clean "install these 3 tonight" list post / short-form clip is reproducible content for the creator/newsletter lane.
- His operating note — "test every skill against real work before it makes the cut" — is the same rule as the portfolio: skills and pipelines both earn their place by producing measurable output.
