# Ichor Subconscious Tick — 2026-07-11 04:15 UTC

**Source:** Cron job (ichor_subconscious.py)  
**God:** Thoth  
**Status:** Processed

## Summary

Subconscious tick found **4 events** for Thoth (of 2,677 total events in past 24h across the fleet). Two persistent blockers resurfaced alongside active BTST/Ghost project work.

## Findings

### 1. 🔴 BTST / Ghost Bridge — Active Project
- **Ghost bridge** must have **full access** (Content API + Admin API with safety gates), not read-only
- Admin-only auth first using **BTST auth** — no Ghost member SSO in Wave 1
- **SQLite** first, **Cybermag UI**
- **Multi-install mapping** (InstallConnection record with baseUrl, auth, ownership, status, plugin caps) needed *before* Tallon/Amber/customer access — but does **not** block Phase 1 or the local BTST app scaffold
- Ghost/BTST shared auth deferred to later phase
- Via session `20260710_213444_74d4e1`

### 2. 🔴 Affective Memory — Still Missing (Jul 3→Jul 10)
- PRD'd **July 3** but *never queued for build*
- Every tool call outcome (success/failure/latency) gets recorded; gods query a **Wilson lower bound + recency decay** ranked signal for tool routing
- Tension gate covers claim conflicts but **nothing covers tool reliability**
- This is the single biggest unanswered capability gap
- 👉 PRD at: `Codex-God-thoth/research/pantheon-improvement-sources-20260703/prd-dokoro-integration.md` (Phase 2, ~6h)

### 3. 🟡 QUALITY.md — Never Written
- PRD exists but `~/pantheon/QUALITY.md` was **never created**
- Formal quality model for Ichor gates & forge (5 areas, 18 factors)
- 👉 PRD at: `Codex-God-thoth/research/pantheon-improvement-sources-20260703/prd-qualitymd-integration.md` (Phase 1, ~2h)

### 4. 🔵 Ichor v2 Spec — In Progress
- Tension gate v1→v2: WFGY + Mnemos as reference sources
- Hysteresis rules, tense claims with `zone`/`tension_score`
- Claims default to `active` (changed from `pending`)
- Structural extractor as companion to tension gate
- Spec update handed off to Hermes around 03:59 UTC

## System Health

| Backend | Status |
|---------|--------|
| FTS5 | ✅ OK |
| Vector (109,425 embeddings) | ✅ OK |
| Events (311,764 total) | ✅ OK |
| Reference (L2) | ✅ OK |
| Entities / Relationships | 13,674 / 20,578 |
| LLM Extractions | 1,148 logged |

## Recommendations

1. **Immediate (~2h):** Write `~/pantheon/QUALITY.md` — the draft PRD has the full model ready to copy
2. **Short-term (~6h):** Build affective memory (Dokoro Phase 2) — the subconscious keeps surfacing this as the #1 gap
3. **Ongoing:** BTST/Ghost bridge follows its current trajectory; Phase 1 is not blocked
