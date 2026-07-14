# Conductor UI — Drift Remediation Build Plan

> **Status:** OPERATOR-LOCKED — pending Konan sign-off
> **Date:** 2026-06-21
> **Author:** Hephaestus
> **Trigger:** Tier-1 Spec-Conformance Audit (2026-06-21) — 6 dead nav items, broken Board, Soulforge not Workforge
> **Project root:** `/home/konan/projects/conductor-ui/`
> **Supersedes:** Nothing — this is a remediation plan, not a new feature plan

---

## 0. Provenance

| Source | What it told us |
|---|---|
| **Build plan v1.3 (2026-06-18)** | 7-route shell (Dashboard, Editor, Board, Runs, Connectors, Forge, Settings). Soulforge sibling at `/forge`. Workforge interview for node authoring. Phase 4.4-4.7 NOT STARTED. |
| **Spec-conformance audit (2026-06-21)** | 6 phantom nav items. Board broken. Forge = Soulforge not Workforge. Connectors tab broken. Editor has duplicate connector panel. Settings empty. Runs exists but spec says NOT STARTED. |
| **Tier-1 expanded gates (2026-06-21)** | Items 8 + 9 now mandatory — spec conformance + acceptance gate |

---

## 1. Tier Routing Summary

**Specialists:** Marvin (code), Iris (design sign-off on visual fixes), Hephaestus (Tier-1 verify + spec-conformance gate)
**Pattern:** Sequential — kill dead items first, then fix broken routes, then acceptance gate
**Complexity:** Medium — mostly removal + rewire, minimal new code

---

## 2. Foundation — What Exists

| Asset | Status |
|---|---|
| Vite + React + TypeScript scaffold | ✅ |
| 7 functional routes (Dashboard, Editor, Board, Runs, Connectors, Forge, Settings) | ⚠️ 2 broken (Board, Connectors), 1 wrong (Forge), 1 skeleton (Settings) |
| SDK wired (14 nodes) | ✅ |
| Workforge interview code (W1/W2 phases) | ✅ Built, not wired into Forge route |
| Kanban plugin (11+ REST endpoints) | ✅ Live on backend |
| Vite proxy for kanban API | ⚠️ Suspected broken — "Could not load the board" |

---

## 3. Phased Implementation Plan

```
Phase R1: Kill dead nav items + fix nav
  ↓
Phase R2: Fix Board (kanban API connection)
  ↓
Phase R3: Swap Soulforge → Workforge on /forge route
  ↓
Phase R4: Fix Connectors tab (remove from Editor, fix schema errors)
  ↓
Phase R5: Wire Settings page content
  ↓
Phase R6: Acceptance gate — click every route, verify every nav item works
```

---

## 4. File-by-File Changes

### Phase R1 — Kill Dead Nav Items + Fix Nav

| # | Path | Action | Owner |
|---|---|---|---|
| R1.1 | `src/components/AppShell.tsx` or sidebar component | REMOVE 6 dead StaticText items: Templates, Variables, Marketplace, Logs, Notifications, Help | Marvin |
| R1.2 | `src/routes/` | REMOVE any empty route files for dead nav items if they exist | Marvin |
| R1.3 | Verify 7-route shell matches spec exactly: Dashboard, Editor, Board, Runs, Connectors, Forge, Settings | Hephaestus |

**Size:** S
**Gate:** Sidebar shows exactly 7 clickable items, all match spec.

### Phase R2 — Fix Board (Kanban API Connection)

| # | Path | Action | Owner |
|---|---|---|---|
| R2.1 | `vite.config.ts` | Debug kanban API proxy — verify `/api/plugins/kanban` reaches `127.0.0.1:9119` with correct auth headers | Marvin |
| R2.2 | `src/routes/board.tsx` | If proxy is fine, fix board component's API client — it may be calling wrong endpoint or missing auth | Marvin |
| R2.3 | Manual verify | Click Board → see kanban columns with tasks. Click a task → see detail panel. | Hephaestus |

**Size:** S-M
**Gate:** Board renders kanban columns with real task data. No "Could not load the board."

### Phase R3 — Swap Soulforge → Workforge on /forge Route

| # | Path | Action | Owner |
|---|---|---|---|
| R3.1 | `src/routes/forge.tsx` | MODIFY — import Workforge interview component instead of Soulforge. The Workforge components were built in W1/W2 phases and live in `src/soulforge/` or `src/workforge/`. Wire them into the `/forge` route. | Marvin |
| R3.2 | `src/routes/forge.tsx` | UPDATE page heading from "Soulforge" to "Workforge" and description text | Marvin |
| R3.3 | `src/editor/` | "Forge New Node" button in Editor → link to `/forge` with context (new workflow node creation) | Marvin |
| R3.4 | Soulforge preservation | Do NOT delete Soulforge code. If it needs to survive, mount it at `/soulforge` or a sub-route. Konan's call. | Marvin |

**Size:** M
**Gate:** Click Forge in nav → see Workforge interview (workflow node creation, not god soul authoring). Click "Forge New Node" in Editor → lands on Workforge with new-node context.

### Phase R4 — Fix Connectors Tab + Remove Editor Connector Panel

| # | Path | Action | Owner |
|---|---|---|---|
| R4.1 | `src/routes/connectors.tsx` | FIX schema validation errors. The connector YAML files have schema violations. Either fix the YAML or fix the validator to match the actual format. | Marvin |
| R4.2 | `src/editor/` | REMOVE the Connector catalog right-panel from the Editor. Connectors belong on the Connectors tab, not in the editor. | Marvin |
| R4.3 | Manual verify | Click Connectors tab → see connector catalog with working filter. Editor has no connector panel in right rail. | Hephaestus |

**Size:** S-M
**Gate:** Connectors tab renders connector catalog without schema errors. Editor shows workflow canvas without connector panel.

### Phase R5 — Wire Settings Page Content

| # | Path | Action | Owner |
|---|---|---|---|
| R5.1 | `src/routes/settings.tsx` | POPULATE section content. GOD ROSTER: list of configured gods with status. CONNECTIONS: list of active connectors. THEME: theme toggle + Lumen overrides. | Marvin |
| R5.2 | Manual verify | Settings page has actual content under each section header, not just empty headers. | Hephaestus |

**Size:** S
**Gate:** Settings page has functional content. Not a dead skeleton.

### Phase R6 — Acceptance Gate

| # | Action | Owner |
|---|---|---|
| R6.1 | Click every nav item. Verify every route renders without errors. | Hephaestus |
| R6.2 | Board: verify tasks load, detail panel works, create task works. | Hephaestus |
| R6.3 | Forge: verify Workforge interview starts, completes, produces a node. | Hephaestus |
| R6.4 | Connectors: verify filter works, no schema errors. | Hephaestus |
| R6.5 | Full audit: compare rendered UI against build plan v1.3 nav structure. | Hephaestus |

**Gate:** All 7 routes render. Board works. Forge is Workforge. No dead nav items. No schema errors.

---

## 5. Tests + Verification Gates

| Phase | Gate | Command |
|---|---|---|
| R1 | 7 nav items, no dead ones | Visual: sidebar inspection |
| R2 | Board loads real tasks | Click Board → verify render |
| R3 | Forge = Workforge interview | Click Forge → verify content |
| R4 | Connectors tab works, Editor clean | Click Connectors → verify no errors |
| R5 | Settings has content | Click Settings → verify populated |
| R6 | Full acceptance sweep | Click all 7 routes, verify all functional |

---

## 6. Guardrails

- Do NOT introduce new nav items.
- Do NOT modify the 7-route shell structure.
- Do NOT delete Soulforge code — preserve it at a different route if needed.
- Do NOT touch the SDK integration (14 nodes wired).
- Do NOT break the Vite proxy to Conductor API or kanban plugin.

---

## 7. Pitfalls

| # | Risk | Mitigation |
|---|---|---|
| 1 | Board API fix reveals deeper kanban plugin auth issues | Hephaestus troubleshoots with direct curl to 9119 |
| 2 | Workforge W1/W2 code doesn't cleanly mount into /forge route | Marvin adapts the mount point; interview engine is already built |
| 3 | Connector YAML schema mismatch is in the YAML files, not the validator | Fix the YAML files to match the schema, or fix the schema to match the YAML |
| 4 | Settings page needs API data (god roster, connections) | Stub with mock data if APIs aren't ready; wire real data when available |

---

## 8. Phase Scope

| Phase | Tasks | Owner(s) | Size | Status |
|---|---|---|---|---|
| R1 | 3 files | Marvin + Hephaestus | S | ⏳ |
| R2 | 2 files + debug | Marvin + Hephaestus | S-M | ⏳ |
| R3 | 3 files | Marvin | M | ⏳ |
| R4 | 2 files | Marvin | S-M | ⏳ |
| R5 | 1 file | Marvin | S | ⏳ |
| R6 | Manual sweep | Hephaestus | S | ⏳ |

---

## 9. Post-Build

When all phases ship:
1. Hephaestus runs full acceptance sweep (all 7 routes, all nav items)
2. Spec-conformance audit clean against build plan v1.3
3. Kanban board verified operational
4. Workforge verified as the /forge route
5. Decision log updated
