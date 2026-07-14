# Synergy Codes Workflow Builder SDK — Conductor UI Fit Assessment

> Spike deliverable for `t_acc5b6fd`. Adopt / pilot / defer recommendation
> with a 1-page TL;DR, theming answer, ranked risks, and relative sizing.
>
> Sister document: [`synergy-wb-port-adapter-spec.md`](./synergy-wb-port-adapter-spec.md)
> (the port adapter design referenced throughout).
>
> Sibling artifacts (this spike):
> - Demo screenshot: `synergy-wb-demo-screenshot.png`
> - Embed flag OFF: `synergy-wb-embed-flag-off.png`
> - Embed flag ON: `synergy-wb-embed-flag-on.png`

## TL;DR — **YES, WITH CAVEATS — adopt via pilot**

The Synergy Codes Workflow Builder SDK is a credible, production-quality
visual editor that mounts cleanly in the Conductor UI shell (verified
end-to-end in this spike). The two main caveats are (1) the editor's
node vocabulary and Conductor v2's workflow YAML are not shape-compatible
— a non-trivial translation layer is required, and (2) Conductor v2 has
**no REST CRUD for workflows today**, so a small new API surface must
ship in the conductor codebase before the editor can save/load
anything. Build the API server first, build the port adapter second,
and the editor mounts for free. The SDK's design is stable
(`2.1.0`, just shipped 2026-06-16) and the embed path is the lowest-risk
piece of this whole stack.

## 30-second fit summary

**What we want:** a visual node-graph editor for Conductor v2's
file-based YAML workflows, embedded in Conductor UI, that lets the
operator author, validate, and (optionally) trigger workflows from
`/editor/<id>` in the existing 4-layer shell.

**What the SDK gives:** `<WorkflowBuilder.Root>` — a React compound
component backed by `@xyflow/react` (canvas) + `@jsonforms/react`
(properties panel) + `@phosphor-icons/react` (palette icons) +
`@synergycodes/overflow-ui` (their design system, beta) +
`i18next` (translations) + a plugin architecture (component / function /
translation decorators) and three persistence strategies
(`localStorage` default, `api` for backend, `props` for fully host-owned).
Install size on top of conductor-ui: **+134 npm packages, +1583 lockfile
lines (26% growth), +node_modules 468M, 34.5s install**. Peer dep set is
real and React 19 compatible (`@xyflow/react@^12`, `@jsonforms/*@^3.4`,
`i18next@^24`, `immer@^10`, `zustand@^5` — zustand was already
shared with conductor-ui).

**What blocks a clean "just install and go":** Conductor v2 has no REST
endpoint to list/read/save a workflow. The engine loads YAML eagerly
from `~/pantheon/conductor/workflows/*.yaml` at startup and never
re-exposes it. The SDK's `api` persistence strategy needs a backend, and
the backend does not exist. This is the single biggest spike finding —
**a M-L piece of work (new `api_server.py` in `~/pantheon/conductor/v2/`)
must land first**, then the M-sized port adapter + node-vocabulary
translation, then the editor mounts without further design work.

## Path A vs Path B — Docker

**Recommendation: stay on Path A (Vite + React embed) — Docker is
explicitly out of scope per the brief.** The spike used `pnpm dev:demo`
(their monorepo) for the demo and `npm run dev` (our existing
conductor-ui) for the embed — both worked, neither required Docker.
The Synergy repo's preflight script does try to bring up Docker
Compose (`apps/backend/docker-compose.yml`) but the front-end-only
`<WorkflowBuilder.Root>` does not need it. The `dev:ai-studio` script
*does* need Temporal via Docker, but `dev:demo` does not. **The
editor's path is Docker-free.**

`@workflowbuilder/sdk` ships a pre-built `dist/` (ESM + CSS bundle) and
can be installed as a plain npm dep with no source build — proven by
the 34.5s `npm install` in this spike. Building from source requires
the full pnpm monorepo + the `icons` package's `pnpm build` step
(needed once after clone, not in CI) — the demo's first run errored on
`Failed to resolve import "../dist" from "../icons/src/icon.tsx"`, fixed
by running `pnpm build` in `apps/icons/`. This is a one-time setup
gotcha for their monorepo, **not** for the consumer.

## Theming — "can it look like Workforge?"

**Yes, with caveats.** Two layers in the SDK's theming model:

1. **Top-level CSS variables** (well-documented, simple to override):
   `--wb-background-color`, `--wb-font-family`, `--wb-transition`, plus
   scrollbar tokens. Set these on `:root` (or scope to the editor
   container) and the SDK paints with your colors. The spike's embed
   screenshot shows conductor-ui's Lumen dark theme bleeding through
   into the SDK's canvas without any override — the SDK's defaults are
   light-gray-on-white and the editor inherits the parent's background
   where it doesn't paint its own.
2. **`@synergycodes/overflow-ui` `--ax-*` tokens** (less simple). The
   SDK's `style.css` ships a bundled copy of Overflow UI's tokens.
   Re-theming to Lumen requires either (a) shipping a Lumen-token CSS
   file that overrides `--ax-*` at the editor root, OR (b) accepting
   Overflow UI's design language inside the editor while Lumen lives
   on the shell. Option (a) is "L" effort; option (b) is "S" but
   visually two design systems side by side.

The 2026-06-15 demo screenshot shows the un-themed default: light
gray canvas, gray top bar, gray icons. The 2026-06-16 embed screenshot
shows the SDK mounting inside the Lumen dark shell — the SDK adapts
to the background but the chrome (top bar, palette, properties panel
icons) is still gray-on-light. **Real Workforge visual parity needs
(a), an L-effort theme-override pass.** Cheap path: use Overflow UI
as-is and live with the visual mismatch inside the editor. Right
answer: re-theme to Lumen tokens, ship as part of the pilot.

Also: the SDK ships `@fontsource/poppins` as a bundled dep. Conductor
UI's Lumen theme likely uses Inter or system-ui; Poppins adds ~50-100KB
of font weight. Override `--wb-font-family` to your font and Poppins
falls out of any visible path (still bundled, not a tree-shake win
without ejecting).

## 5 ranked risks + mitigations

### Risk #1 — Conductor v2 has no workflow CRUD API (BLOCKER for save/load)

**Impact:** The editor cannot save a workflow back to disk. The
`api` persistence strategy has nothing to talk to.

**Mitigation:** Ship `~/pantheon/conductor/v2/api_server.py` first —
~300-500 LOC that wraps the existing file-based workflows dir
(GET/PUT/DELETE) and the workflow_validator (POST /validate). The
server is started by `ConductorService` in `service.py:56` behind the
same lifecycle, single bearer token for auth. This is the blocker.
The port adapter spec §4.4 enumerates the 8 proposed endpoints; none
require new business logic, just wrapping the existing functions.

**Estimated effort:** M-L for the API server alone. Without it, the
editor is read-only and the pilot fails on day 1.

### Risk #2 — Conductor v2 has no auth on its existing servers (security gap)

**Impact:** The webhook at :8088 and LiveStream at :7700 currently
accept any caller. Today, both bind to `0.0.0.0` by default (see
`webhook.py:34` and `live_stream.py:DEFAULT_HOST`), which means any
process on the host (or any container on the same network) can POST
events or stream runs. Adopting the SDK forces us to add auth —
otherwise the new "edit workflows from a UI" path is wide open too.

**Mitigation:** Add a single bearer token, set via env var
(`CONDUCTOR_API_KEY`), enforced by the existing webhook/livestream
servers and the new api_server. Conductor UI reads the same token at
startup from `~/.hermes/.env` (the same file that already holds
`API_SERVER_KEY` for Hermes gateway). Reject by default. This is
~30 LOC per server, mostly the `Authorization: Bearer ...` check.

**Estimated effort:** S, but **must land in the same milestone as
Risk #1** — shipping the new API without auth is the worst of both
worlds (new surface, no guard rails).

### Risk #3 — Node vocabulary mismatch between SDK and Conductor v2

**Impact:** The SDK's `nodeTypes: PaletteItem<NodeSchema>[]` is the
editor's vocabulary. Conductor v2's workflow YAML uses its own
7-ish step kinds (god-call, nats-publish, decision, parallel, etc.).
A 1:1 mapping is needed in BOTH directions:
- **Authoring:** Synergy `WorkflowDefinition<TNode>` → Conductor YAML
  (steps, input_from, gates, timeout, operator_approval_required)
- **Observing:** Conductor `WorkflowInstance` status → Synergy node
  state (idle / running / completed / failed) for the SDK's UI

The diamond/join topology is the tricky one: Conductor v2's `input_from`
is a single string ref per step, but Synergy's edge graph supports
multi-input. Either flatten at translate time (lossy) or add an
explicit join node (lossless, requires new step type).

**Mitigation:** Pick the 4-6 most-used Conductor v2 step kinds for
the pilot (god-call, nats-publish, decision, parallel-fanout). Define
their PaletteItem (label, icon, JSON schema, JsonForms uischema,
default data). The demo's 8 node types in
`apps/demo/src/app/data/nodes/` are a copy-paste template for the
shape — ~100-120 LOC per node kind. Translation layer is ~400 LOC.

**Estimated effort:** M (node vocab) + M (translator). The
hex port + persistence + SSE glue is S-S each on top.

### Risk #4 — Theming depth is unproven

**Impact:** If "look like Workforge" means strict visual parity with
the Lumen theme, the work has not been sized. The SDK's design
system (`@synergycodes/overflow-ui`) is in beta (1.0.0-beta.27), and
the re-theme work is not documented in the SDK's public docs as a
common pattern.

**Mitigation:** Pilot includes a 1-week "themed embed" sub-milestone
at the end. If the re-theme takes longer than S, accept the visual
mismatch (Option b above) and re-evaluate. Don't gate the pilot on
visual polish — the operator workflow benefit (graphical workflow
editing with validation) is the actual win.

**Estimated effort:** S to M for a theming pass. S to skip.

### Risk #5 — SDK is on a moving target

**Impact:** The SDK just shipped 2.1.0 on 2026-06-16. The
`DECISION-LOG.md` notes four major restructure phases (Phase 1, 2,
3b, 4) in 12 months. Public API today is `<WorkflowBuilder.Root>`
with subcomponents, but the log shows the entry point has changed
3 times. The hex port is more stable (execution-core is older and
hex patterns don't get rewritten often).

**Mitigation:** Pin `@workflowbuilder/sdk@2.1.0` exactly. Subscribe
to the repo's releases. Budget a small recurring slot per release cycle for SDK
upgrades. If breaking changes land, the upgrade window is
sub-cycle — the API surface is small. The biggest risk
is the *node type* and *plugin* API drifting; the persistence and
theming layers are likely stable.

**Estimated effort:** S per upgrade, but recurring. A frozen fork
is worse than the upgrade cost — Synergy Codes is responsive and
the SDK is their product, not a side project.

## Recommended next step

**Adopt with a pilot.** Specifically:

1. **Milestone 0 (this spike — DONE):** Validate the embed path in
   Conductor UI. `synergy-wb-embed-flag-on.png` is the proof.
2. **Milestone 1 (~one short cycle):** Ship the Conductor v2
   `api_server.py` with auth (Risks #1 + #2). It's M-L and unblocks
   everything else.
3. **Milestone 2 (~one short cycle):** Build the 4 most-used
   PaletteItem node types (god-call, nats-publish, decision,
   parallel-fanout) + the translation layer. M + M.
4. **Milestone 3 (~one short cycle):** Mount the editor in
   `/editor/$id` for real (replace the placeholder). Wire the
   persistence adapter + SSE event relay. S + S.
5. **Milestone 4 (~one short cycle):** Theme to Lumen. M (or
   accept Overflow UI as-is and defer — pilot's value is
   the workflow-authoring flow, not the visual polish).

Pilot kill criteria: if Milestone 1's API server surfaces a deeper
gap (e.g., the engine doesn't support runtime reload after
PUT, or the workflow validator rejects visually-valid graphs),
stop and reassess. The custom-editor-from-scratch path is the
fallback (estimate: 2-3x the work of the SDK adoption, but full
control).

## Effort estimate (relative)

| Workstream                                | Size  | Blocked by       |
| ----------------------------------------- | ----- | ---------------- |
| Conductor v2 `api_server.py` + auth       | M-L   | nothing (start here) |
| Port adapter (persistence + hex port)     | M     | api_server       |
| Node vocabulary + translator              | M     | pick the 4-6 step kinds first |
| UI integration (replace `/editor/$id` placeholder) | S | adapter |
| Live event SSE relay                      | S     | LiveStreamServer (exists) |
| Themed embed pass (Lumen)                 | M     | SDK in `/editor/$id` |
| Tests across the above                    | M     | parallel         |
| Documentation + runbook                   | S     | parallel         |

**Adoption total: L.** Vs **XL for custom editor** (canvas + drag/drop
+ properties panel + persistence + SSE + integrations all built
from zero). The SDK is a real saving — but the saving is partially
absorbed by the new Conductor v2 API surface that has to land first.
A custom editor would have needed that same API surface anyway, so
the net comparison is "L for SDK, L for custom" at the API layer,
plus "M for SDK adapter, 0 for custom" at the editor layer. **The
SDK is M-faster on a 2-3x axis**, but the absolute work is the
same ballpark because the API server is the dominant cost.

This makes the SDK adoption's ROI: **pay M now to get a maintained
editor (Synergy Codes ships fixes, new node types, theming
updates) for free, vs pay 0 now and own the full maintenance
curve in-house.** That's the decision the pilot should validate.

## What was verified in this spike

- [x] Demo ran via `pnpm dev:demo` (Path B, no Docker); editor mounts
      on `http://localhost:4200`, all 4 panels render, screenshot
      captured (`synergy-wb-demo-screenshot.png`).
- [x] `@workflowbuilder/sdk@2.1.0` installed in
      `/home/konan/projects/conductor-ui/` via `/editor-spike` route
      behind `VITE_FEATURE_SYNERGY_WB=true` feature flag. Embed
      screenshot captured (`synergy-wb-embed-flag-on.png`).
- [x] Flag-off state confirmed: shell renders, route shows
      "feature flag off" message, SDK not loaded
      (`synergy-wb-embed-flag-off.png`).
- [x] No new TypeScript errors introduced by the embed; pre-existing
      build errors in `src/state/`, `src/api/`, `src/ledger_client/`
      are NOT in scope for this spike and are NOT my changes
      (verified by `npm run build` diff and `git status`).
- [x] Install timing + lockfile growth + node_modules size measured.
- [x] `~/pantheon/conductor/v2/` real endpoints enumerated and
      referenced in `synergy-wb-port-adapter-spec.md` (no invented
      endpoints; new surface is marked `[PROPOSED — not yet
      implemented]`).
- [x] All references are file paths (`engine.py:970`,
      `webhook.py:37`, `live_stream.py:263`, etc.) verified by
      `read_file`/`grep` in this session.

## What was NOT verified (out of scope or blocked)

- Drag/drop interaction: the editor's editor renders, but the
  spike did not click + drag nodes. (Path A/B verification of the
  editor's *interactivity* is in scope for the pilot, not the spike.)
- Save/load round-trip: no API server exists yet to save to.
- Live event streaming: WebSocket and SSE integration were scoped
  to "design the port" not "wire the live socket" in the spike.
- The 4-6 PaletteItem node types for Conductor v2's step kinds:
  not built; estimated but not implemented.
- Lumen theme override: `--wb-*` tokens identified; the actual CSS
  override file is not written.

## Verdict — YES, WITH CAVEATS

The SDK is a real, production-quality editor that we can mount in
Conductor UI in one afternoon (proven by this spike). The
caveat is the Conductor v2 API surface work that has to land
first — without that, the editor is read-only and the pilot's
value evaporates. The second caveat is theming — we can ship
visually inconsistent at first and re-theme in a follow-on.

The honest "no" reasons to defer:
- The Conductor team has more pressing Phase 1-3 work
- We don't yet know the operator's actual authoring flow
  (do they edit by hand, by Soulforge interview, or visually?)
- The hex port model assumes the editor drives execution,
  but Conductor v2 is event-driven from webhooks — the
  trigger story for a "Run" button is unclear

The honest "yes" reasons to pilot:
- The embed is cheap (M total), the maintenance curve is real
  (Synergy Codes ships), and the operator's authoring flow is
  the highest-leverage UI work in the Phase 1-4 plan
- The api_server.py is needed regardless of which editor
  ships — even a custom editor would need it
- The spike proves there are no hidden integration landmines
  (no React 19 / no ReactFlow / no JsonForms peer dep conflicts,
  no SSR or build-tool surprises)
