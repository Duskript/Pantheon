---
title: "Skills — what they are and how to invoke them"
last_verified: 2026-09-01
---

# Skills — what they are and how to invoke them

A **skill** in Hermes/Pantheon is a Markdown file named `SKILL.md` that gives an agent specialized knowledge or a repeatable procedure. Skills are loadable instructions; they are not Python packages or MCP tools. The behavior described here was checked against the current Hermes skill scanner and prompt builder on 2026-09-01.

## What a skill is

A skill package normally contains:

- **YAML frontmatter** — at minimum `name` and `description`; optional metadata and platform/environment conditions
- **Markdown body** — the instructions, framework, or procedure
- **Optional support files** — `references/`, `templates/`, `scripts/`, or `assets/`

Example:

```yaml
---
name: gtm-strategy
description: "Create a go-to-market strategy covering channels, messaging, metrics, and launch sequencing. Use when planning a product launch or entering a new market."
metadata:
  version: 1.0.0
  tags: [strategy, product]
---

# GTM Strategy

## Procedure
Create the strategy, validate the assumptions, and record open questions.
```

Drop the package in a recognized skills directory; no Python registration step is required.

## Where skills live

For the active Hermes profile, the scanner searches the profile's local skills directory first, then any external directories configured under `skills.external_dirs`:

1. **Active profile skills** — `$HERMES_HOME/skills/<skill-name>/SKILL.md` (for example `~/.hermes/profiles/thoth/skills/`)
2. **Configured external skill directories** — read-only directories listed in `skills.external_dirs`

For the default profile, `$HERMES_HOME/skills/` is normally `~/.hermes/skills/`. External directories are available for discovery but agent-created skills are written to the active local skills directory. When names collide, local skills take precedence.

## How skills are exposed and loaded

At session startup, Hermes builds a compact skills index containing eligible skill names and descriptions. Platform/environment filters can remove a skill from offer surfaces; an explicit load still works for a compatible or intentionally force-loaded skill.

The full body is **not automatically loaded merely because a description contains a matching phrase**. The description is a selection hint shown to the model. The model must explicitly load the skill through one of these paths:

- `skill_view(name="skill-name")` — load the body or a linked support file
- `--skills skill-name` — preload it for a new Hermes invocation
- `/<skill-name>` — use the generated slash command; this loads the skill and passes any trailing instruction along

This distinction matters: a skill can be visible in the prompt index without its full body being present in context. Installed skills and prompt-index changes normally take effect in a new session; use `/reset` when appropriate.

## How to invoke a skill

### Method 1 — Ask the agent to use it

If the skill is visible in the session's index, ask for the task and explicitly mention the skill when reliability matters:

```
> Use the gtm-strategy skill to draft a launch plan for our new product.
```

The agent should call `skill_view` before applying the instructions.

### Method 2 — Invoke by slash command

Installed Markdown skills become slash commands based on their directory name:

```
> /gtm-strategy Draft a launch plan for our new product
```

The runtime normalizes spaces and underscores to hyphens when building the command. Plugin-provided skills may use namespaced names such as `plugin:skill-name`; load those explicitly with `skill_view(name="plugin:skill-name")` rather than assuming a matching slash command exists.

### Method 3 — Load from a build plan or CLI

A build-plan executor can list the skill in its Tools section. For a new Hermes process, preload it with:

```bash
hermes chat --skills gtm-strategy -q "Draft a launch plan"
```

## Skills vs commands and MCP tools

- **Markdown skill** — loadable instructions for the agent
- **Slash skill command** — a runtime entry point that loads a Markdown skill
- **MCP tool** — callable code with a schema and side effects
- **Executable shared skill** — the separate Pantheon MCP `skill_run` surface; inspect it with Pantheon's `skill_list`/`skill_info` before execution

Use a Markdown skill when the agent should follow specialized knowledge. Use an executable tool or script only when an actual program must run.

## What skills are NOT

- **Not code by default.** A skill body is Markdown, although support files may contain executable scripts.
- **Not an API call.** Loading a skill changes the agent's context; it does not itself call an external service.
- **Not a plugin.** A plugin can bundle skills, commands, tools, and a manifest; a skill is one loadable package.
- **Not a durable fact store.** Put changing facts and events in the appropriate memory system, not in a skill body.

## Anti-patterns

- **Don't write a skill that says “do everything.”** Give it a narrow task and clear boundaries.
- **Don't assume phrase matching loads the body.** Use `skill_view`, a slash command, or `--skills` when the skill is required.
- **Don't duplicate an existing skill.** Search first; update the existing skill when it already covers the territory.
- **Don't make a one-off script into a skill.** Put one-off execution in a script; use a skill for reusable instructions.
- **Don't put secrets in a skill.** Skills can be shared and indexed; secrets belong in environment/configuration or a secrets manager.

## When to make a new skill

Create one when a pattern has been used successfully more than once, when an agent needs a reusable way of thinking about a narrow topic, or when hard-won procedure should be available to future operators. If it is only a one-off, keep it as a script or session note.

## See also

- [Using a Skill](05-using-a-skill.md) — frontmatter and packaging guidance
