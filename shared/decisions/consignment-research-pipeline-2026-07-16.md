# Decision: Consignment Research Pipeline Contract

**Date:** 2026-07-16  
**Author:** Thoth  
**Status:** Final, implementation-ready  

**Summary:** Full specification written for how the consignment app research module identifies items, gathers comps, normalizes/filters/averages prices, and drafts listings. Covers FB Marketplace and eBay with distinct platform-specific output.

**Key decisions:**
1. Pipeline is 6 stages: Identify → Gather Comps → Normalize & Filter → Price Recommendation → Draft Listing → Humanize (FB only)
2. 3 parallel comp sources: eBay Sold (primary, 2× weight), eBay Active (secondary, 1× weight), Price Guides (tertiary, validation only)
3. IQR outlier filtering on ≥4 comps; trim-mean on ≥5 comps; weighted-median on 2-4 comps; heavy-discount on 1 comp
4. Humanizer runs AFTER draft, BEFORE user approval — FB only. eBay stays factual/SEO.
5. User corrections invalidate all prior comps and re-run from Stage 0 or 1 depending on what was corrected
6. Guardrails: no hallucinated prices (null + VERY_LOW if 0 comps), label weak comps, require human approval before post, fee-awareness in eBay summaries, price bounds from user constraints
7. FB recommendation: use `fair` price, conversational copy, no fees, local pickup. eBay: use `high` price, structured/SEO copy, include shipping, fee-aware.

**Full spec at:** `~/athenaeum/Codex-Forge/specs/consignment-research-pipeline-contract.md`

**Implementation target:** Hermes orchestrates, Marvin builds the integration layer. Typescript interfaces ready-to-use.
