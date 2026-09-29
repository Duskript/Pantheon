# Consignment AI Supercharge Setup

**Date:** 2026-08-09  
**Status:** Proposed setup blueprint  
**Owner:** Hermes / Konan  
**Thread:** Consignment AI Supercharge  

## Source Context

This blueprint maps Patrick Dang's video **"10 Claude AI Side Hustles That Can Pay A Full-Time Income (Ranked List)"** into Konan's current consignment business and TheoForge/Pantheon workflow stack.

Existing related decision:

- `~/pantheon/shared/decisions/consignment-research-pipeline-2026-07-16.md`
- Full spec: `~/athenaeum/Codex-Forge/specs/consignment-research-pipeline-contract.md`

Existing research/listing pipeline contract:

1. Identify
2. Gather comps
3. Normalize & filter
4. Price recommendation
5. Draft listing
6. Humanize for Facebook only

## Strategic Frame

The consignment business should be treated as the dogfood wedge for **AI-assisted revenue operations**, not just a local resale side hustle.

Core offer framing:

> We help households and small businesses turn unused inventory into cash without them managing pricing, listings, buyer messages, approvals, or payouts.

Internal product framing:

> AI-assisted resale operations: intake → pricing → listing → approval → publishing → buyer follow-up → payout.

## Business Suggestions Setup Map

| # | Video suggestion | Consignment/TheoForge adaptation | Setup priority | Why |
|---|---|---|---|---|
| 1 | AI Ads for Meta | Meta ad creative generator for local consignment intake: "Have stuff sitting around? We'll sell it for you." | Later | Useful after offer is proven; not first bottleneck. |
| 2 | AI Ghostwriting | Founder/local trust content for Facebook, LinkedIn, neighborhood groups, and short posts about sold items, transformations, tips. | Medium | Builds credibility and inbound demand. |
| 3 | AI Creator | Build a visible resale/decluttering/operator brand around real before/after item stories. | Medium | Slow-burn audience, but creates proof. |
| 4 | Growth Operator | Operate the full resale funnel for clients: intake, pricing, listing, buyer comms, sale, payout. | High | This is the real business. |
| 5 | YouTube Agency | Not a primary service; use video only for internal case studies and trust-building shorts. | Low | Heavy ops; weak near-term cash. |
| 6 | Content Distribution / Second Channel | Turn sold-item stories, intake lessons, and pricing wins into posts, shorts, listing examples, and local trust content. | Medium | Supports acquisition without creating net-new content every time. |
| 7 | AI SEO / GEO / AEO | Local landing pages and answer-engine pages: "consignment in Boise", "sell estate items", "Facebook Marketplace selling help". | Medium/High | Important for inbound local discovery. |
| 8 | AI Lead Generation | Find local people/businesses with inventory signals: moving sales, estate cleanouts, stale listings, garage-sale posts, local groups. | High | Directly feeds supply of items. |
| 9 | AI DM Setting / Inbound Sales | Scripted/manual-approved outreach to people with stale or overloaded listings; qualify item value and book intake. | High | Highest near-term revenue path if done carefully. |
| 10 | Email Monetization + Retention | Client lifecycle messages: approval reminders, price-drop approvals, sale updates, payout notifications, "have more items?" follow-up. | High | Prevents revenue leaks and repeat-client loss. |

## Recommended Setup Tracks

### Track A — Consignment Revenue Ops Core

Purpose: turn items into cash reliably.

MVP surfaces:

1. **Item Intake**
   - item photos
   - owner/client
   - condition
   - category
   - minimum acceptable price
   - pickup/storage status

2. **Research + Pricing**
   - eBay sold comps
   - eBay active comps
   - price guides where applicable
   - confidence label
   - recommended FB price
   - recommended eBay price

3. **Listing Drafts**
   - Facebook Marketplace conversational listing
   - eBay SEO/factual listing
   - title variants
   - defect disclosures
   - platform-specific price

4. **Approval Gate**
   - client/admin approval required before publish
   - approval history
   - price-change approval
   - copy-change approval

5. **Publishing Queue**
   - approved listing ready for phone-assisted publishing
   - platform selected
   - post result URL / external ID saved
   - errors tracked

6. **Buyer Message / Offer Tracker**
   - inbound inquiry state
   - suggested reply draft
   - offer amount
   - accept/counter/reject state
   - meetup/shipping state

7. **Sale + Payout Ledger**
   - sold amount
   - marketplace fees
   - shipping/materials
   - commission
   - client payout
   - payout status

### Track B — Lead Generation / Supply Acquisition

Purpose: find people with items before they become competitors or dead listings.

Target segments:

1. Households downsizing or moving
2. Estate cleanouts
3. People with stale Facebook Marketplace listings
4. Small businesses with unused inventory/equipment
5. Storage/garage overload signals
6. Local collectors liquidating categories

Candidate signals:

- "moving sale"
- "estate sale"
- "downsizing"
- "must go"
- "need gone"
- many stale marketplace posts from the same seller
- local group posts asking "where can I sell..."
- businesses closing, relocating, or remodeling

Output object: **Lead**

Lead fields:

- source platform
- source URL
- person/business name if public
- item/category signal
- estimated resale value band
- urgency signal
- location
- allowed contact channel
- outreach status
- compliance/source lineage date

Guardrails:

- No bulk scraping protected platforms.
- No CAPTCHA/login-wall bypass.
- Use public business/contact channels or user-controlled accounts only.
- Human approval before outbound messages.
- Keep source URL/date for every contact.

### Track C — DM / Intake Booking

Purpose: convert supply leads into intake appointments.

Initial workflow:

1. Lead discovered
2. AI drafts short helpful message
3. Human reviews/approves
4. Message sent manually or via approved platform path
5. Reply classified: interested / maybe / no / wrong fit
6. Intake booked or follow-up scheduled

Message angle:

> "If you're tired of dealing with messages/no-shows, I can handle pricing, listing, buyer replies, and payout. You only approve the price/listing before anything goes live."

### Track D — Trust Content Engine

Purpose: make the business feel real and safe.

Content types:

- before/after item stories
- "what sold this week"
- pricing lessons
- scams/no-show buyer tips
- decluttering tips
- estate-sale/liquidation explainers
- client payout screenshots with private info removed
- short videos of item intake/listing process

Repurpose each item sale into:

1. Facebook post
2. short-form video script
3. local group educational post
4. website/case-study snippet
5. email/SMS update for past clients

### Track E — Local SEO / Answer Engine

Purpose: be findable when people need help selling items.

Initial pages/posts:

- `/consignment-boise`
- `/sell-used-furniture-boise`
- `/estate-item-consignment-boise`
- `/facebook-marketplace-selling-help`
- `/how-consignment-payouts-work`
- `/what-items-are-worth-selling`

Answer-engine prompts to target:

- "Who can sell my stuff for me near Boise?"
- "Best way to sell estate items locally"
- "How do consignment payouts work?"
- "Should I sell on Facebook Marketplace or eBay?"

### Track F — Client Retention / Revenue Leak Automation

Purpose: prevent slow approvals, forgotten payouts, and one-time clients.

Automations:

- approval reminder after 24h/72h
- price-drop recommendation after stale period
- buyer-offer urgent alert
- sale notification
- payout-ready notification
- "have more items?" follow-up 7/30/90 days after payout
- category-specific seasonal reminders

## Agent Reach GitHub Evaluation

Repo evaluated: `https://github.com/Panniantong/Agent-Reach`

Observed facts from live check:

- Repository: `Panniantong/Agent-Reach`
- Description: "Give your AI agent eyes to see the entire internet. Read & search Twitter, Reddit, YouTube, GitHub, Bilibili, XiaoHongShu — one CLI, zero API fees."
- Language: Python
- License: MIT
- Stars: ~69.5k
- Forks: ~5.9k
- Open issues: ~60
- Latest push observed: 2026-08-06
- Package version in `pyproject.toml`: 1.5.0
- Requires Python >=3.10
- CLI entry point: `agent-reach = agent_reach.cli:main`
- Main dependency stack: `requests`, `feedparser`, `python-dotenv`, `loguru`, `pyyaml`, `rich`, `yt-dlp[default]`
- Channels present: web, twitter, youtube, github, bilibili, reddit, facebook, instagram, linkedin, rss, exa_search, v2ex, xiaohongshu, xiaoyuzhou, xueqiu

### What Agent Reach Is

Agent Reach is **not** a CRM, sender, or lead-gen app.

It is a capability/install/health-check layer that helps an agent access platform-specific upstream tools:

- web pages via Jina Reader
- YouTube via yt-dlp
- GitHub via gh CLI
- RSS via feedparser
- Facebook/Instagram/Reddit via OpenCLI / browser session where available
- Twitter/X via CLI + cookies
- Exa search via mcporter

### How It Could Help This Plan

Best uses for Pantheon/consignment:

1. **Research collection**
   - read public pages
   - watch/source YouTube content
   - inspect GitHub repos/tools
   - pull RSS/feeds

2. **Demand-signal discovery**
   - Reddit search/read where login/session is available
   - X/Twitter search where cookies are explicitly configured
   - local/social signal review through approved browser-session paths

3. **Marketplace/source monitoring support**
   - Facebook/Instagram via OpenCLI may help with user-controlled browser-session access
   - useful for assisted research, not autonomous scraping or mass outreach

4. **Pantheon shared skill/MCP inspiration**
   - Agent Reach's model is exactly the pattern we discussed: shared capability layer + health checks + backend routing.
   - It could inform the proposed Pantheon shared-skills MCP design.

### Risks / Constraints

1. **Not a direct replacement for our phone bridge.**
   - Facebook Marketplace publishing still needs the real-device workflow / human approval gates.

2. **Cookie/browser-session channels need strict blast-radius control.**
   - Use dedicated/secondary accounts where possible.
   - Never use main personal accounts for automated exploratory tooling unless explicitly approved.

3. **Compliance risk if misused for scraping/outreach.**
   - Agent Reach can make access easier, but it does not make platform ToS or anti-scraping rules disappear.
   - Use for assisted research and source discovery, not bulk platform scraping.

4. **Installation should start read-only.**
   - Safe first step is `agent-reach install --env=auto` only.
   - Do not run `--system` or optional channel installs without explicit approval.

### Recommendation

Use Agent Reach as a **sandboxed research/access capability layer**, not as the operational core.

Recommended first test:

```bash
# no system changes; read-only dependency/channel check
python3 -m venv ~/.agent-reach-venv
source ~/.agent-reach-venv/bin/activate
pip install https://github.com/Panniantong/agent-reach/archive/main.zip
agent-reach install --env=auto
agent-reach doctor
```

Only after that succeeds, consider optional channels:

- `opencli` for desktop browser-session platform access
- `facebook,instagram` only after deciding account/session boundaries
- `reddit` only with explicit logged-in session strategy
- `twitter` only with explicit cookies and dedicated account preference

## Immediate Priority Sequence

### Phase 1 — Set up the core consignment revenue ops board

Build/verify the central objects:

- Item
- Client
- Lead
- ListingDraft
- Approval
- PlatformListing
- BuyerInquiry
- Offer
- Sale
- Payout
- Task

### Phase 2 — Set up lead generation/supply acquisition

Start with manual-assisted lead discovery, not automation-at-scale:

- Facebook local groups/manual review
- moving/estate/downsizing signals
- stale marketplace listing candidates
- small business liquidation signals

Create a lead sheet or database table with source URLs and approval status.

### Phase 3 — Set up DM/intake conversion

Create approved message templates and a manual send/reply tracking process.

### Phase 4 — Set up client retention messages

Create lifecycle templates:

- intake confirmation
- listing approval request
- price-drop approval
- buyer offer needs answer
- sold notification
- payout-ready
- more-items follow-up

### Phase 5 — Set up trust/content engine

Every completed item becomes content proof.

### Phase 6 — Agent Reach sandbox

Install in isolated venv only after approval; run doctor; decide which channels are worth connecting to Pantheon.

## Decision Needed From Konan

Choose the first execution lane:

A. **Revenue Ops Core** — build the consignment board/state machine first.  
B. **Lead Gen + DM Setting** — start finding supply leads and booking intake.  
C. **Agent Reach Sandbox** — install read-only in venv and run doctor.  
D. **Content/SEO Engine** — build the local trust/discovery surfaces.
