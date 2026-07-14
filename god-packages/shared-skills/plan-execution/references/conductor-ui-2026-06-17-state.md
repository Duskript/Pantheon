# Conductor UI — 2026-06-17 On-Disk State

Session-specific detail for the conductor-ui project. Captures the state of
the workspace at the moment the commit-after-signoff rule was added, so
future sessions can orient quickly without re-running the inventory.

## What was on disk

- `~/projects/conductor-ui/src/kanban/detail.tsx` — **795 lines, 4 sections built**
  (header, relationships, comments, run log, audit timeline)
- `~/projects/conductor-ui/src/router.tsx` — `/board/$taskId` route wired to
  `TaskDetailPanel` (the Phase 3.4 deliverable)
- `~/projects/conductor-ui/src/kanban/__tests__/detail.test.tsx` — test file
  exists, all 23 tests pass
- `npx tsc --noEmit` — **clean, zero errors** (the claimed "1 unrelated tsc
  error in migration" was stale — verified clean on 2026-06-17)
- `npx vitest run src/kanban/__tests__/detail.test.tsx` — **PASS (23) FAIL (0)**

## What was missing

- **No `.git` repository** at the project root — the work was on disk but
  had no version history, no remote backup, no recovery path
- **No `.gitignore`** — first commit would have pulled in `node_modules/`
  and other generated artifacts
- **No remote** — no `origin`, no `Duskript/conductor-ui` connection
- **The GitHub URL `Duskript/conductor-ui` returned 404** at the GitHub API
  on 2026-06-17. The URL was reserved/announced but the GitHub-side
  `git init --bare` had not happened. Could not push until the repo was
  created via `gh repo create`.

## What the operator wanted

Konan's standing directive: "we should start committing after each sign off
against the conductor-ui GitHub repo." This triggered the new-project-repo
flow documented in `github-pr-workflow` §8.

## Follow-up actions for the next session

1. Confirm the operator's preference: private vs public repo (default private
   until told otherwise)
2. Decide on commit shape: A (single initial) or B (scaffold + feature)
   — Shape B recommended for this case because the 795-line `detail.tsx` is
   real shipped-quality code that deserves its own commit boundary
3. Run the new-project-repo flow (verify URL → inventory → write `.gitignore`
   → `gh repo create` → commit → push → verify)
4. After the first commit lands, the commit-after-signoff rule kicks in
   automatically: any subsequent sign-off triggers a commit + push before
   the next phase starts

## What NOT to do

- Don't rebuild the 795-line `detail.tsx` — it's already shipped
- Don't split kanban task t_34f89a26 into "fix the crash" subtasks — the
  crash was in a prior wrap-up cycle; the surviving artifact is green
- Don't auto-create the GitHub repo without confirming the operator's
  private/public preference (the URL exists in chat history but the actual
  repo doesn't exist on GitHub yet)
