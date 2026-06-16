---
name: skill-author-for-amber
description: "Use when the user says 'build Amber a skill', 'she needs something for X at the conference', 'make her a skill that does Y', 'package this up for her', 'design a skill for Amber', or any request to design, build, and ship a custom skill for Amber. The output is a fully packaged skill (zip file) ready to attach to Telegram and send to her agent for install. Designed to be invoked repeatedly as new conference needs come up."
version: 1.0.1
metadata:
  hermes:
    tags: [meta, skill-authoring, conference, amber, private]
    related_skills: []
---

# Skill Author for Amber — On-Demand Skill Builder

## When to Use

Load this skill when the user (Konan) wants to design, build, and ship a custom skill specifically for Amber. The output is always a zip file containing a complete, installable skill bundle, plus install instructions for her agent and a "what to expect" description for Amber.

**Trigger phrases:**
- "Build Amber a skill for X"
- "She needs something for Y at the conference"
- "Make her a skill that does Z"
- "Package this up for her"
- "Design a skill for Amber"
- "She needs a tool that [does X]"

**Do not use this skill for:**
- Skills intended for the shared skills hub or other users
- General-purpose skills to be published
- One-off scripts (just run the script, don't wrap it in a skill)
- Questions about how to design skills (use the god-prototyping workflow instead)

## Amber Profile (Baked-In Context)

Don't ask. Use this as ground truth unless Konan explicitly overrides:

- **User:** Amber. Konan's person at the accounting conference.
- **Conference context:** 2026 accounting professionals event. She's there to network, talk to the Unaccountable podcast guys, show off what Pantheon can do.
- **Audience for what she produces:** Accounting professionals (CPAs, firm partners, controllers, bookkeepers) and the Unaccountable podcast team. Skeptical of AI hype. Values evidence over enthusiasm.
- **Machine:** Her own Pantheon instance, separate machine (Idaho while conference is in Florida).
- **Chat interface:** Telegram (primary). The skill's output should attach cleanly to a Telegram message.
- **Install target:** Her Pantheon agent, not her directly. She doesn't run shell commands. Install instructions must be formatted as something her agent can execute.
- **Tech comfort:** Non-technical. Skills must "just work" after install. Graceful degradation if deps are missing.
- **Aesthetic preference:** "Cool" and "show off." Things that look editorial, designed, considered — not generic AI output.

## Existing Skills for Amber (Don't Duplicate)

Before building, check if the need can be met by an existing skill. The following are already shipped (or being shipped) to her:

- **`conference-report`** — research a topic, generate self-contained HTML report with editorial design, auto-render PDF. For showing at the booth, on the podcast, etc.
- **`transcribe-recording`** — turn audio files into clean transcripts with key quotes, summary, action items.

If a new need is an extension or variant of one of these (e.g., "transcribe AND generate a follow-up email"), prefer **referencing the existing skill** in the new one's procedure rather than rebuilding from scratch.

## Procedure

Follow these steps in order. The deliverable is always a zip file in the user's Telegram, with install instructions and a "what to expect" description.

### Step 1: Clarify the Need (ONE Question)

If the user's request is clear, proceed. If it's vague, ask **ONE** clarifying question — not five. Pick the most important ambiguity.

Priorities for the question, in order:
1. **What does the skill produce?** (file, message, action on a system, structured data)
2. **What's the input?** (audio file, text topic, photo, URL, user message)
3. **What does "done" look like?** (file attached, message returned, system state changed)

If the user gave any of these explicitly, don't re-ask. The other two can be inferred.

**Never ask about:**
- Audience (assume the conference/podcast context unless told otherwise)
- File format (default to Markdown + PDF for documents, MP4 for video, JSON for data)
- Where to save (default to `~/Documents/{skill-name}/` or `~/Downloads/` for ephemeral)
- Whether to use scripts vs SKILL.md-only (this is decided by what the skill actually needs to do)

### Step 2: Classify the Skill

Based on the need, classify into one of three architectures. This determines what files to generate.

**Class A — Pure Procedural (SKILL.md only)**
- **What it does:** Teaches the LLM a procedure. The model reads the SKILL.md and follows it.
- **Examples:** "draft a follow-up email after a conversation", "summarize a long article", "generate 5 podcast questions on a topic"
- **Files needed:** `SKILL.md` only
- **Size:** 5-15KB typically

**Class B — Procedural + References (SKILL.md + references/)**
- **What it does:** Teaches the model a procedure AND gives it long-form knowledge to reference (methodology, design system, data format, etc.)
- **Examples:** conference-report (has design-brief.md, research-methodology.md, html-template.md)
- **Files needed:** `SKILL.md`, `references/*.md`
- **Size:** 15-50KB typically

**Class C — Procedural + References + Scripts (SKILL.md + references/ + scripts/)**
- **What it does:** The model follows a procedure, references long-form knowledge, AND needs to call external tools (audio transcription, PDF rendering, file conversion, API calls, etc.)
- **Examples:** transcribe-recording, conference-report (v3 with PDF render)
- **Files needed:** `SKILL.md`, `references/*.md`, `scripts/*.py`
- **Size:** 20-100KB typically

**Default to Class A** unless the need clearly requires references (long knowledge the model needs to consult mid-procedure) or scripts (calls to tools the LLM can't do natively).

### Step 3: Design the SKILL.md

The SKILL.md is the core of every skill. Required sections, in this order:

```markdown
---
name: {skill-name}
description: "{trigger phrases, when to use, what it produces}"
version: 1.0.0
metadata:
  hermes:
    tags: [{domain}, {type}, conference, amber]
    related_skills: [{other-skill-names}]
---

# {Skill Title}

## When to Use

{1-2 sentences on trigger phrases and what the skill produces}

**Trigger phrases:** "{phrases that should load this skill}"

## What It Produces

{Numbered list of deliverables. 1-5 items, each a concrete artifact.}

## Procedure

### Step 0: Setup Check (only if Class C with deps)
{Detect missing dependencies, prompt user once, install if confirmed}

### Step 1: {Name}
{1-2 sentences on what the model does}

### Step 2: {Name}
{...}

{Continue as needed. 3-7 steps is typical. Each step is action-oriented, not explanatory.}

## Quality Gates

{Numbered checklist the model should self-verify before delivering. 5-10 items.}

## Pitfalls

{Bulleted list of common failure modes. 3-8 items. Each is "Don't do X because Y."}

## Related Skills

{If the skill composes with other Amber skills, link to them.}
```

**SKILL.md rules:**
- **Use active voice.** "Run the script" not "the script can be run."
- **Be specific.** "Save to `~/Documents/{name}/report-{slug}-{date}.html`" not "save the output."
- **Include example commands.** Don't just describe — show the exact bash/python.
- **No emoji in the body.** Emoji in skill instructions pollute the LLM's tendency to use them in output. (Emoji in the *output* of the skill is fine — that's a design choice for the skill to make.)
- **Date-stamp the procedure.** "Generated 2026-06-15" in a comment or version field, so future maintainers know when this was written.
- **Banned phrases (in the SKILL.md body):**
  - "You can also" (passive permission, just say what to do)
  - "Optionally" (decide for the user)
  - "It might be helpful to" (just say it)
  - "Consider" (be directive)
  - "May want to" (be directive)

### Step 4: Build References (if Class B or C)

References are long-form knowledge the model reads mid-procedure. They live in `references/`.

**Common reference types:**
- **Design brief** — visual design rules, anti-patterns, color tokens, typography
- **Methodology** — research methodology, source standards, confidence frameworks
- **Template** — annotated template the model fills in (HTML, email, script outline)
- **Domain knowledge** — accounting, legal, medical, etc. specifics the LLM doesn't have
- **Tone guide** — voice and style rules for the skill's output

**Reference rules:**
- Each reference is self-contained. The model should be able to read any reference independently.
- Cross-link between references with `[[filename]]` or explicit "see references/X.md" language.
- Include anti-patterns explicitly. "Don't do X because Y" is more useful than "do Y."
- Date-stamp. Add a "Last updated" note at the top.

### Step 5: Build Scripts (if Class C)

Scripts are external tool invocations. They live in `scripts/`.

**Required scripts (when applicable):**
- `check-deps.py` — verify dependencies are installed. Exits 0 if ready, 1 with message if not. Reads/writes a `.deps-installed` flag file.
- `install-deps.py` — one-time install of missing deps. Idempotent. Writes the flag file on success.
- The actual tool script (e.g., `transcribe.py`, `render-pdf.py`)

**Script rules:**
- **Stdlib + already-installed packages only**, unless a heavier dep is truly required. If it is, the install script must handle it.
- **stdout = machine-readable** (just the result, e.g., the output file path). **stderr = human-readable** (progress, errors, instructions).
- **Exit 0 on success, 1 on hard failure, 0 on graceful degradation** (e.g., deps missing but HTML was still produced).
- **No silent side effects.** If the script does something irreversible (writes to disk, calls an API), it must say so before doing it.
- **Idempotent where possible.** Re-running the install script should be a no-op if already installed.

### Step 6: Generate the README

The README is what Amber's agent reads to install the skill. It must include:

1. **One-line description** of what the skill does
2. **One-command install** (untars the zip, copies to `~/.hermes/skills/`, makes scripts executable)
3. **Manual install** (step-by-step, in case the one-liner fails)
4. **One-time setup** (if there are deps to install — link to `install-deps.py`)
5. **Usage examples** (3-5 phrases she can use to invoke the skill)
6. **File layout** (so she can see what's in the package)
7. **Troubleshooting** (5-10 common issues, each with a fix)
8. **Notes** section at the bottom: "Private skill. Not for distribution."

### Step 7: Package as Zip

```bash
cd ~/pantheon/exports
rm -f {skill-name}.zip
python3 -c "
import zipfile
from pathlib import Path
src = Path('{skill-name}')
dst = Path('{skill-name}.zip')
with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for f in sorted(src.rglob('*')):
        if f.is_file() and '__pycache__' not in f.parts and not f.name.endswith('.pyc') and not f.name.startswith('.'):
            zf.write(f, f.relative_to(src.parent))
print(f'Created: {dst} ({dst.stat().st_size:,} bytes)')
"
```

**Zip rules:**
- Compression level 9 (max).
- Top-level folder inside the zip is the skill name (so unzipping creates `{skill-name}/`, not a flat dump).
- Exclude: `__pycache__/`, `*.pyc`, `*.deps-installed`, `*.flag`, anything starting with `.`
- Verify the zip contents with `unzip -l` before delivering.

### Step 8: Sanity Check the Package

Before delivering, verify:

1. **All files are present** (use `unzip -l`)
2. **SKILL.md parses** — frontmatter is valid YAML, structure follows the spec
3. **All scripts parse** — `python3 -c "import ast; ast.parse(open('script.py').read())"`
4. **No public cruft** — no `license: MIT`, no `author:` fields with external names, no "for distribution" language
5. **The "Notes" section in README is correct** — "Private skill. Not for distribution."
6. **No Tailwind / gradient / glassmorphism** in any HTML templates (if applicable)
7. **The trigger phrases in frontmatter match the actual procedure**
8. **If a script is included, `check-deps.py` is also included**

### Step 9: Deliver to User

Three things to return, in this order:

**1. The zip, attached to the chat:**
```
MEDIA:/home/konan/pantheon/exports/{skill-name}.zip
```

**2. Install instructions for her agent** — formatted as a single block she can paste into her Pantheon chat. See "Install Message Template" below.

**3. A "what to expect" description for Amber** — formatted as a single block describing what she'll experience when she uses the skill. See "What-To-Expect Template" below.

After delivery, append a one-line summary: "Shipped. Skill is at `~/pantheon/exports/{skill-name}.zip`, size X.X KB."

### Step 10: Memory Update (Optional but Recommended)

If the skill taught us something reusable about Amber's needs (a pattern, a preference, a constraint), store it via `ichor_store` with category `preference` or `insight`. Don't store the skill itself — that lives in the export directory.

Examples of worth-storing insights:
- "Amber prefers editorial-aesthetic designs for conference materials (not generic SaaS)."
- "Amber's install target is her Pantheon agent, not her directly — instructions should be agent-pasteable."
- "Amber values graceful degradation — skills that fail closed (no deliverable) are worse than skills that fail open (deliver partial)."

## Install Message Template (for her agent)

```
Hey, I need you to install a new skill I was given. Here's what to do:

1. I just sent you a zip file called `{skill-name}.zip` containing a folder called `{skill-name}/`. Save the zip somewhere (Downloads, Desktop, wherever) and unzip it.
2. Once unzipped, run this single command from the folder that contains the `{skill-name}/` folder:

```bash
mkdir -p ~/.hermes/skills/{skill-name}/{references,scripts} && \
cp -r {skill-name}/{{SKILL.md,references,scripts}}/* ~/.hermes/skills/{skill-name}/ && \
chmod +x ~/.hermes/skills/{skill-name}/scripts/*.py
```

3. {IF HAS DEPS: Run `python3 ~/.hermes/skills/{skill-name}/scripts/check-deps.py` to see if dependencies are installed.}
4. {IF HAS DEPS: If it says "NOT READY," run `python3 ~/.hermes/skills/{skill-name}/scripts/install-deps.py` to install them. It's a one-time download, takes X-Y minutes, and won't be asked again.}
5. Report back when the skill is installed and {IF HAS DEPS: the deps check passes}.
```

## What-To-Expect Template (for Amber)

```
The `{skill-name}` skill is for {one-line description of what it's for}. When you invoke it, here's what happens:

**You {input action}.** Something like "{example invocation 1}" or "{example invocation 2}."

**It {core action 1}.** {1-2 sentences on what the skill does.}

**It {core action 2}.** {1-2 sentences on the next step.}

**You get {output description}.** {What the user sees in their chat — file attached, message returned, etc.}

**For your conference use cases:**
- **{Scenario 1}:** {How to use it, what model/option to pick}
- **{Scenario 2}:** {How to use it}
- **{Scenario 3}:** {How to use it}

**Heads up on the first run:** {IF HAS DEPS: it'll ask once if you want to install dependencies. Say yes. After that, the skill just works.}

Try it first with something easy — {small first-use suggestion} — to see how the output looks, then go after the bigger tasks.
```

## Anti-Patterns (Don't Do These)

- ❌ **Don't ask 5 questions when 1 will do.** The user wants a skill, not a requirements-gathering session.
- ❌ **Don't build Class C when Class A is enough.** Scripts add install friction. Only include them when the LLM truly can't do the work.
- ❌ **Don't copy-paste from existing skills without thinking.** The conference-report and transcribe-recording skills have specific patterns (check-deps, install-deps, etc.) that work — but a new skill might not need them all.
- ❌ **Don't add features Konan didn't ask for.** A skill that does the one thing well beats a skill that does five things poorly.
- ❌ **Don't skip the "what to expect" message.** Konan will paste it into Telegram for Amber. Without it, she has to figure out the skill from the install instructions alone.
- ❌ **Don't use emoji in the SKILL.md body.** They pollute the LLM's output.
- ❌ **Don't include `license: MIT` or `author: ...` in the frontmatter.** Amber-only. Always.
- ❌ **Don't make the SKILL.md longer than needed.** Every paragraph costs tokens on every invocation. Cut ruthlessly.
- ❌ **Don't add a "License" section to the README.** Replace with "Notes: Private skill. Not for distribution."
- ❌ **Don't auto-install dependencies.** Always ask the user once. The flag file handles "don't ask again."

## Quality Gates (Self-Check Before Delivering)

- [ ] The skill does one thing well (not five things poorly)
- [ ] Class A/B/C was chosen correctly for the need
- [ ] All trigger phrases in the frontmatter are real phrases someone would say
- [ ] The procedure is 3-7 steps, each action-oriented
- [ ] All scripts (if any) are syntax-clean and follow the stdout=path / stderr=human convention
- [ ] The README has install + use + troubleshooting
- [ ] The zip is well-formed and contains the right files
- [ ] No public cruft (license, author, distribution language)
- [ ] No emoji in the SKILL.md body
- [ ] The "what to expect" message is specific to this skill, not generic
- [ ] The install message is formatted as a single agent-pasteable block
