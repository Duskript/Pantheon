# External Sources for Pantheon Improvement — Research Results

**When:** 2026-07-03  
**Who:** Thoth  
**Status:** Completed

## Key Findings

**Immediate action items:**
1. **QUALITY.md** — write `~/pantheon/QUALITY.md` as formal quality model for Ichor gates. Low effort, high precision gain.
2. **Dokoro affective memory** — integrate `dokoro_feedback_record` → `dokoro_feedback_route` pattern as sidecar MCP for god tool routing.

**Build (adopt pattern):**
3. **Trace replay** — borrow Mirrors' approach (Ichor events → sandbox → replay → score) for pre-deploy validation. Implement self-hosted via Conductor workflow.

**Defer:**
4. **Ctx** — if multi-harness search becomes needed.
5. **Onyx-MCP signed receipts** — when autonomous ops scale sufficiently.

**Don't:**
- Don't replace Ichor with Dokoro. Supplement only.
- Don't pay for Mirrors SaaS. Build on Ichor.
- Don't add crypto now. Trust problem doesn't exist yet.

**Full report:** Codex-God-thoth/research/pantheon-improvement-sources-20260703/report.md
