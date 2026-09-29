---
title: "Using a Skill — frontmatter best practices"
last_verified: 2026-09-01
---

# Using a Skill — frontmatter best practices

This page covers the frontmatter fields used by the current Hermes skill scanner and loader, verified 2026-09-01. Frontmatter is indexed before the full body is loaded, so it controls discoverability, filtering, and metadata—not an automatic semantic execution trigger.

## Required frontmatter

```yaml
---
name: skill-name
description: What this skill does and when to use it.
---
```

`name` and `description` are the minimum useful fields. Keep the YAML valid and quote descriptions containing punctuation that could be interpreted as YAML syntax.

## The `name` field

Use the Agent Skills naming convention:

- 1–64 characters
- lowercase letters (`a-z`), numbers (`0-9`), and hyphens (`-`)
- no leading or trailing hyphen
- no consecutive hyphens
- keep the frontmatter name identical to the skill directory name

Valid: `cro`, `emails`, `ab-testing`, `pm-product-strategy`

Invalid: `Page-CRO`, `-page`, `page--cro`, `skill_name`

The scanner builds the `/skill-name` command from the directory name and uses the package directory when resolving a skill. Matching the frontmatter and directory names prevents confusing display and lookup behavior, especially for categorized skills such as `category/skill-name/SKILL.md`.

## The `description` field

The description is the main discovery signal. Hermes renders skill names and descriptions in the compact skills index so the model can decide which skills are relevant. The model then explicitly loads the body with `skill_view`, a slash command, or `--skills`.

There is no evidence in the current runtime of a separate phrase-matching engine that automatically loads a skill body. Write descriptions as clear selection guidance, not as a promise that a substring will execute the skill.

### What a good description contains

1. **What the skill does** — one plain-language sentence
2. **When to use it** — likely user requests and trigger phrases
3. **Scope boundaries** — what it does not cover, with natural-language cross-references where useful

### Example — good

```yaml
description: "Optimize conversions on marketing pages. Use when the user asks about CRO, conversion rate optimization, or a page that is not converting. For signup-flow diagnosis, see signup."
```

### Example — weak

```yaml
description: "Helps with CRO."
```

This is too vague: it gives the model little information about the task, when to load it, or where its boundary lies.

Keep descriptions concise because they are included in the session's prompt index. Do not put the full procedure in frontmatter.

## Optional frontmatter

```yaml
---
name: lean-canvas
description: "..."
license: MIT
metadata:
  version: 1.2.0
  author: Your Name
  tags: [strategy, product, lean]
---
```

Useful optional fields include:

- `license` — licensing information for shared skills
- `metadata.version` — recommended semver for tracking changes; it is metadata, not the loading mechanism
- `metadata.author` — maintainer identity
- `metadata.tags` — organization and catalog labels
- `platforms` — OS compatibility, for example `[linux, macos]`
- `environments` — relevance filters such as `[kanban]` or `[docker]`
- `metadata.hermes` — Hermes-specific conditions and configuration declarations when needed

Platform and environment fields affect offer/index surfaces. Explicit `skill_view` and `--skills` loads are intentionally not blocked by environment relevance filters; command-level compatibility still remains the skill author's responsibility.

## Optional skill subdirectories

A skill can have progressive-disclosure support files:

```
skills/lean-canvas/
├── SKILL.md           # Required main instructions
├── references/        # Detailed material loaded on demand
├── templates/         # Reusable templates
├── scripts/           # Executable helpers
└── assets/            # Data or other support files
```

Reference files are not independent skills. Link them from `SKILL.md` and load them explicitly, for example:

```text
skill_view(name="lean-canvas", file_path="references/examples.md")
```

## Size and structure

Keep `SKILL.md` focused and reasonably small. The commonly used **500-line limit is a house guideline, not a runtime enforcement found in the current Hermes tree**. If a skill grows beyond that size, move deep reference material into `references/` or split unrelated responsibilities into separate skills.

## Cross-referencing skills

Mention related skills in natural language rather than relying on hard links between independently installed packages:

```yaml
description: "Write a PRD when the user asks for product requirements or a spec. For OKRs, see okrs; for roadmaps, see roadmap."
```

This gives the model scope boundaries without assuming that another plugin or external directory is installed.

## Versioning skills

When you change a skill, bump `metadata.version` when the skill has a version field. Use semver as a human-maintained convention:

- **Major** — breaking behavior or renamed/removed capability
- **Minor** — new backward-compatible content
- **Patch** — typo or clarification without behavior change

The runtime does not require a version field, but versioning plus a changelog makes shared skill updates auditable and reversible.

## Anti-patterns

- **Description that merely paraphrases the title.** Add task scope and likely requests.
- **Description without trigger guidance.** The model may not select it when needed.
- **Description that is too long.** It appears in every relevant prompt index.
- **Procedure hidden only in frontmatter.** Put instructions in the Markdown body and link deep material from support files.
- **Name mismatch.** Keep directory and frontmatter names aligned.
- **Secrets in frontmatter or the body.** Use environment variables or a secrets manager.

## See also

- [Skills](02-skills.md) — skill discovery and invocation
