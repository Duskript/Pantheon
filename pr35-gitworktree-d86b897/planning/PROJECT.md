# Pantheon — What Pantheon Is

> Source: Constitution Section 1
> Read this document when: understanding what Pantheon is, its design philosophy, or its core principles.

---

## Overview

Pantheon is a privacy-centric personal AI operating system organized around mythological archetypes. It is not a chatbot. It is not a wrapper around a language model. It is a multi-agent system where every capability has a defined domain, a defined harness, and a defined relationship to every other capability.

Each agent in Pantheon is called a god. Each god has a specific job and nothing else. Gods do not step outside their domain — they route to the appropriate god when something is outside their scope. This is enforced at the harness level, not by trust.

Pantheon is built for a single primary user. It is privacy-centric by design — local inference is preferred, external services are evaluated deliberately rather than assumed. External reach is handled exclusively through Prometheus, the designated API bridge, ensuring all outbound calls are intentional and traceable. Cloud models and external APIs are supported where they add genuine value; they are never the default.

The system is designed around flow-state preservation. It should require minimal user intervention during operation. Gods handle routing, handoffs, and escalation internally. The user should only need to interact with a small number of conversational gods directly. Everything else runs silently.

Pantheon is also a framework. Its god/studio/harness model is portable across mythological pantheons. A user may select Greek, Norse, Egyptian, or custom naming at setup. The underlying architecture does not change — only the names and identity prompts of each agent.

---

## Single User Architecture

Each Pantheon instance is scoped to a single user. The system is personalized at the instance level — one Athenaeum, one god registry, one set of Sanctuaries, all built around one person's needs and knowledge. This is intentional. Deep personalization and a shared multi-user knowledge base are architectural opposites. Pantheon chooses personalization.

Multiple users means multiple instances. Each instance is independent. There is no shared state between instances by default.

**Multi-user is a future consideration, not a current requirement.** When designing any component do not architect against multi-user support but do not build for it either. The flag for future implementation is: shared Codex access with user-scoped write permissions and a unified Mnemosyne partition with user metadata tagging. This is not fleshed out and should not be implemented until explicitly specified.

---

## Core Principles

- **Privacy centric.** Local inference via Ollama is preferred. External services and cloud models are supported where they add genuine value but are never assumed. All external calls route through Prometheus and are intentional and traceable.
- **Domain isolation.** Every god has a lane. No god operates outside it.
- **Athenaeum as truth.** The Athenaeum is the canonical knowledge store — a filesystem of markdown files organized into Codices by domain. It is tool-agnostic; Obsidian is one way to interact with it, not a dependency. All other data layers are derived from the Athenaeum and can be rebuilt from it.
- **Append only.** Logs, version history, and the vault never delete — they archive.
- **Harness enforced.** Agent behavior is defined by harness files, not by trust or convention.
- **Flow preservation.** The system minimizes interruption. Human-in-the-loop gates exist only where decisions genuinely require human judgment.
- **Self-feeding.** Normal usage of Pantheon generates the knowledge base. Working in the system is building the system.
