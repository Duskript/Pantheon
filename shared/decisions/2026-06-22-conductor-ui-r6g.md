# 2026-06-22 — Conductor UI R6g: Comment field wiring tests shipped

Marvin completed kanban task t_dd914776 (R6g) at 18:42 UTC. 8 new
tests added to `CommentsSection` in detail.test.tsx; all 13
CommentsSection + 343 total src/kanban tests pass; tsc clean for files
touched; vite build OK.

See full decision log at
`~/athenaeum/Codex-God-marvin/journal/2026-06-22-conductor-ui-r6g-comment-field.md`.

Key decisions:
- Extended detail.test.tsx CommentsSection block (vs new focused
  file) because the component lives in detail.tsx and 5 tests were
  already there.
- Pinned the actual HTML contract: Enter in <textarea> does NOT
  submit; only the submit button posts. (Original draft assumed the
  form would submit on Enter — wrong, that's <input> behavior.)
- After POST success, button stays disabled because draft cleared —
  asserted on the textarea instead.
- Switched to `server.use(...)` (dynamic handlers) instead of
  stubTask() for tests that mutate currentComments across POST/GET
  lifecycle. msw's latest-handler-wins + closure-captured-array
  pattern requires this for the "comments reload after add" assertion.

Sibling R6 tasks (R6a/b/c/d/f/h/i/j) run in parallel against the same
source tree; R6b (t_e469af7c) is currently creating
drawer-comments.test.tsx which has tsc errors — that's their work, not
mine to fix.
