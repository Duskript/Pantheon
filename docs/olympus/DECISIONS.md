# Olympus UI Decisions

> Raw running decision log for Olympus UI. Capture first, organize later.
>
> Olympus UI is the planned clean, packaged, themeable, feature-flagged, multi-user frontend shell around Hermes Agent. Pantheon is one deployment/theme, not the only product shape.

## 2026-05-22 — Foundational Product Shape

### Product framing

- Olympus UI should be a packaged frontend shell around Hermes Agent, not a hardcoded Pantheon-only UI.
- Pantheon/god terminology should be a theme/deployment layer, not mandatory client-facing terminology.
- The same general shape and UX should be maintainable across deployments while allowing branding, images, colors, terminology, and features to change.
- Client deployments may hide advanced controls that are useful to Konan/operator users.

### Themeability and branding

- Olympus UI should be extremely themeable.
- Use global design tokens / global CSS variables for core visual identity:
  - colors
  - logos/images
  - typography
  - backgrounds
  - glow/effects
  - spacing/radius/density
- Swapping branding should not require editing component code.
- Pantheon mythology terms should be configurable via terminology mapping.
  - Example: `god` can display as `Assistant` for clients.
  - Example: `boon` can display as `Document`, `Output`, or another client-friendly term.

### Feature flags and personalization

- Olympus UI needs easy feature/function toggles.
- Some users/deployments should not see advanced features such as mid-conversation model switching.
- Example: a simple client/grandma user likely does not need a model picker.
- Konan/operator users do need advanced controls like model picker, provider settings, tools, diagnostics, etc.
- Feature visibility should be configurable by deployment and role.
- Frontend feature hiding is UX only; backend permissions must enforce authority.

### Configuration backend / admin surface

- Olympus should include a configuration/admin area, likely at a specific route such as `/admin`.
- Admin/config UI should make personalization quick and easy with toggles and simple controls.
- Admin surface should manage:
  - branding
  - theme/colors/images
  - feature flags
  - visible navigation items
  - agents/profiles exposed to users
  - model availability/defaults where permitted
  - role/user access
- Admin surface should be separate from normal end-user flow.

## 2026-05-22 — Multi-user Model

### Keep multi-user simple, but do not paint into a corner

- Multi-user support is required for Olympus UI on a single install.
- Initial implementation should stay simple and likely remain simple for a while.
- Architecture must avoid choices that block later expansion.

### Human users vs Hermes profiles

- Human user profiles and Hermes/agent profiles are distinct concepts.
- Olympus user profile = human account.
- Hermes/agent profile = runtime assistant/persona/domain profile.
- Keep naming clear to avoid confusion.

### Session ownership and profile tagging

- Every session must belong to a human user.
- Every session must also be tagged by an agent/profile.
- Profiles are a primary sorting method for finding sessions.
- Profile tagging keeps conversations from getting lost and keeps work in the right domain.
- Conceptual minimum fields:
  - `session.user_id`
  - `session.profile_id` or `agent_profile_id`
  - `session.hermes_session_id`
  - timestamps/title/etc.

### Shared vs private resources

- Shared/private resource model is important but currently **TBD**.
- This includes documents/boons, session visibility, shared knowledge, and user-owned outputs.
- Mark as open design area; do not prematurely lock the model.

### User preferences

Human user profile should include at least:

- display name
- avatar
- user color
- density preference: compact vs comfortable
- preferred language

Color picker UX:

- Should be simple and familiar.
- Offer ~six primary color presets.
- Also offer a custom option.
- Custom color selection should use familiar RGB/gradient-style picker UX rather than requiring hex-code knowledge.
- Hex codes can exist under the hood but should not be the main user-facing interaction.

Accessibility settings:

- Mark as **discussion needed**.
- Potential examples to define later:
  - text size
  - reduced motion
  - high contrast
  - dyslexia-friendly font
  - screen-reader/keyboard preferences

Preferred language:

- Low cost to include; include it in the user profile model.

### Role-based feature access

- Agree that feature access should be role/config based.
- Same install can expose different surfaces to different users.
- Example:
  - normal user: simple chat/history/documents
  - power user/operator: model picker, tools, diagnostics, provider settings

### Agent/profile visibility

- Olympus should support showing/hiding agents that exist on the install.
- Users should only see the agents/profiles they are allowed to access.
- This supports both Pantheon-style multi-god installs and client installs with only one or a few assistants exposed.

### Memory scoping

- Memory scoping is important but currently **TBD**.
- Need later design for how user memory, agent/profile memory, deployment memory, and shared memory interact.
- Do not overcommit yet.

### Logs and auditability

- Olympus needs logs.
- Audit/event logging should exist for important system actions.
- Examples likely include:
  - user login/logout
  - config changes
  - feature flag changes
  - model/provider changes
  - agent/profile visibility changes
  - exports/shares
  - admin actions

### Foundation

- **assistant-ui** is the chosen frontend foundation for Olympus UI.
- Evaluation done: assistant-ui fits the AI-chat-native requirements (streaming, tool calls, markdown rendering, multi-model) without reinventing wheels.
- Decision made before Phases 1–4 were completed — this overrides the original "Phase 5" foundation choice order. assistant-ui is locked in; the remaining planning phases adapt around it.

## Open Questions / TBD

- Exact shared/private resource visibility model.
- Memory scoping model.
- Accessibility settings list and UX.
- Exact role names and permissions.
- Whether Olympus is standalone repo, monorepo package, or initially inside Pantheon.
- Exact config schema format: YAML, JSON, database-backed, or hybrid.
- Auth method for MVP: local accounts, invite links, OAuth, magic links, etc.

## Working Principle

Capture decisions in this document as they happen. Organize later. Avoid losing product/UX decisions in chat history.

---

## 2026-06-14 — Conductor v2 is the canonical reaction engine; n8n deprecated

**Decision:** Conductor v2 ships as the single source of truth for Pantheon event routing. v1 stays retired. n8n is being sunset in favor of TheoForge (visual editor on top of Conductor v2).

**Evidence:**
- v2 is a single-process daemon with 5 modules (engine, gateway, nats, webhook, delivery) wired by `service.py`
- Test suite: 90/90 passing, all loading real production YAML from `~/pantheon/conductor/{rules,workflows}/`
- Zero `hermes-agent/` imports in v2/ — verified by grep. Decoupled from any Hermes refactor.
- Spec 8.1: all 5 handling modes (`log_only`, `notify`, `notify_and_log`, `approval_required`, `route_on_approval`) implemented; unmatched external events default to `approval_required`.
- Spec 8.4: workflow versions are locked per instance.
- Spec 8.5: Conductor routes, gods don't — verified by `TestHandoffRouting`.
- Live smoke test passed: daemon started, gateway connected (Thoth :8642), webhook received, unmatched event quarantined to `pending/_quarantine/`.
- systemd unit installed at `~/.config/systemd/user/conductor-v2.service` (not enabled — manual start until we have a day of clean runs).

**DO NOT:**
- Re-add `import hermes_cli` or any hermes-agent import to v2/ — keep it decoupled.
- Add new NATS implementations, webhook handlers, or god-spawn paths outside `v2/`. v1's sprawl is why we're here.
- Auto-enable the systemd unit. Test manually for a week first.
- Modify production rules/workflows without running the test suite — tests are the contract.
