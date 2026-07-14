# Conductor UI Phase 4.0b-harden QA blocker

Updated: 2026-06-18T08:27:43Z
Owner: Hephaestus
Status: RETURN_TO_MARVIN
PR: #35 (`phase-4.0b-api-server` @ `b020120`)

## Verdict

GPT-5.5 Ponytail QA returned `FAIL` with high confidence after Hephaestus re-verified the branch on disk.

## Blocking findings

1. `service.py` still violates the auth sentinel contract on the service -> `LiveStreamServer` path. In the documented production shape where `CONDUCTOR_API_KEY` exists only in `~/.hermes/.env` or `~/pantheon/conductor/v2/.env`, service computes `self.api_key = ""` and passes that explicit empty string into `LiveStreamServer`, disabling WebSocket auth.
2. `api_server.py` `/health` reports `auth: DISABLED` when protected routes are actually enforcing auth via env/file fallback.
3. PR #35 scope contract is stale: title/body describe a narrow Phase 4.0b API/auth PR, but current diff is 57 files / 14 commits / 15,532 additions.
4. `git diff --check origin/main..HEAD --` fails on trailing whitespace in shared/active markdown files.

## Evidence

- Clean worktree at `/tmp/phase-4.0b-wt2`, head `b020120`, remote and PR head both `b020120`.
- Auth-surface pytest: 58 passed, 3 deprecation warnings.
- PR-base verification: imports clean; auth/module-load candidates manually reviewed; scope warning remains.
- Direct `.env`-only probe: `LiveStreamServer(api_key=None)` rejects wrong key, but service-equivalent `LiveStreamServer(api_key="")` accepts wrong key.
- Isolated Ponytail session: `20260618_022611_be9fcd`.

## Next step

Return to Marvin for a focused fix cycle: use the shared auth resolver/None fallthrough contract in service wiring, add service-level `.env` fallback regression tests for live_stream/all surfaces, fix `/health` effective auth reporting, clean whitespace, then hand back to Hephaestus for a fresh Tier-1 + isolated Ponytail re-run.
