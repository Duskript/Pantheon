# Skill Author for Amber

> Design, build, and ship a custom skill for Amber, on demand. The output is a zipped, installable skill bundle, ready to send via Telegram.

## What it does

When you say "build Amber a skill for X" or "she needs something that does Y at the conference," this skill:

1. Clarifies the need (one question, not five)
2. Classifies the skill (procedural only, with references, or with scripts)
3. Designs the SKILL.md with proper frontmatter, trigger phrases, and procedure
4. Builds any supporting files (references, scripts)
5. Writes the README with install + use + troubleshooting
6. Packages as a zip
7. Returns the zip, install instructions, and a "what to expect" description

You paste the install instructions into her Pantheon chat, attach the zip, and she's got a new capability.

## Install

This skill is for *us* (Konan, Thoth, and any god that needs to build skills for Amber). It doesn't get shipped to Amber herself.

```bash
mkdir -p ~/pantheon/god-packages/shared-skills/skill-author-for-amber && \
cp -r skill-author-for-amber/* ~/pantheon/god-packages/shared-skills/skill-author-for-amber/
```

The procedure is in `SKILL.md`. Load it any time a request matches the trigger phrases:
- "Build Amber a skill for X"
- "She needs something for Y at the conference"
- "Make her a skill that does Z"
- "Package this up for her"
- "Design a skill for Amber"

## When to use this vs. the god-prototyping workflow

**Use `skill-author-for-amber` when:**
- The deliverable is a Hermes skill for Amber's machine
- The scope is small (one skill, one capability, ship in one session)
- The user is Konan and the recipient is Amber

**Use the god-prototyping workflow when:**
- The deliverable is a new Pantheon god (full persona, harness, knowledge base)
- The scope is large (multi-file, multi-session, knowledge architecture)
- The work is for a god's design, not a user's tool

## How to invoke

In any Thoth or Hermes session, just say one of the trigger phrases. The skill loads, the procedure runs, the zip ships.

Example:
> "Build Amber a skill that turns a photo of a business card into a structured contact in her notes."

The skill will:
1. Ask: "Should the output be a Markdown file, JSON, or a new entry in some specific format?"
2. Build a Class C skill (procedural + scripts, since OCR needs an external tool)
3. Ship a zip with the OCR script, the SKILL.md, the install instructions

## Notes

Private skill. Not for distribution. For internal use by Konan, Thoth, and any god that builds skills for Amber. Last refreshed 2026-06-15.
