# Pantheon — The God / Studio / Harness Model

> Source: Constitution Section 4
> Read this document when: defining, editing, or instantiating any god, studio, or harness file; working on the registry; or making decisions about agent behavior and routing.

---

## The Three Layers

**The God**
The god is the agent's identity, domain, and personality. It defines what the agent is responsible for and what it is not. Gods do not overlap. When something is outside a god's domain the harness routes it to the appropriate god rather than attempting to handle it.

**The Studio**
A studio is a specialization layer loaded on top of a god's base harness for a specific task domain. A god can have multiple studios. Studios inherit the god's base identity and add targeted knowledge context, scoped Mnemosyne partitions, and domain-specific guardrails. Not all gods have studios — studios exist only where meaningful specialization is required.

**The Harness**
The harness is the constraining structure that makes a god's output reliable and consistent. It defines exactly what the god does, what it refuses, what format it outputs, how it handles ambiguity, and how it routes out-of-scope requests. The harness is enforced at the definition level — not by convention or trust. A god without a harness is not a Pantheon agent.

---

## The Hierarchy

```
Sanctuary (the room you work in)
└── God (who you are talking to)
    └── Studio (what they are specialized for)
        └── Harness (the guardrails and routing rules)
            └── Mnemosyne Partition (the scoped knowledge)
```

---

## The Harness File Schema

Every god is defined by a YAML harness file stored in `/Athenaeum/Codex-Pantheon/harnesses/`. This file is the complete definition of the agent. Nothing about a god's behavior exists outside this file.

The `schema_version` field is required on every harness file. The loader validates this field first before reading anything else. A harness without a `schema_version` is treated as invalid and will not load.

```yaml
# Example: apollo-lyric-writing.yaml

schema_version: 1

name: Apollo
studio: Lyric Writing
sanctuary: The Studio

extends: apollo-base.yaml

driver: llm
model: gemma4
vault_path: /Athenaeum/Codex-SKC/sessions/
mnemosyne_scope:
  - /Athenaeum/Codex-SKC/lyrics/
  - /Athenaeum/Codex-SKC/style/
  - /Athenaeum/Codex-SKC/distilled/

identity: |
  You are Apollo operating in Lyric Writing mode.
  You assist exclusively with creative writing within
  the SKC artistic voice and style. You have access
  to the SKC creative corpus via Mnemosyne. You flag
  lyrical repetition from past work. You format output
  for Suno compatibility when requested.

receives:
  - Creative prompts
  - Mnemosyne corpus results
  - SKC style context

output:
  format: structured_sections
  fields: [section_type, content, notes]
  log_to_vault: true

routing:
  - if: it_or_infrastructure_topic
    then: route_to(hephaestus)
  - if: requires_vault_knowledge
    then: call(athena) → inject → continue
  - if: requires_corpus_search
    then: call(mnemosyne) → inject → continue
  - if: long_form_narrative_request
    then: suggest_sanctuary(calliope, long-form-fiction)
  - if: outside_all_known_domains
    then: escalate(zeus, reason="unclassified")

guardrails:
  hard_stops:
    - Never execute system commands
    - Never write outside SKC voice without explicit override flag
    - Never access Athenaeum directly — always via Athena or Mnemosyne
  soft_boundaries:
    - Flag if prompt feels outside established SKC themes
    - Flag if requested style conflicts with SKC style documents
    - Flag if imagery closely matches existing corpus content

failure_behavior:
  on_ambiguity: ask_one_clarifying_question
  on_out_of_scope: route_with_explanation
  on_hard_stop: return_refusal_with_reason
  on_mnemosyne_unavailable: proceed_without_corpus_note_limitation
```

---

## The Driver Field

Not every god requires a language model. The harness `driver` field defines what powers the god. This is a required field for all harness files.

```yaml
driver: llm       # Language model via Ollama — conversational and reasoning gods
driver: script    # Python or shell script — scheduled jobs, monitors, file watchers
driver: service   # Long-running process or API — vector DB interfaces, log pipelines
driver: hybrid    # Script with optional LLM calls for classification or summarization
```

| God | Driver | Reason |
|---|---|---|
| Zeus | llm | Orchestration requires reasoning |
| Apollo | llm | Creative output requires inference |
| Hephaestus | llm | Planning requires reasoning |
| Athena | llm | Knowledge retrieval and synthesis |
| Mnemosyne | hybrid | Vector DB operations via service driver, LLM for Staging classification and Codex proposal |
| Hestia | script | Health checks — pure monitoring logic |
| Demeter | script | Cron scheduler — pure job triggering |
| Kronos | service | Log pipeline — append only, no inference |
| Hades | hybrid | File consolidation logic + LLM for summarization |
| Hermes | hybrid | Inter-god message routing and handoffs |
| Hecate | llm | Intent classification requires inference |
| Hera | service | Config state management — no inference needed |
| Ares | script | Enforcement rules — deterministic logic only |
| Charon | script | File transfer pipeline — no inference needed |
| Prometheus | hybrid | Web search execution via script, result summarization for Mnemosyne staging uses LLM |

For `script` and `service` drivers the `model` field is omitted entirely. For `hybrid` drivers the `model` field is optional and only invoked for specific steps defined in the harness.

---

## Base and Studio Harness Inheritance

Base harness files define a god's core identity and default behavior. Studio harness files extend the base, adding only what differs. This prevents duplication and ensures the god's core identity stays consistent across all studios.

```
apollo-base.yaml           ← core identity, default routing, base guardrails
apollo-lyric-writing.yaml  ← extends base, adds SKC corpus scope and Suno awareness
apollo-poetry.yaml         ← extends base, adds poetry structure and meter awareness
apollo-short-fiction.yaml  ← extends base, adds narrative structure awareness
```

Merge rules:
- Child values always override parent values
- Routing rules: child rules are prepended to base rules (child routes evaluated first)
- Guardrails: hard stops are additive — child hard stops are never removed by a child harness
- Circular extends references must be detected and rejected at load time
- Missing harness files cause a hard failure — no silent fallback to defaults

---

## Harness Schema Versioning

Every harness file carries a `schema_version` integer. The loader validates this field before reading anything else. This ensures builders always know what schema version a file was written against and provides a clear migration path when the schema evolves.

### Schema Version Rules

- `schema_version` is a required field on every harness file — base and studio
- The current schema version is defined in the loader as `CURRENT_SCHEMA_VERSION`
- A file with no `schema_version` field is treated as invalid — same as a missing required field
- A file with a `schema_version` below current triggers a schema mismatch failure
- A file with a `schema_version` above current is a hard failure — do not attempt to load a file written for a future schema

### Loader Behavior on Schema Mismatch

When the loader detects a schema version mismatch it fails loudly. The Sanctuary does not open. The loader produces a structured error report:

```
⚠ Apollo harness failed to load — schema out of date

  File    : harnesses/apollo-lyric-writing.yaml
  Found   : schema_version 1
  Expected: schema_version 2

  Issues found:
  • 'failure_behavior' field is now required — missing from this harness
  • 'output.schema' has been renamed to 'output.fields'

  To fix automatically:
    ./scripts/migrate-harness.sh harnesses/apollo-lyric-writing.yaml

  To fix manually:
    Open apollo-lyric-writing.yaml in Hera → Harnesses
```

Iris surfaces this report to the user in readable form. Hera displays a warning badge on the affected harness in the harness list. Kronos logs the failure with the file path, version found, and version expected.

### Migration Script

`scripts/migrate-harness.sh` upgrades a single harness file from schema version N to N+1. It is run deliberately — never automatically. Each schema version increment ships with a corresponding migration transform in the script.

```bash
# Usage
./scripts/migrate-harness.sh harnesses/apollo-lyric-writing.yaml

# Output
Migrating apollo-lyric-writing.yaml from schema v1 to v2...
  + Added 'failure_behavior' field with default values
  ~ Renamed 'output.schema' to 'output.fields'
Migration complete. Review changes in Hera before reloading.
```

The script never overwrites the original silently — it writes the migrated version and logs what changed. The user reviews the result in Hera before the harness is reloaded. Kronos logs every migration run.

---

## The God Registry

Zeus loads the god registry at startup. The registry is a single YAML file listing all available gods, their base harness files, and their available studios.

```yaml
# pantheon-registry.yaml

gods:
  - name: Zeus
    harness: zeus-base.yaml
    type: orchestrator
    studios: none

  - name: Apollo
    harness: apollo-base.yaml
    type: conversational
    studios:
      - lyric-writing
      - poetry
      - short-fiction

  - name: Hephaestus
    harness: hephaestus-base.yaml
    type: conversational
    studios:
      - program-design
      - infrastructure-planning
      - project-scoping

  - name: Athena
    harness: athena-base.yaml
    type: conversational
    studios:
      - knowledge-query
      - research
      - vault-management

  - name: Hermes
    harness: hermes-base.yaml
    type: service
    studios: none

  - name: Mnemosyne
    harness: mnemosyne-base.yaml
    type: subsystem
    studios: none

  - name: Hades
    harness: hades-base.yaml
    type: subsystem
    studios: none

  - name: Hecate
    harness: hecate-base.yaml
    type: service
    studios: none

  - name: Hestia
    harness: hestia-base.yaml
    type: subsystem
    studios: none

  - name: Demeter
    harness: demeter-base.yaml
    type: subsystem
    studios: none

  - name: Kronos
    harness: kronos-base.yaml
    type: subsystem
    studios: none

  - name: Hera
    harness: hera-base.yaml
    type: subsystem
    studios: none

  - name: Ares
    harness: ares-base.yaml
    type: subsystem
    studios: none

  - name: Caduceus
    harness: caduceus-base.yaml
    type: conversational
    studios:
      - medical-research
      - health-reference

  - name: Calliope
    harness: calliope-base.yaml
    type: conversational
    studios:
      - long-form-fiction
      - worldbuilding

  - name: Prometheus
    harness: prometheus-base.yaml
    type: service
    studios: none
```

---

## Agent Types

| Type | Description | User Interaction |
|---|---|---|
| conversational | Primary user-facing agents | Direct |
| orchestrator | Routes and synthesizes — Zeus only | Direct |
| service | Event-driven, handles handoffs and routing | Indirect |
| subsystem | Background processes, never conversational | None |

---

## Hard Rules For This Layer

- Every god must have a harness file before it is instantiated.
- No god operates outside its defined domain. Out-of-scope requests are routed, not handled.
- Studio harness files always extend a base — they never define a god from scratch.
- The registry is the only authoritative list of available gods. If a god is not in the registry it does not exist.
- Hera holds the official state of all harness files. Changes to harness files are propagated by Hera.
- Hard stops in a harness are non-negotiable. They cannot be overridden by user instruction at runtime.
