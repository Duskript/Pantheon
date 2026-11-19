# 2026-11-19 — Zombie cron retired + verified auto-commit/push

**Author:** Hermes · **Thread:** Pantheon / #notifications / briefing-dawn-patrol

## 1. Zombie cron retired

`b10f2996a9ed` *"Athenaeum entity extraction (pre-Hades)"* was **removed**.

- It was a **legacy zombie**: LLM extraction was deprecated at Ichor rollout **Phase 0a**
  (*"Deprecate LLM extraction — Hades skips extract-entities.py"* ✅), so nothing drove it —
  yet the nightly job kept firing into a dead provider (cachyos-llama timeouts → 502).
- **Measured:** three durable incidents `alerted` and never recovered —
  `b10f29_1aa0ea53933c` (script, since 2026-09-19), `b10f29_3707743cb065` (auth, since 2026-09-26),
  `b10f29_176ce15bf1a7` (timeout, since 2026-10-25, last 2026-11-18). Two months, zero output.
- `hermes cron doctor` flagged it as the **only** unhealthy job in the fleet.
- **Actions:** `jobs.json` backed up → `jobs.json.bak-20261119-124343-pre-zombie-retire`;
  job removed; **all 17** stale `alerted` incidents acked (this job's 3, plus 8 for jobs that no
  longer exist: `657b31f05871`, `cfb065b056ac`, `430a627bffe0`, plus 6 for the paused Kairos jobs).
  `hermes cron doctor` → *"found no issues, checked 34 active jobs"*.
- Entity extraction is now owned by Tier-A regex (rollout 0b) + the L2/Ichor pipeline.
  **Do not resurrect the old job** — see the RETIRED banner in skill `athenaeum-extraction-fix`.

## 2. Verified auto-commit/push (new recurring job)

`~/.hermes/scripts/pantheon-verified-commit.py` + cron **`bd297b570a64`** (*every 6h*, `no_agent`).

Lands `~/pantheon` working-tree changes **only after they verify** — `[verified]` now means the
gate passed, not that someone ran `git add -A`.

- **Gate (fail-closed):** parse (`py_compile` / `bash -n` / `json` / `yaml`) → onboarding suite
  (91 tests) → `roster_install.py --check` + `conductor_onboard.py --check` → secret scan of the
  staged diff.
- **Allowlist, not `-A`:** `voice/` (40 MB venv + `.shim_token`), `god-packages/fleet-skills/`
  (67 MB mirror) and `shared/clients/` (client deliverables) are never staged.
- **Push:** `origin HEAD` on `feat/recursive-loop-phase0-1-and-l2-drainer` (ff-safe;
  never `main` — the branch is ~200 ahead / 48 behind).
- **First run landed the backlog:** commit `0098bd1` — **92 paths, +11,722 lines**, pushed.
  Working tree left clean except the three intentionally-excluded dirs.

## 3. Client onboarding — verified

| Surface | Result |
|---|---|
| Unit/contract suite | **91 passed** (`test_client_kit_roster` 21, `test_interview_engine` 27, `test_conductor_onboarding` 29, `test_portal_intake` 14) |
| `roster_install.py --check` | OK — 6 gods, conductor=hermes, 3 documented limits |
| `conductor_onboard.py --check` | OK — permission split 379968 / 51808422992 |
| Real install (scratch root) | 6 complete god trees, `tenant.json`, Codex dirs; **MEMORY.md blanked (0 B)**, no `sessions/`/`cron/`/`ichor/`, no `*.db` |
| Secret scan of generated files | clean — only empty `DISCORD_BOT_TOKEN=` / `TELEGRAM_BOT_TOKEN=` placeholders |
| `install-pantheon.sh --client --client-dry-run --phase 8b` | OK, wrote nothing |
| `install-pantheon.sh --client --client-dry-run --phase 8c --conductor-platform discord` | Plan-first: prints the 4 live-verification signals, then the ordered call list; refuses to call without `--conductor-apply` + `--conductor-token-file` |

**Honest limit:** the *live apply* (a real client tenant + the client's logged-in Discord portal
session) is not exercisable here — Phase 3 is plan-first by design. Everything up to the first
real API call is verified.

## 4. Open observations (not acted on)

- `add27402d3bc` / `634460426099` (*Daily Content Topics — Kairos / Facebook*) have been **paused
  since 2026-09-24** (~2 months). Dead weight in the job list — resume or remove.
- The three excluded dirs will keep showing as untracked. Adding them to `.gitignore` would keep
  `git status` honest, but `voice/` and `shared/clients/` are judgement calls, not obvious.
