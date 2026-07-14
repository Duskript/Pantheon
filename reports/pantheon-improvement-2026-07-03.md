🏛️ Pantheon Improvement Report
_2026-07-03 23:31 UTC_

## 🥋 Skills (Hermes Dojo)
  **Success rate:** 97.0%
  **Trend:** [  ▅▅▇██]
  **7-day delta:** 📈 +3.0%
  **30-day delta:** 📈 +8.3%

  🔻 **Weakest tools:**
    • mcp_playwright_browser_click: 33.3% success
    • mcp_playwright_browser_navigate: 57.1% success
    • mcp_composio_COMPOSIO_REMOTE_BASH_TOOL: 66.7% success

## 🔧 Harnesses (Ichor Forge)
  **Interventions (7d):** 13
  **Overall block rate:** 100%
  🔴 **logic_gate:** 13 calls, 100% block rate
       ↳ Logic Gate: 1 issue in '/home/konan/pantheon/scripts/craigslist-monitor.py': 2x
       ↳ Logic Gate: 1 issue in '/home/konan/projects/theoforge-visual-editor/web/tsconfig.app.json': 1x

  🔍 **Patterns detected (3):**
    • ⚠️ logic_gate is over-blocking (100% block rate on 13 calls). Consider relaxing thresholds.
    • 🚨 Recurring failure mode (6x / 46% of blocks): "Line 14: leftover print() call". Affected gods: hermes(5), thoth(1). Suggestion: strengthen god system prompts to require removal of all top-level print() calls in files containing function defs before responding.
    • 📊 Model 'unknown' has 100% block rate (12/12). This model may need adjusted gate thresholds or better instructions.

  💡 **Suggested adjustments (2):**
    • add Before responding, scan every file you wrote or modified. If a file contains function definitions (def/async def), remove any top-level print() calls (column-0 prints outside the if __name__ == '__main__' guard). Indented prints inside functions are fine. to god_system_prompt (Recurring 'leftover print()' (6x). Affects: thoth, hermes, marvin, hephaestus, apollo.)
    • modify unknown to model_thresholds (12/12 interventions blocked (100%))

## ⚖️ Memory Weights (Retrieval)
  **Current weights:**
    • **fts5:** 0.45  █████████░░░░░░░░░░░ 45%
    • **vector:** 0.20  ████░░░░░░░░░░░░░░░░ 20%
    • **events:** 0.20  ████░░░░░░░░░░░░░░░░ 20%
    • **reference:** 0.15  ███░░░░░░░░░░░░░░░░░ 15%

  **Queries logged (7d):** 2085
  **Avg results/query:** 5.0

  **Top queries:**
    • "auth middleware" — 85x
    • "NATS jetstream" — 85x
    • "Cloudflare tunnel" — 85x
    • "memory upgrade" — 85x
    • "ichor retrieval" — 85x

---
_Report generated: 2026-07-03 23:31 UTC_