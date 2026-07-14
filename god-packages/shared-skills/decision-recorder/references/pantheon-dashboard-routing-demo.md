# Pantheon Health Dashboard — Routing Demo (2026-06-16)

> **Context:** Hephaestus rework routing test. Walked through a hypothetical "Pantheon Health Dashboard" build to prove every keyword in the dispatch table routes to exactly one god. Every code-producing task gets a Thoth QA follow-on. Every phase has a Hephaestus gate.

## The request

"Build a Pantheon-wide health dashboard. One surface that shows the status of every subsystem, every god, every active chain, and every cron pipeline."

## Full routing table (proved end-to-end)

### Build-plan-orchestrator chain (Steps 1-5)

| Step | Keyword matched | Routes to | Why |
|---|---|---|---|
| t1 tier-route | `tier-route` | **hephaestus** | He executes the chain |
| t2 find-similar | `find-similar` | **hephaestus** | He executes the chain |
| t3 write plan | `write plan` | **hephaestus** | He authors the plan (Konan+Thoth decide, Hephaestus executes) |
| t4 sign-off | `final sign-off` | **thoth** | The gate — operator-in-the-loop, stays with Thoth |
| t5 dispatch | `dispatch the build` | **hephaestus** | He dispatches the work to specialists |

### Per-phase dispatch

#### Phase 0 — Foundation

| Task | Keyword | Routes to | Why |
|---|---|---|---|
| Research subsystem metrics | `research`, `investigate` | **thoth** | Research lane |
| Design dashboard UI | `Action: DESIGN`, `ui design` | **iris** | UI/UX lane |
| Scaffold React project | `Action: CREATE`, `scaffold` | **marvin** | Code lane |
| Architecture review | `architecture review` | **hephaestus** | Design review lane |
| QA review of scaffold | `Action: REVIEW`, `code review` | **thoth** | QA gate |

#### Phase 1 — Backend

| Task | Keyword | Routes to | Why |
|---|---|---|---|
| Build health endpoints (×5) | `Action: CREATE`, `implement` | **marvin** | Code lane |
| Wire to Conductor workflow | `architecture`, `integration design` | **hephaestus** | Integration seam |
| QA review (×5) | `Action: REVIEW` | **thoth** | QA gate |

#### Phase 2 — Frontend

| Task | Keyword | Routes to | Why |
|---|---|---|---|
| Build dashboard panels (×5) | `Action: CREATE`, `component` | **marvin** | Code lane |
| Design audit vs Olympus system | `Action: DESIGN`, `visual QA` | **iris** | Design system lane |
| QA review (×5) | `Action: REVIEW` | **thoth** | QA gate |

#### Phase 3 — Operations

| Task | Keyword | Routes to | Why |
|---|---|---|---|
| Wire cron schedule | `cron`, `operations` | **hermes** | Operations lane |
| Gateway health monitoring | `message`, `route` | **hermes** | Gateway lane |
| Register in Conductor catalog | `orchestrate`, `system design` | **hephaestus** | Catalog management |
| QA review | `Action: REVIEW` | **thoth** | QA gate |

#### Phase 4 — Polish + Ship

| Task | Keyword | Routes to | Why |
|---|---|---|---|
| Accessibility audit | `Action: DESIGN` | **iris** | Accessibility lane |
| Dashboard copy (tooltips) | `copy` | **rheta** | Copywriting lane |
| Final QA review | `Action: REVIEW`, `qa review` | **thoth** | QA gate |
| Architecture sign-off | `contract review` | **hephaestus** | Design review |
| Phase gate → operator | `monitor chain` | **hephaestus** | Conductor |

## Keyword → God summary

| God | Keywords |
|---|---|
| **hephaestus** | `tier-route`, `find-similar`, `write plan`, `dispatch the build`, `architecture review`, `design review`, `contract review`, `integration design`, `architecture design`, `monitor chain`, `orchestrate`, `system design` |
| **thoth** | `final sign-off`, `Action: REVIEW`, `code review`, `qa review`, `research`, `search`, `synthesize`, `investigate` |
| **marvin** | `Action: CREATE`, `Action: MODIFY`, `implement`, `scaffold`, `code` |
| **iris** | `Action: DESIGN`, `ui design`, `ux design`, `figma`, `token`, `component` |
| **hermes** | `cron`, `route`, `message`, `operations` |
| **rheta** | `copy` |
| **DEFAULT** | `thoth` (reviews and routes if no keyword matches) |

## Rules verified

1. Every keyword maps to exactly one god — no ambiguity, no overlap
2. Every code-producing task (`Action: CREATE`/`MODIFY`) gets a `thoth` QA follow-on
3. Every phase boundary has a `hephaestus` gate
4. `thoth` does NOT get dispatched code production work (only reviews)
5. `hephaestus` does NOT get dispatched code production work (only architecture + dispatch)
6. Niche gods (`rheta`, `mercer`, `apollo`, `caduceus`) only get their domain-specific keywords
