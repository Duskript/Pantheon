# Olympus API Consolidation Implementation Plan

> **For Hermes/Marvin:** Use disciplined, surgical implementation. Read before write. Keep upstream Hermes changes out of the critical path whenever possible.

**Goal:** Consolidate Olympus/Pantheon UI API ownership so Olympus backend becomes the canonical service for Olympus-facing routes, Pantheon webui becomes a thin adapter during migration, and upstream Hermes dashboard/web_server stops being a required customization surface.

**Architecture:** Today, Olympus-facing behavior is split across three layers: upstream Hermes dashboard routes, Pantheon webui routes, and the standalone Olympus backend on `127.0.0.1:8788`. The refactor should collapse ownership so Olympus backend becomes the source of truth for Olympus APIs, while Pantheon webui either proxies temporarily for compatibility or gets out of the way entirely. Upstream Hermes should remain an internal dependency, not the routing/auth spine for Olympus.

**Tech Stack:** FastAPI (`services/olympus-backend/main.py`), Pantheon webui Python HTTP server (`webui/api/routes.py`, `webui/api/auth.py`, `webui/api/models.py`, `webui/api/profiles.py`), Olympus UI frontend clients, Hermes Agent upstream dashboard/web server.

---

## Current State Summary

### Layer A — Olympus backend (`services/olympus-backend/main.py`)
Currently owns direct routes for:
- `/api/auth/login`
- `/api/auth/logout`
- `/api/auth/me`
- `/api/users`
- `/api/feature-flags`
- `/api/theme`
- `/api/athenaeum/walk`
- `/api/athenaeum/read`
- `/api/athenaeum/search`
- `/api/stream/entities`
- `/api/stream/edges`
- `/api/stream/metrics`
- `/api/olympus/auth/me`
- `/api/olympus/features`
- `/api/olympus/features/definitions`

### Layer B — Pantheon webui (`webui/api/routes.py`)
Currently owns or serves Olympus-adjacent routes for:
- `/api/models`
- `/api/profile/switch`
- `/api/sessions`
- `/api/ideas`
- `/api/notifications/poll`
- `/api/theme`
- `/api/users`
- `/api/auth/me`
- `/api/olympus/*` → proxied to `http://127.0.0.1:8788`

### Layer C — Upstream Hermes (`hermes_cli/web_server.py`, dashboard auth middleware)
Currently represents the risky seam because local custom behavior in upstream Hermes can be stomped during updates. Public-path logic is intentionally narrow upstream, so any Olympus/Pantheon feature depending on loosened local dashboard auth is fragile.

---

## Hard Constraints

1. **Do not keep Pantheon runtime behavior dependent on local edits to upstream Hermes `web_server.py`.**
2. **Session pinning is a UI/Pantheon concern, not a Hermes-core concern.**
3. **TokenJuice god-tracking patch is not required for this migration.**
4. **Telegram patch is not required for this migration.**
5. **Preserve user-visible behavior during migration via compatibility shims/proxies where needed.**
6. **Do not merge the two auth systems blindly.** Olympus backend auth and Pantheon webui auth/session handling are currently different systems.

---

## Canonical Ownership Target

### Olympus backend should become canonical owner for:
- `/api/auth/*`
- `/api/users`
- `/api/feature-flags`
- `/api/theme`
- `/api/athenaeum/*`
- `/api/stream/*`
- `/api/olympus/*`
- eventual `/api/notifications/*`
- eventual `/api/ideas`

### Pantheon webui should either:
- temporarily proxy compatibility endpoints to Olympus backend, or
- stop serving Olympus-owned endpoints entirely once callers are migrated.

### Pantheon webui may continue owning during transition:
- `/api/models`
- `/api/profile/switch`
- `/api/sessions`
- session shaping/aggregation logic
- profile-aware runtime behavior

### Upstream Hermes should only own Hermes things:
- stock dashboard/admin flows
- stock Hermes system routes
- core agent runtime internals
- not Pantheon/Olympus-specific auth bypass behavior

---

## Migration Strategy

### Phase 0: Freeze the dangerous seam

**Objective:** Stop adding new Pantheon/Olympus behavior to upstream Hermes.

**Files:**
- Modify policy/docs only in this phase; no code required to begin.
- Reference risk files:
  - `hermes-agent/hermes_cli/web_server.py`
  - `hermes-agent/hermes_cli/dashboard_auth/middleware.py`
  - `hermes-agent/hermes_cli/dashboard_auth/public_paths.py`

**Tasks:**
1. Treat any new Olympus/Pantheon route work in upstream Hermes as blocked unless there is no other path.
2. Document that local `web_server.py` customization is migration debt, not a valid long-term extension point.
3. Keep Telegram and TokenJuice tracking patches out of scope for this consolidation.

**Verification:**
- No new Olympus-specific endpoints land in upstream Hermes during the refactor.

---

### Phase 1: Decide the auth direction

**Objective:** Choose one canonical auth story before moving more endpoints.

**Problem:**
- Olympus backend currently uses bearer tokens / its own token verification.
- Pantheon webui currently uses cookie/session validation and profile-aware session identity.

**Decision required:**
Choose one of these and stick to it:

#### Option A1 — Olympus backend becomes auth authority
- Olympus UI authenticates directly against Olympus backend.
- Pantheon webui forwards identity to Olympus backend only where compatibility is still needed.
- Best long-term cleanliness.

#### Option A2 — Pantheon webui remains auth edge temporarily
- Pantheon webui validates the current session/cookie.
- Pantheon webui forwards verified identity to Olympus backend in trusted internal calls.
- Lower migration friction; acceptable as an intermediate step.

**Recommendation:** Start with **A2 as an intermediate step**, then migrate to **A1** only if needed. This minimizes breakage while still moving route ownership out of upstream Hermes.

**Files likely involved:**
- `webui/api/auth.py`
- `webui/api/routes.py`
- `services/olympus-backend/main.py`
- Olympus frontend API client files

**Verification questions:**
- Can Olympus backend accept trusted forwarded identity from Pantheon webui?
- Can Olympus UI call Olympus backend directly without losing profile/session context?
- Which clients currently depend on cookie auth vs bearer auth?

---

### Phase 2: Collapse duplicate easy endpoints first

**Objective:** Remove duplicate ownership where the endpoint semantics are simple.

**Endpoints to consolidate first:**
- `/api/auth/me`
- `/api/users`
- `/api/theme`

**Why these first:**
They exist in both the backend and Pantheon webui and are easier than sessions/models/profile-switch.

**Files:**
- Backend canonical implementations:
  - `services/olympus-backend/main.py`
- Webui compatibility/proxy layer:
  - `webui/api/routes.py`
  - `webui/api/auth.py`
- Frontend callers:
  - Olympus UI client modules (find all `/api/auth/me`, `/api/users`, `/api/theme` consumers)

**Steps:**
1. Normalize response shapes between Pantheon webui and Olympus backend.
2. Decide whether the webui route becomes:
   - a thin proxy to Olympus backend, or
   - a removed/deprecated route after clients migrate.
3. Migrate frontend callers to the canonical route surface.
4. Keep compatibility wrappers only if an active caller still depends on the legacy shape.
5. Delete duplicate business logic after callers have moved.

**Verification:**
- `GET /api/auth/me` returns the same user/bootstrap shape through the chosen canonical path.
- `GET /api/users` returns the same user list shape and permissions behavior.
- `GET /api/theme` produces identical effective theme data before/after cutover.

---

### Phase 3: Move Olympus-native service routes fully under Olympus backend

**Objective:** Make backend-owned service routes truly backend-owned.

**Endpoints:**
- `/api/feature-flags`
- `/api/athenaeum/*`
- `/api/stream/*`
- `/api/olympus/*`

**Files:**
- `services/olympus-backend/main.py`
- `webui/api/routes.py`
- Olympus frontend API clients

**Steps:**
1. Audit all callers for `/api/olympus/*` and direct Olympus service routes.
2. Pick one public route surface:
   - either direct backend routes, or
   - stable webui proxy paths mapped 1:1 to backend.
3. Ensure proxying, if kept, is dumb/pass-through only — no business logic.
4. Remove duplicate parsing/serialization logic from webui.
5. Add smoke tests for backend route availability and payload shapes.

**Verification:**
- All Olympus service routes resolve correctly without any dependence on Hermes dashboard auth bypass logic.
- Shutting off local customizations in upstream Hermes does not break these endpoints.

---

### Phase 4: Untangle the hard endpoints

**Objective:** Design proper ownership for session/profile/model orchestration rather than copying code around.

**Hard endpoints:**
- `/api/models`
- `/api/profile/switch`
- `/api/sessions`
- `/api/notifications/poll`
- `/api/ideas`

**Why hard:**
These are not simple CRUD endpoints. They carry profile/runtime/session shaping behavior and UI-specific aggregation logic.

#### `/api/models`
Current owner behavior lives in Pantheon webui and is tied to config/runtime/provider knowledge.

**Target:**
- Either keep this in Pantheon webui as an adapter service, or
- extract a shared service module that both webui and backend can call.

#### `/api/profile/switch`
Current owner behavior is deeply tied to webui profile runtime state.

**Target:**
- Keep profile switching in Pantheon webui unless/until there is a clean backend-level profile-runtime abstraction.

#### `/api/sessions`
Current webui route merges webui session state with CLI metadata and preserves UI-owned fields like pinned/archived.

**Target:**
- Keep session shaping logic out of upstream Hermes.
- Consider extracting session aggregation into a Pantheon-owned shared service module.
- Keep pinning UI-owned.

#### `/api/notifications/poll`
Current implementation is simple enough to migrate later.

**Target:**
- Move to backend once the notification storage contract is settled.

#### `/api/ideas`
Current implementation is simple file-backed behavior.

**Target:**
- Migrate to backend after the auth and route contract is stable.

**Verification:**
- Each hard endpoint gets an explicit owner before code moves.
- No endpoint is migrated purely because it “looks related.”

---

### Phase 5: Extract shared service modules where duplication remains

**Objective:** Avoid solving duplication by proxying forever.

**Pattern:**
If both Olympus backend and Pantheon webui need the same business behavior, extract that behavior into Pantheon-owned shared modules rather than keeping two implementations.

**Potential shared modules:**
- Olympus user/bootstrap service
- Theme service
- Feature flag service
- Athenaeum read/walk/search service
- Notification service
- Session aggregation service

**Rule:**
- Shared module = business logic
- Backend/webui route = transport layer only

---

### Phase 6: Remove dependency on upstream Hermes auth bypasses

**Objective:** Make local `hermes_cli/web_server.py` edits unnecessary for Olympus/Pantheon behavior.

**Files:**
- `hermes-agent/hermes_cli/web_server.py`
- `hermes-agent/hermes_cli/dashboard_auth/middleware.py`
- local Pantheon integration code that currently assumes bypassed auth

**Steps:**
1. Enumerate every Olympus/Pantheon feature that currently relies on loosened Hermes dashboard auth.
2. Repoint those features to backend- or webui-owned routes.
3. Remove/retire the local upstream Hermes route/auth customization.
4. Verify live behavior with the customization disabled.

**Success condition:**
Upstream Hermes can update without Pantheon/Olympus losing core UI functionality due to route-gate drift.

---

## Route Ownership Matrix

### Canonical now or soon
- `Olympus backend`: `/api/auth/*`, `/api/users`, `/api/theme`, `/api/feature-flags`, `/api/athenaeum/*`, `/api/stream/*`, `/api/olympus/*`

### Pantheon-owned for now
- `Pantheon webui`: `/api/models`, `/api/profile/switch`, `/api/sessions`

### Migrate later after contract decision
- `/api/notifications/poll`
- `/api/ideas`

### Must leave upstream Hermes critical path
- any Olympus/Pantheon route currently depending on local dashboard auth bypass behavior

---

## Risks

### Risk 1: Two auth systems remain half-merged
**Bad outcome:** duplicated login/session bugs, weird bootstrap inconsistencies.

**Mitigation:** pick one auth edge per phase and document it.

### Risk 2: Proxy layer becomes permanent mud
**Bad outcome:** Pantheon webui remains a fat duplicate forever.

**Mitigation:** use proxies only as temporary transport adapters; move business logic into shared modules/backend ownership.

### Risk 3: Session behavior regresses
**Bad outcome:** pinned/archived/profile-scoped session UX breaks.

**Mitigation:** treat `/api/sessions` as a special case; do not migrate it casually.

### Risk 4: Upstream Hermes still leaks into routing
**Bad outcome:** updates still stomp local behavior.

**Mitigation:** explicit shutdown plan for Hermes custom auth/public-path dependence.

---

## Implementation Order Recommendation

1. Write route ownership ADR / this plan
2. Pick auth direction (A2 intermediate recommended)
3. Consolidate `/api/auth/me`, `/api/users`, `/api/theme`
4. Consolidate backend-native Olympus service routes
5. Extract shared modules for duplicated behavior
6. Design ownership for sessions/models/profile-switch
7. Remove upstream Hermes dependency
8. Only then revisit/update the live Hermes branch confidently

---

## Verification Checklist

- [ ] Olympus-facing routes no longer require local Hermes dashboard auth bypass behavior
- [ ] `/api/auth/me`, `/api/users`, `/api/theme` have one canonical implementation each
- [ ] Olympus backend and Pantheon webui are not both owning the same business logic long-term
- [ ] Session pinning remains a UI/Pantheon concern, not Hermes-core state
- [ ] Telegram and TokenJuice tracking patches remain out of scope
- [ ] Upstream Hermes updates no longer threaten Olympus/Pantheon core route behavior

---

## Recommended Follow-up Tasks for Marvin

1. Audit all frontend callers of duplicated endpoints.
2. Choose and implement the auth transition strategy.
3. Normalize response shapes for `/api/auth/me`, `/api/users`, `/api/theme`.
4. Convert Pantheon webui duplicates into thin proxies or remove them.
5. Extract shared service modules before tackling sessions/models/profile-switch.
6. Produce a second focused design note for `/api/sessions` ownership and pinning semantics.

---

## Paths to inspect during implementation

- `/home/konan/pantheon/services/olympus-backend/main.py`
- `/home/konan/pantheon/webui/api/routes.py`
- `/home/konan/pantheon/webui/api/auth.py`
- `/home/konan/pantheon/webui/api/models.py`
- `/home/konan/pantheon/webui/api/profiles.py`
- `/home/konan/pantheon/hermes-agent/hermes_cli/web_server.py`
- `/home/konan/pantheon/hermes-agent/hermes_cli/dashboard_auth/middleware.py`
- `/home/konan/pantheon/hermes-agent/hermes_cli/dashboard_auth/public_paths.py`

---

## Design Addendum: Shared Olympus Service Layer + Optional MCP Facade

### Why add this layer
The consolidation plan above fixes route ownership, but route cleanup alone does not guarantee long-term stability. If Pantheon webui and Olympus backend continue to carry duplicated business logic, then the system remains fragile even after upstream Hermes is removed from the critical path.

**This addendum introduces a stronger boundary:**
- **Shared service layer** = canonical business logic for Olympus/Pantheon operations
- **Olympus backend** = canonical browser-facing HTTP API for Olympus
- **Pantheon webui** = thin compatibility adapter during migration
- **Optional MCP facade** = agent/internal capability surface over the same shared service logic
- **Upstream Hermes** = consumer/integration surface only, not ownership layer

### Core design principle
Do **not** make MCP the public browser transport. Browsers and frontend clients should continue speaking normal HTTP to Olympus backend. MCP should exist only as an internal capability layer for agentic access and shared service operations.

**Good pattern:**
- frontend → HTTP → Olympus backend
- Olympus backend → shared service modules
- Pantheon webui → proxy or shared service modules during transition
- Hermes/gods/automation → MCP facade → same shared service modules

**Bad pattern:**
- frontend/browser → MCP semantics directly
- business logic duplicated once in HTTP handlers and again in MCP tools
- Pantheon webui remaining a permanent BFF with independent behavior

---

### Proposed ownership model

#### Layer 1 — Shared Olympus/Pantheon service modules (new canonical business layer)
Create Pantheon-owned Python modules for reusable business behavior. These modules should contain:
- storage access
- validation
- shaping/normalization rules
- authorization decisions that are independent of browser transport
- domain-specific operations for Olympus/Pantheon data

**Candidate module boundaries:**
- `olympus_services/auth_bootstrap.py`
- `olympus_services/users.py`
- `olympus_services/theme.py`
- `olympus_services/feature_flags.py`
- `olympus_services/athenaeum.py`
- `olympus_services/stream_metrics.py`
- later: `olympus_services/notifications.py`
- later: `olympus_services/ideas.py`
- later/special case: `olympus_services/session_aggregation.py`
- later/special case: `olympus_services/models_catalog.py`

**Rule:** shared modules know nothing about FastAPI request objects, webui cookie/session wrappers, or MCP schemas. They only know domain inputs and domain outputs.

#### Layer 2 — Olympus backend (canonical HTTP facade)
Olympus backend should be the single public browser-facing owner for Olympus routes. Its job should be:
- auth edge handling for Olympus HTTP clients
- request/response serialization
- calling shared service modules
- stable HTTP contract ownership

Olympus backend should **not** re-implement business logic already present in the shared modules.

#### Layer 3 — Pantheon webui (temporary adapter)
Pantheon webui should shrink toward:
- compatibility proxies
- profile/session-specific UI aggregation that has no clean backend abstraction yet
- transitional route shims while callers migrate

Pantheon webui should **not** remain a second business-logic owner for users/theme/auth bootstrap if those domains have been moved into the shared service layer.

#### Layer 4 — Optional MCP facade (internal capability surface)
An MCP server is viable and useful **after** the shared service modules exist. The MCP layer should expose operations such as:
- `get_auth_bootstrap`
- `list_users`
- `create_user`
- `get_theme`
- `set_theme`
- `get_feature_flags`
- `set_feature_flags`
- `athenaeum_walk`
- `athenaeum_read`
- `athenaeum_search`
- `get_stream_metrics`
- later: `list_notifications`
- later: `list_ideas`
- later with caution: `list_sessions`, `get_models`, `switch_profile`

**Important:** MCP should wrap the same shared service modules used by HTTP, not implement parallel logic.

---

### What should stay HTTP-first vs MCP-optional

#### HTTP-first now
These should be owned by Olympus backend as normal browser-facing APIs first:
- `/api/auth/*`
- `/api/users`
- `/api/theme`
- `/api/feature-flags`
- `/api/athenaeum/*`
- `/api/stream/*`
- `/api/olympus/*`

#### MCP-optional after service extraction
These are good candidates for internal MCP exposure once the service modules exist:
- auth bootstrap read operations
- user management
- theme/feature-flag reads and writes
- Athenaeum reads/searches
- stream metrics and graph summaries
- notification reads
- idea reads/writes

#### Keep out of MCP until semantics are cleaner
These currently carry too much UI/runtime coupling to rush into MCP:
- `/api/sessions`
- `/api/models`
- `/api/profile/switch`

They may eventually gain MCP exposure, but only after the underlying ownership and abstractions are stabilized.

---

### Migration order for this design

#### Step A — Extract easy shared services first
Move duplicated business logic for:
- auth bootstrap (`/api/auth/me`)
- users
- theme
- feature flags

**Success condition:** backend and webui can both call the same service module instead of owning separate implementations.

#### Step B — Make Olympus backend the only canonical HTTP owner
Once shared services exist, route all browser-facing Olympus requests through Olympus backend. Pantheon webui can proxy temporarily but should stop shaping business logic.

#### Step C — Extract backend-native service domains
Move Athenaeum/stream/Olympus feature logic behind shared modules where useful, keeping backend as HTTP owner.

#### Step D — Add MCP facade only where it pays for itself
Once shared services are stable, add an MCP server or MCP tool surface that calls those modules. Start with read-heavy, low-ambiguity operations before mutating/sessionful operations.

#### Step E — Revisit hard runtime-coupled domains
Only after the above is stable, design proper ownership for:
- sessions
- models catalog/runtime
- profile switching
- notification delivery semantics
- idea workflows if still split

---

### Plugin vs MCP vs shared-module guidance

#### Use a Hermes plugin when:
- a temporary compatibility shim is needed inside Hermes runtime
- you must register helper tools/hooks without editing upstream files
- you need a short-term bridge while the real service boundary is being built

#### Use MCP when:
- multiple agentic consumers need the same capability surface
- you want gods/automation/backends to share one operation contract
- the operation is domain logic, not browser transport

#### Use shared Python modules when:
- the main problem is duplicated business logic inside one deployable system
- you want the simplest durable solution first
- HTTP and MCP should both call the same implementation

**Recommendation:** build the shared service modules first, then layer MCP on top only where useful. Do not force MCP to be the first move.

---

### Auth and boundary cautions
1. **Do not collapse browser auth and agent auth into one fuzzy layer prematurely.**
2. **Do not let MCP become a bypass around permission checks.** Shared service modules should accept explicit actor/context inputs where authorization matters.
3. **Do not move profile switching into a generic service until profile-runtime semantics are documented.**
4. **Do not proxy forever.** Each compatibility proxy needs a retirement target.
5. **Do not preserve Olympus behavior by re-creating `web_server.py` hacks in a prettier place.** The goal is ownership cleanup, not cosmetic relocation.

---

### Concrete deliverables this addendum implies
1. Create a new shared services package under the Pantheon codebase for Olympus/Pantheon business logic.
2. Refactor `/api/auth/me`, `/api/users`, `/api/theme`, and `/api/feature-flags` to use those shared services.
3. Reduce Pantheon webui handlers for those domains to proxy/adapter logic only.
4. Keep a follow-up design note specifically for `/api/sessions`, `/api/models`, and `/api/profile/switch`.
5. After service extraction, decide whether to implement an MCP facade as:
   - a dedicated MCP server process, or
   - a Pantheon-local MCP service module exported through Hermes native MCP config.
6. Verify that disabling local upstream Hermes auth/public-path customizations no longer breaks Olympus flows.

---

### Decision summary
- **Yes:** a plugin can help as a bridge.
- **Yes:** an MCP-backed connections/capabilities layer is viable.
- **No:** plugin alone should not be the permanent API ownership solution.
- **No:** MCP should not replace the normal browser-facing HTTP backend.
- **Best target state:** shared Olympus/Pantheon service layer, Olympus backend as canonical HTTP facade, optional MCP facade for internal/agent consumers, Pantheon webui reduced to thin adapters where still necessary.

---

## Final recommendation

**Strong recommendation:** merge ownership around Olympus backend, not around upstream Hermes and not by preserving duplicate Pantheon webui logic forever. Use Pantheon webui as a migration adapter where necessary, keep sessions/profile/model orchestration Pantheon-owned until a cleaner shared abstraction exists, and remove upstream Hermes from the Olympus critical path. Extend that architecture with a Pantheon-owned shared service layer first; only then add an MCP facade where shared agent/internal capabilities genuinely benefit from it.
