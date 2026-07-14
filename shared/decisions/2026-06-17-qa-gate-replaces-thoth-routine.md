# 2026-06-17 — QA Gate: GPT-5.5 Ponytail replaces Thoth as routine

**Status:** LOCKED (operator-signed: Cyber/Konan, Telegram 2026-06-17)
**Scope:** All Pantheon code-producing tasks going forward.
**Replaces:** SOUL.md rule #2 ("QA Gate Rule") of the operator-locked 10 ruleset.

## Decision

The routine QA gate for Marvin/Iris code production is now the **GPT-5.5 Ponytail QA gate**, invoked by Hephaestus in an isolated one-shot `hermes chat` session pinned to `openai-codex / gpt-5.5`.

**New flow:**

```
Marvin/Iris code
   ↓
Hephaestus tier-1 (verify + engineering review, in-session)
   ↓
GPT-5.5 Ponytail QA gate (isolated one-shot chat)
   ↓
   ├── PASS                  → ACCEPT (kanban: tier-1 + Ponytail gate)
   ├── PASS_WITH_WARNINGS    → ACCEPT with warnings OR RETURN with Must Fix
   ├── FAIL                  → RETURN_TO_MARVIN with Must Fix list
   └── ESCALATE              → ESCALATE (Thoth, Hermes, or operator)
```

**Thoth's new role:** Escalation and release-gate intelligence only. Invoked when:
- Ponytail verdict is `ESCALATE`
- Operator specifically requests a Thoth review
- Release-gate work (Phase 5+, public releases, schema migrations)

**Skills:**
- `gpt55-ponytail-qa` (location: `~/.hermes/skills/pantheon/gpt55-ponytail-qa/SKILL.md`)
- Template: `templates/hephaestus-marvin-qa-gate-prompt.md`

## Rationale

- **Underused ChatGPT subscription.** Konan is paying for GPT-5.5 via OpenAI Codex; routine builds are a high-leverage way to use that budget without adding new spend.
- **Speed.** One-shot isolated review is faster than spinning up a Thoth session for every routine change.
- **Adversarial review at the right layer.** Ponytail is deliberately anti-bloat, anti-overengineering, anti-weak-UX. That's the right lens for "should this ship?" — exactly what the routine gate needs.
- **Thoth's strengths preserved.** Thoth is excellent for synthesis, product judgment, cross-system reasoning, escalation review. Demoting Thoth from "default" to "escalation" puts his strongest capability where it actually pays off.

## Authoritative scope

- This decision locks the QA Gate Rule going forward.
- In-flight kanban tasks created before 2026-06-17 retain their original Tier-1 + Tier-2 structure. New tasks created after this date follow the new flow.
- The active `conductor-ui v1.2` chain has ~25 Tier-2 (Thoth) tasks queued. Per default, they continue. Konan may explicitly prune them if desired.

## Cross-references

- SOUL.md (operator-locked 10 ruleset, rule #2) — needs update
- `~/.hermes/skills/pantheon/gpt55-ponytail-qa/SKILL.md` — canonical skill
- `pantheon/shared/decisions/2026-06-16-hephaestus-rework-complete.md` — predecessor
- Ichor event `id=68593` — Hermes's original decision record (now superseded by operator sign-off)

## Implementation status

- [x] Decision logged
- [ ] SOUL.md rule #2 updated
- [ ] Skill loaded into active dispatch path
- [ ] First build gated with Ponytail (planned: Phase 4.1 PaletteItems when Marvin ships)