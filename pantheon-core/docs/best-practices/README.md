---
title: "Pantheon Best Practices"
last_verified: 2026-09-01
audience: OSS users of pantheon-core
status: living document
---

# Pantheon Best Practices

> **Living knowledge base.** Updated regularly. Each page has a `last_verified` date. If a page is more than 60 days old, the monthly staleness check flags it for re-verification.

## What this is

A practical operator's manual for Pantheon. Not a pitch, not a tutorial series, not auto-generated reference. These pages answer one question each: *"How do I do the thing, what goes wrong if I do it wrong, and what does the right way look like?"*

## What this is NOT

- **Not a replacement for the [README](https://github.com/Duskript/Pantheon#readme).** The README is the elevator pitch and quick install. This is the operator manual.
- **Not auto-generated reference.** For the live MCP tool surface, see `pantheon-core/mcp_server.py`. For god schemas, see `gods/gods.yaml`.
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
| 00 | [Quickstart](00-quickstart.md) | The five operator actions to start |
| 02 | [Skills](02-skills.md) | What a skill is, how discovery works, and how to invoke it |
| 05 | [Using a Skill](05-using-a-skill.md) | Frontmatter, trigger guidance, and packaging |
| 08 | [Decision Log](08-decision-log.md) | How Pantheon records operator-locked decisions |
| 09 | [MCP Tools](09-mcp-tools.md) | The current operator-facing MCP surface |

The current checkout contains these five numbered pages. Topics formerly listed as pages 01, 03, 04, 06, and 07 are not present at this path; consult the repository's current source and skills documentation rather than following stale links.

## Contributing

This is a public repo. PRs welcome.

- **Adding a page:** follow the page shape above. New pages go at the next number (`10-your-topic.md`).
- **Updating a page:** bump `last_verified` in the frontmatter and add an entry to `CHANGELOG.md`.
- **Disagreeing with a page:** open an issue, not a silent edit. We want the discussion visible.

## Why this exists

Most of the patterns here came from internal use. They were operator-locked decisions, post-mortems, and god-notify exchanges. We collected them in one place so a new operator doesn't have to learn them the hard way.

The cost of bad docs is silent — the cost of good docs is one hour per page. We're paying the second cost so you don't pay the first.

## Maintenance

Each page has a `last_verified` field in its frontmatter. The docs are reviewed monthly. Pages older than 60 days are flagged for re-verification by `docs-staleness-check.py`.

The append-only `CHANGELOG.md` is the audit trail of what changed and when.

## License

This documentation is part of the Pantheon project. See [LICENSE](https://github.com/Duskript/Pantheon/blob/main/LICENSE) in the repo root.
