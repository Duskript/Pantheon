---
title: "Using a Skill — frontmatter best practices"
last_verified: 2026-06-19
---

# Using a Skill — frontmatter best practices

This page covers the frontmatter fields you'll touch most often: `name`, `description`, `metadata.version`, and `metadata.tags`. The frontmatter is the part of a skill that's *always* loaded — the body is lazy. Get the frontmatter right and the skill works; get it wrong and the skill never triggers.

## Required frontmatter

```yaml
---
name: skill-name
description: What this skill does and when to use it.
---
```

That's the minimum. Two fields, both required.

## The `name` field

Rules from the Agent Skills spec:

- 1-64 characters
- Lowercase letters (`a-z`), numbers (`0-9`), hyphens (`-`)
- Cannot start or end with a hyphen
- No consecutive hyphens (`--`)
- **Must match the parent directory name exactly**

Valid: `cro`, `emails`, `ab-testing`, `pm-product-strategy`
Invalid: `Page-CRO`, `-page`, `page--cro`, `skill_name`

**Why strict?** The directory name *is* the skill name. Mismatch = the god can't find it.

## The `description` field

This is the most important field in the entire skill. It's the *only* thing the god sees in its system prompt. The body is lazy-loaded.

**The description is the trigger mechanism.** The god looks at the user's request and the description of every available skill. If the description contains trigger phrases that match the request, the god loads the body.

### What a good description contains

1. **What the skill does** — one sentence, plain language
2. **When to use it** — explicit trigger phrases the user might say
3. **What it does NOT cover** — scope boundaries, with cross-references to other skills

### Example — good

```yaml
description: "When the user wants to optimize conversions on any marketing page. Use when the user says 'CRO,' 'conversion rate optimization,' 'this page isn't converting.' For signup flows, see signup."
```

Three things in one line:

1. What it does (optimize conversions)
2. When to use it (3 trigger phrases)
3. What it doesn't cover (signup flows → different skill)

### Example — bad

```yaml
description: "Helps with CRO."
```

Too vague. "CRO" is the only trigger phrase, and "helps with" tells the god nothing about *what* it does.

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

- `license` — defaults to MIT if omitted
- `metadata.version` — semver, useful for tracking changes
- `metadata.author` — who maintains the skill
- `metadata.tags` — free-form tags for organization

## Optional skill subdirectories

A skill can have more than just `SKILL.md`:

```
skills/lean-canvas/
├── SKILL.md           # Required - main instructions (<500 lines)
├── references/        # Optional - detailed docs loaded on demand
├── scripts/           # Optional - executable code
└── assets/            # Optional - templates, data files
```

- `references/` is for *deep-dive* content. The skill body links to it ("see references/lean-canvas-deep-dive.md") and the god loads it only when the user needs the depth.
- `scripts/` is for executable code. Use sparingly — most skills don't need them.
- `assets/` is for templates and data files (CSV headers, JSON schemas, etc.).

## The 500-line rule

`SKILL.md` should be **under 500 lines**. The Agent Skills spec enforces this as a soft ceiling.

If your skill is over 500 lines, you're doing one of two things wrong:

1. **Too much detail in the body.** Move the deep content to `references/` and link to it.
2. **Too many topics in one skill.** Split it into multiple skills. Use the `related_skills` cross-reference to tie them together.

## Cross-referencing skills

You can mention other skills in your description. This helps the agent pick the right one.

```yaml
description: "When the user wants a PRD. Use when the user says 'PRD,' 'product requirements document,' 'write a spec.' For OKRs, see okrs. For roadmaps, see roadmap. For PR FAQs, see pr-faq."
```

Three scope boundaries in one description. The agent will pick the right skill based on the prompt.

**Note from the Agent Skills spec:** cross-references in `description` are *natural language*, not hard links. Plugins install independently, so hard-linking another plugin's skill can break. Always say "see [skill-name]" in plain text.

## The trigger phrase technique

The description is the trigger. To make the trigger reliable, list the *exact phrases* the user is likely to say.

```yaml
description: "When the user wants to write a SWOT analysis. Use when the user says 'SWOT,' 'strengths weaknesses opportunities threats,' 'do a strategic analysis,' 'where do we stand.'"
```

Four trigger phrases. The agent will recognize any of them.

**Don't:**

```yaml
description: "A comprehensive framework for evaluating strategic position."
```

That's a description of what the framework *is*, not what the user will *say*. The agent won't trigger on it.

## Versioning skills

When you change a skill, bump the `metadata.version` field. This is critical for:

- Detecting when an update is available
- Tracking what changed (the version + CHANGELOG)
- Rolling back if a change breaks

The convention is semver:

- **Major** (1.0.0 → 2.0.0) — breaking change (renamed, removed functionality, behavior change)
- **Minor** (1.0.0 → 1.1.0) — new content, no breaking change
- **Patch** (1.0.0 → 1.0.1) — typo fix, clarification, no content change

## Anti-patterns

- **Description that paraphrases the title.** "Helps with X" when the title already says "X" — wastes the trigger surface.
- **Description without trigger phrases.** The agent can read it, but won't know when to load it.
- **Description that's too long.** The god sees it in every prompt. Keep it under 1024 chars.
- **No `metadata.version`.** You will lose track of what's current.

## See also

- [Making a Skill](04-making-a-skill.md) — the full authoring workflow
- [Skills](02-skills.md) — what skills are
- [Common Pitfalls](07-common-pitfalls.md) — what goes wrong with skill authoring
