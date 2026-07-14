# Pantheon — Hard Rules

> Source: Constitution Section 12
> These rules apply to every component, every phase, and every builder. They are non-negotiable. They cannot be overridden by user instruction, time pressure, or convenience. If a rule conflicts with an implementation decision, the rule wins and the implementation changes.

---

## Architecture Rules

- **The Athenaeum owns the truth.** All other data layers are derived. If any derived layer is lost or corrupted it is rebuilt from the Athenaeum. The Athenaeum itself is never rebuilt from a derived layer.
- **Nothing is deleted.** Content is archived. Gods are archived. Sanctuaries are archived. Workflows are versioned. The only exception is explicit user-initiated permanent deletion with a confirmation gate.
- **Prompt isolation is absolute.** The global system prompt is never included in an active Sanctuary context. No exceptions, no overrides, no configuration flags.
- **Hard stops are pre-model.** Hard stops defined in a harness are evaluated before any model call. They never reach the model and never produce output that gets filtered after the fact.
- **Every god has a harness.** No god is instantiated without a valid harness file. A god definition that exists only in the registry without a harness file is incomplete and cannot be activated.
- **The registry is authoritative.** If a god is not in the registry it does not exist in Pantheon regardless of whether a harness file exists for it.
- **Hera holds config state.** All changes to harness files, Sanctuary configs, and the god registry are written through Hera. No component modifies these files directly.

---

## Build Rules

- **Phases are sequential.** Never begin a phase until the previous phase verification checklist is complete and version history is updated.
- **Scope is enforced.** Do not implement features from a future phase during an earlier phase build. Document future considerations as notes — do not build them.
- **One dependency rule.** Before introducing any new external dependency, confirm it cannot be solved with existing stack components. Every new package is a future maintenance burden.
- **pantheon-core stays separate.** All Pantheon-specific code lives in `pantheon-core/`. Nothing Pantheon-specific is written into Open WebUI's core frontend or backend directories.
- **The fork must build clean.** At any point in development a fresh clone must produce a working system with a single Docker Compose command. If it does not, fixing the build is the highest priority task.
- **Backup covers Pantheon and harnesses.** The backup script targets `~/Pantheon/` and the repo's `harnesses/` directory. Nothing else. Cloud backup encryption is a future consideration — unencrypted cloud backup is not permitted until encryption is implemented.

---

## Data Rules

- **Vault writes are real-time.** Session logging is never batched or buffered. Each turn is written immediately. A crash loses at most one turn in progress.
- **Codex partitions are metadata.** Mnemosyne partitions are logical scopes defined by metadata tags at embedding time. They are not separate database instances.
- **Inbox content is unindexed until processed.** Content in Codex-Inbox is not embedded into Mnemosyne until Mnemosyne classifies and routes it to a destination Codex.
- **Distillation preserves originals.** When Hades distills content, source files move to `/archive/asphodel/` via Charon — never deleted. The distilled version is a new file in the live Codex.
- **Live Codices are always clean.** Nothing lingers in a live Codex path after archiving. Charon moves immediately.
- **Archived content is not embedded.** Mnemosyne never embeds content in any archive tier. The ARCHIVE_INDEX.md is the only navigation layer for archived content.
- **Charon notifies Mnemosyne on every move.** Stale vectors are removed immediately when source files leave the live Codex. No stale embeddings accumulate.
- **Tartarus is the only true delete.** Content in Tartarus is purged after 3 months by The Fates. This is the sole exception to the append-and-archive principle. Nothing is restored from Tartarus.
- **The Fates run on a defined schedule.** No more frequently than nightly, no less frequently than weekly. Configurable. Runs alongside Hades' consolidation job by default.

---

## Communication Rules

- **All inter-god messages use the standard envelope.** No freeform god-to-god communication outside the defined message format.
- **All messages are logged.** Kronos receives every inter-god message. There is no silent communication between gods.
- **Background gods use Iris.** Background gods never write directly to an active session. Iris is the only path from a background god to the user.
- **Escalations are never empty.** Every escalation to Zeus includes a reason, context, and suggested routing target.
- **Timeouts are always defined.** No god waits indefinitely for a response. Every request has a `timeout_seconds` value.

---

## Security and Privacy Rules

- **External calls are intentional.** All outbound requests route through Prometheus. No god makes external network calls directly.
- **External calls require gate approval.** Session-level approval is the minimum for external calls. Silent external calls are not permitted.
- **No credentials in harness files.** API keys, passwords, and secrets are never stored in harness YAML files. They are stored in environment variables or a secrets manager.
- **Tailscale is the network boundary.** Pantheon services are not exposed to the public internet. Access is via Tailscale only.

---

## Version and Documentation Rules

- **Version history is append-only.** Existing version entries are never modified. New entries are always appended below existing ones.
- **The bootstrap entry is permanent.** The bootstrap rule in the Version History section is never deleted or modified regardless of how many versions accumulate below it.
- **Constitution updates precede implementation.** If a build decision requires changing the architecture, update the relevant constitution document before writing code.
- **The What Does Not Exist Yet list is maintained.** As components are built, STATE.md is updated to reflect actual current state. A builder should always be able to read STATE.md and know exactly what exists.
