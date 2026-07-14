---
title: "Skills — what they are and how to invoke them"
last_verified: 2026-06-19
---

# Skills — what they are and how to invoke them

A **skill** in Pantheon is a markdown file (`SKILL.md`) that gives a god specialized knowledge for a specific task. Skills are the *loadable knowledge* of the system.

## What a skill is

A skill is a single file with:

- **YAML frontmatter** — name, description (with trigger phrases), optional metadata
- **Markdown body** — the actual instructions, frameworks, or procedures

Example:

```yaml
---
name: gtm-strategy
description: "Create a go-to-market strategy covering marketing channels, messaging, success metrics, and launch timeline. Use when planning a product launch, creating a GTM plan from scratch, or defining a launch strategy for a new market."
---

# GTM Strategy

## Overview
Create a comprehensive go-to-market strategy...

## When to Use
- Planning a product launch
...
```

That's it. No code, no compilation, no deployment. Drop the file in a recognized skills directory and the god can load it.

## Where skills live

Pantheon finds skills in three places, in this order:

1. **Profile skills** — `~/.hermes/profiles/<profile>/skills/<skill-name>/SKILL.md`
2. **Hub skills** — `~/.hermes/skills/<skill-name>/SKILL.md`
3. **External skill directories** — listed in `config.yaml` under `skills.external_dirs`

For the operator, this means:

- Skills installed at the **hub level** (`~/.hermes/skills/`) are available to every profile
- Skills installed at the **profile level** are visible only to that profile
- Profile-level skills override hub-level skills with the same name (use this for per-god specialization)

## How skills are loaded

Skills are **lazy-loaded** by the Agent Skills spec. This means:

- The god's skill list is always in the system prompt
- The full skill body is loaded **on demand** when the trigger matches
- Skills don't bloat the context window

The trigger mechanism is **semantic**, not exact-match. The god looks at the user's request and the `description` field of each skill. If the description contains trigger phrases that match the request, the god loads the skill body.

**This is why the `description` field is the most important part of a skill.** It's the entire trigger mechanism. See [Making a Skill](04-making-a-skill.md) for how to write good descriptions.

## How to invoke a skill

### Method 1 — Trigger naturally (the default)

Just ask the god to do the thing. The skill loads if the description matches.

```
> Help me draft a Lean Canvas for our new product
```

If a `lean-canvas` skill exists with a matching description, the god loads it and follows its instructions.

### Method 2 — Invoke by name (force-load)

If you know the skill name and want to guarantee it loads, use the slash syntax:

```
> /lean-canvas
```

Or the qualified form:

```
> /plugin-name:skill-name
```

The second form is useful when multiple plugins ship skills with the same name.

### Method 3 — Reference in a build plan

In a build plan (the 13-section format), reference skills in the "Tools" section. The plan executor loads them before running the step.

## Skills vs commands

Some plugins (like `phuryn/pm-skills`) ship both:

- **Skills** — noun/concept. Loaded on demand. The agent auto-selects based on description.
- **Commands** — verb/workflow. Triggered by `/command-name`. Run as a multi-step process.

Use skills when the agent should *consider* the framework. Use commands when you want a *specific procedure* executed.

## What skills are NOT

- **Not code.** Skills are markdown. They don't run.
- **Not API calls.** Skills are knowledge. The god reads them and applies them.
- **Not plugins themselves.** A plugin is a *collection* of skills + commands + manifest. A skill is one file.

## Anti-patterns

- **Don't write a skill that says "do everything."** A vague description means the skill never triggers, or triggers when it shouldn't. Be specific.
- **Don't duplicate an existing skill.** If a similar skill exists, update it instead of creating a new one.
- **Don't make a skill a one-off procedure.** One-off procedures belong in scripts, not in skills.
- **Don't put secrets in a skill.** Skills are shared. Secrets belong in the environment or a secrets manager.

## When to make a new skill

You have a pattern you've used 3+ times.
You want a god to *think* a specific way about a specific topic.
You want a new operator to have your hard-won knowledge without learning it the hard way.

If it's a one-off, don't make a skill. If it's a procedure (steps to execute), make a script. If it's knowledge (how to think), make a skill.

## See also

- [Making a Skill](04-making-a-skill.md) — how to author a new skill
- [Using a Skill](05-using-a-skill.md) — frontmatter best practices
- [Building a God](06-building-a-god.md) — when to escalate from skill to new god
