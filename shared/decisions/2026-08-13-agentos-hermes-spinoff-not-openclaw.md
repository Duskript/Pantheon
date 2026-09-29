# 2026-08-13 — AgentOS-Hermes Spinoff, Not OpenClaw Adoption

**Decision:** Pantheon will not adopt OpenClaw. If AgentOS is useful, the path is a spinoff/fork of AgentOS patterns and/or MIT-licensed code with Hermes Agent/Pantheon as the runtime underneath, replacing the OpenClaw dependency boundary.

**Rationale:** Konan explicitly clarified the intended direction after the AgentOS evaluation: “I have no intention of adopting openclaw. So it would be more of a spinoff/fork using Hermes agent instead.” This preserves the useful AgentOS operator-layer ideas — control plane, capability matrix, operations console, worker/god profiles, account/session policy — while keeping Pantheon grounded in its existing Hermes, Ichor, Conductor, Olympus, gateway, and god-profile architecture. It also avoids taking on OpenClaw’s runtime coupling and unclear license metadata as an architectural dependency.

**Alternatives considered:**
- Adopt AgentOS + OpenClaw as a runtime stack: rejected — Konan does not want OpenClaw adoption, and Pantheon already has runtime primitives.
- Use AgentOS only as a design reference: partially accepted — still useful, but the clarified path allows a fork/spinoff if MIT-licensed AgentOS code accelerates a Hermes-native operator layer.
- Build a Pantheon operator console entirely from scratch: still viable, but lower leverage if AgentOS UI/control-plane structures can be reused safely under MIT.

**Evidence:**
- Operator directive in Discord, 2026-08-13: “I have no intention of adopting openclaw. So it would be more of a spinoff/fork using Hermes agent instead.”
- Thoth research report: `/home/konan/athenaeum/Codex-God-thoth/research/agentos-pantheon-eval/report.md`
- AgentOS README license section: `README.md` lines 488–490 says `MIT`.

**Reversibility:** easy — this is an architecture direction and dependency constraint, not an implemented migration.

**Decided by:** Konan on 2026-08-13

**Operator sign-off:** konan

**Affected:**
- Future Pantheon operator-console / Olympus / Mission Control build specs
- `/home/konan/athenaeum/Codex-God-thoth/research/agentos-pantheon-eval/report.md`
- Any future AgentOS fork/spinoff feasibility plan
- Hermes Agent integration boundary design
