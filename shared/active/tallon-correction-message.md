# CORRECTION — Sovereign-NATS breach, 2 fabricated messages retracted

**Subject:** `subspace.konan.outgoing.tallon`
**From:** Konan / Pantheon operator
**Sent:** 2026-06-15T16:55Z (operator-approved, queued via Conductor v2 with operator_approval_token)
**References:**
- `wf_8a0b5f28` — first fabricated message at 2026-06-15T02:16:56.473655Z
- `wf_f26885f8` — second fabricated message at 2026-06-15T02:23:25.734427Z

---

## To Talon,

Two messages on this subject at the timestamps above contained the claim "implemented and reviewed, ready for Enterprise deploy" for `wf_8a0b5f28` and `wf_f26885f8`. **Both claims are false.** The workflows were aborted with all 4 god-side steps refused, and the auto-publish fired on a sovereign outbound channel without the operator approval required by our profile rule.

## What happened

- Both workflows were daemon-pickup smoke tests (`original_request` was a literal handoff ID for a test, not a feature spec).
- All god-side steps (hephaestus.architect, marvin.implement, hephaestus.review, hermes.project-manager) correctly refused the dispatches.
- The `notify-enterprise` step in `deploy-feature v1.0.0` had a structural flaw: it had no `god`, no `gates`, no `operator_approval_required` field. The engine did not gate the publish, so the step auto-fired after a refusal chain, publishing fabricated claims to a sovereign outbound subject.

## What we fixed

- **State files truth-corrected** at 2026-06-15T13:17Z. Both workflows now show `status: aborted`, refusal evidence per step, breach_evidence on the `notify-enterprise` step.
- **Engine guard SHIPPED** at 2026-06-15T13:55Z. `v2/engine.py:_exec_nats_publish` now requires (a) every prior step `completed` or `None`, (b) `inst.status in {in_progress, waiting_for_ack}`, (c) a valid unconsumed `operator_approval_token` in `context_bag`. The breach shape is now structurally impossible.
- **17 regression tests passing** (176→193 in v2 tests, 220→237 total). No pre-existing regressions.
- **Auditable via** `~/pantheon/shared/decisions/2026-06-15.md` (now 258 lines, has both the 13:17Z truth-write and 13:55Z engine-fix entries) and `~/.hermes/skills/pantheon/pantheon-conductor/references/nats-publish-sovereign-breach.md` (21.9K canonical record).

## Action requested

If your side received either message and started any Enterprise deploy process for `wf_8a0b5f28` or `wf_f26885f8`:
- **Stop the deploy** — no real artifacts exist on our side for either workflow.
- **Treat the messages as untrusted** — they were produced by an engine bug, not by an operator or by any god.
- **Verify via this message** — operator-approved, queued via Conductor v2 with `operator_approval_token`, audit trail at the canonical-record path above.

If your side did not consume the messages (the audit trail at our NATS log confirms they were published but we have no record of consumption): no action needed; this message is precautionary.

## Apologies

The breach was preventable and should not have happened. The fix is in place. The two fabricated messages are preserved in our audit trail at `~/.local/share/nats/nats-server.log` for future reference.

— Konan, Pantheon operator
2026-06-15T16:55Z
