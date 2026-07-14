---
title: "Pantheon Best Practices"
last_verified: 2026-06-19
audience: OSS users of pantheon-core
status: living document
---

# Pantheon Best Practices

> **Living knowledge base.** Updated regularly. Each page has a `last_verified` date. If a page is more than 60 days old, file an issue.

## What this is

A practical operator's manual for Pantheon. Not a pitch, not a tutorial series, not auto-generated reference. These pages answer one question each: *"How do I do the thing, what goes wrong if I do it wrong, and what does the right way look like?"*

## What this is NOT

- **Not a replacement for the [README](https://github.com/Duskript/Pantheon#readme).** The README is the elevator pitch and quick install. This is the operator manual.
- **Not auto-generated reference.** For the MCP tool surface, see `mcp_server.py`. For god schemas, see `gods/gods.yaml`.
- **Not architecture documentation.** We don't explain *why* Pantheon is built the way it is. We explain *how to use it well*.

## How to read this

If you just installed Pantheon, start with `00-quickstart.md`. If you have a specific task, jump to the relevant page in the table of contents.

Each page follows the same shape:

1. **When to use this** — the user question it answers
2. **The pattern** — the recommended approach, with concrete commands
3. **Anti-patterns** — what goes wrong, with examples
4. **See also** — links to the source material

## Table of contents

| # | Page | What it covers |
|---|---|---|
| 00 | [Quickstart](00-quickstart.md) | The 5 commands you actually need to start |
| 01 | [Context Management](01-context-management.md) | Memory, Ichor, Athenaeum — how persistence works in Pantheon |
| 02 | [Skills](02-skills.md) | What a skill is, when skills load, how to invoke them |
| 03 | [Reverse Prompting](03-reverse-prompting.md) | The "let the god ask you" pattern |
| 04 | [Making a Skill](04-making-a-skill.md) | How to author a new skill (SKILL.md conventions) |
| 05 | [Using a Skill](05-using-a-skill.md) | Frontmatter best practices, trigger phrases, examples |
| 06 | [Building a God](06-building-a-god.md) | When and how to spawn a new god |
| 07 | [Common Pitfalls](07-common-pitfalls.md) | The high-cost mistakes and how to avoid them |
| 08 | [Decision Log](08-decision-log.md) | How Pantheon records operator-locked decisions |
| 09 | [MCP Tools](09-mcp-tools.md) | The operator-facing MCP surface |

## Contributing

This is a public repo. PRs welcome.

- **Adding a page:** follow the page shape above. New pages go at the next number (`10-your-topic.md`).
- **Updating a page:** bump `last_verified` in the frontmatter, add an entry to `CHANGELOG.md`.
- **Disagreeing with a page:** open an issue, not a silent edit. We want the discussion visible.

## Why this exists

Most of the patterns here came from internal use. They were operator-locked decisions, post-mortems, and god-notify exchanges. We collected them in one place so a new operator doesn't have to learn them the hard way.

The cost of bad docs is silent — the cost of good docs is one hour per page. We're paying the second cost so you don't pay the first.

## Maintenance

Each page has a `last_verified` field in its frontmatter. The docs are reviewed on the 1st of each month. Pages older than 60 days are flagged for re-verification.

The append-only `CHANGELOG.md` is the audit trail of what changed and when.

## License

This documentation is part of the Pantheon project. See [LICENSE](https://github.com/Duskript/Pantheon/blob/main/LICENSE) in the repo root.
