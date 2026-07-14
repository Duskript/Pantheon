# Skill Name Collision Failure Mode

## Symptom

A kanban task fails to spawn a worker with this error in the log:

```
Error: Unknown skill(s): <name>
```

The task is in `crashed` state with `outcome=crashed` and `error: "pid <PID> not alive"`. The dispatcher eventually demotes the task to `blocked` after the failure limit (default: 2 consecutive crashes).

The dispatcher has hit its failure limit (`failures == effective_limit`, default 2) and demoted the task to `blocked`. The chain is **stalled**, not broken — parent-gating is preserved, but the task needs intervention to retry.

## Root cause

The Hermes skill loader (in `agent/skill_commands.py:475` via `build_preloaded_skills_prompt`) refuses to load a skill if the name is ambiguous — i.e., more than one `SKILL.md`-bearing directory matches the same name. The collision check is a **guard, not a feature**. A single collision rejects the whole `--skill` list for that worker, because the loader cannot tell which one the operator wanted.

**The collision can be a reference doc, not a full skill directory.** A file inside another skill's `references/` directory that happens to have the same filename as a real skill will trigger the collision. Example: `pantheon-dev-workflow/references/workflow-tier-routing.md` shadows `pantheon/workflow-tier-routing/SKILL.md` — both are matched by the loader when it looks up `workflow-tier-routing`.

## Diagnostic recipe

When a worker crashes with `Unknown skill(s): <name>`:

```bash
# 1. Check the log to confirm the error
hermes kanban log <task_id> | grep -i "unknown skill"

# 2. Find ALL matches for the skill name (the loader checks both)
find ~/.hermes/profiles/<profile>/skills/ ~/pantheon/god-packages/shared-skills/ \
  -type d -name "<skill_name>" 2>/dev/null
find ~/.hermes/profiles/<profile>/skills/ ~/pantheon/god-packages/shared-skills/ \
  -name "<skill_name>.md" 2>/dev/null
```

The second `find` (for `<name>.md` files) is the one that catches reference-file collisions. If it returns 2+ matches, that's the collision.

## Two recovery options

**Option A: drop the colliding skill from the task's skill list.** Surgical, low-risk, for active builds.

```bash
# Check current skills
sqlite3 ~/.hermes/kanban.db "SELECT skills FROM tasks WHERE id='<task_id>';"

# Drop the colliding skill, keep the rest
sqlite3 ~/.hermes/kanban.db \
  "UPDATE tasks SET skills='[\"workflow-catalog-lookup\"]' WHERE id='<task_id>';"

# Unblock and re-dispatch
hermes kanban unblock <task_id>
hermes kanban dispatch
```

**When to use:** active build, time pressure, the colliding skill isn't strictly required for the task.

**Option B: rename the references file.** Real fix, takes 1 minute, prevents future crashes.

```bash
# Find the colliding file (usually in another skill's references/ dir)
find ~/.hermes/profiles/<profile>/skills/ -name "<skill_name>.md" -path "*/references/*"

# Rename it to something non-colliding
mv /path/to/colliding/skill/references/<skill_name>.md \
   /path/to/colliding/skill/references/<skill_name>-reference.md

# Update any internal links to the old filename
grep -rln "<skill_name>.md" /path/to/colliding/skill/

# Verify no more collision
HERMES_PROFILE=<profile> python3 -c "
import sys, os, json
os.environ['HERMES_PROFILE'] = '<profile>'
sys.path.insert(0, '/home/konan/pantheon/hermes-agent')
from tools.skills_tool import skill_view
print(json.loads(skill_view('<skill_name>', preprocess=False)).get('success'))
"
# Expected: True (success)
```

**When to use:** after the active build, as a follow-up. Always file a follow-up kanban task if you take Option A under time pressure.

## Case study: workflow-tier-routing collision (verified 2026-06-16, conductor-ui build)

The conductor-ui build (task `t_fad2b870`) had this in its `task.skills` field:

```json
["workflow-catalog-lookup", "workflow-tier-routing"]
```

The worker crashed twice. The reason:

- `workflow-catalog-lookup` lives at `~/pantheon/god-packages/shared-skills/workflow-catalog-lookup/SKILL.md` — the actual skill, symlinked into the thoth profile's skills tree
- `workflow-tier-routing` has TWO files with that name:
  - `~/pantheon/god-packages/shared-skills/workflow-tier-routing/SKILL.md` — the actual skill
  - `~/.hermes/profiles/thoth/skills/software-development/pantheon-dev-workflow/references/workflow-tier-routing.md` — a reference doc inside another skill that happens to have the same filename

The collision check found both and rejected `workflow-tier-routing` entirely. The whole `--skill` list failed to load, the worker couldn't start, the dispatcher gave up after 2 crashes.

**Option A applied under time pressure:** dropped `workflow-tier-routing` from the task's skills, restored it after the rename. Total recovery time: ~15 minutes (most of which was diagnosing the root cause).

**Option B applied as follow-up:** renamed the references file to `workflow-tier-routing-reference.md`, updated 3 internal links in `pantheon-dev-workflow/SKILL.md`. Both skills now resolve cleanly.

## Pre-existing tracking document

The `pantheon-ops/operator-chain-design` skill ships with a reference at `references/skill-name-collision-2026-06-16.md` that documents this same failure mode. If you encounter a collision and want a more detailed RCA, read that file.

## Prevention rules

For skill authors writing reference docs:

- **Don't name a reference file the same as a real skill.** Use a `-reference` or `-notes` suffix, or move the file to a subdirectory like `_internal/`.
- **For skill authors** reorganizing a reference doc into a new full skill: delete the old reference file, don't leave it as a shadow. The conductor-ui crash is what happens when you don't.

For god authors dispatching kanban tasks:

- **After creating a new task**, run `hermes skills list | grep <skill_name>` to confirm the skill resolves.
- **If a worker crashes immediately with `Unknown skill(s):`,** don't just `kanban unblock` and retry. The collision will recur. Diagnose with the recipe above first.

For operators reviewing build plans:

- **Build plans that reference skills by name should also reference the canonical path.** If a build plan says "use `workflow-tier-routing`", the operator (or a watcher god) should verify the skill resolves before the first dispatch.
