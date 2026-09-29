# Pantheon Reliability & Efficiency Fixes

**Date:** 2026-08-06  
**Owner:** Hermes / Pantheon Ops  
**Scope:** Reliability, efficiency, upgrade-readiness, and operational cleanup for Pantheon/Hermes.  
**Explicit exclusion:** This document **does not include the Thoth/Hermes-LCM canary/test plan**. LCM is being evaluated separately and should not be treated as a cleanup target from this document.

## Executive Summary

Pantheon is powerful but carrying operational drift: stale systemd units, failed timers, duplicated service paths, noisy dead services, dirty repo state, and incomplete queue/data lifecycle policy. The recommended path is to stabilize the runtime first, then consider Hermes upgrades or architecture consolidation.

**Recommended order:**

1. Fix stale/broken systemd service units.
2. Fix `ichor-tick.service` timeout.
3. Disable or archive dead/obsolete failed units.
4. Add fleet config drift guard.
5. Add memory/swap watchdog for god gateways.
6. Clean repo hygiene and test collection.
7. Add Conductor pending queue lifecycle policy.
8. Add Ichor DB retention/maintenance policy.
9. Build upgrade-readiness preflight.
10. Later: evaluate gateway multiplexing/consolidation.

---

## P0 — Fix Before Upgrade

### 1. Regenerate/fix stale systemd service units

**Evidence found:** multiple units reference the deleted user venv path:

```text
/home/konan/.hermes/hermes-agent/venv/bin/python: No such file or directory
```

Affected units observed:

- `clawforge-pattern-export-dojo.service`
- `clawforge-pattern-export-forge.service`
- `clawforge-pattern-export-memory.service`
- `clawforge-proxy.service`
- `pantheon-quarantine-sweeper.service`
- `pantheon-webhook-olympus.service`
- `pantheon-webhook-enterprise.service`
- `inbox-watcher.service`
- `inbox-notifier.service`

Additional unit drift:

- `hermes-gateway@.service` has `TimeoutStopSec=30s` while gateway drain expects >=90s.
- Risk: systemd can SIGKILL gateways mid-drain.

**Fix:**

- Standardize `ExecStart` paths to the active runtime, currently:

```text
/usr/local/lib/hermes-agent/venv/bin/python
```

- Regenerate gateway units where possible with the canonical Hermes command.
- Set/verify `TimeoutStopSec >= 90s` for Hermes gateway services.
- Run `systemctl --user daemon-reload`.
- Restart/verify each repaired unit.
- Reset failed state only after repair:

```bash
systemctl --user reset-failed <unit>
```

**Verification:**

```bash
systemctl --user --failed
systemctl --user status <unit> --no-pager
journalctl --user -u <unit> -n 50 --no-pager
```

---

### 2. Fix `ichor-tick.service` timeout

**Evidence found:** `ichor-tick.service` repeatedly starts, loads the embedder, then systemd kills it at the 2-minute timeout.

Observed pattern:

```text
INFO wrote ... entries to retrieval-log.jsonl
INFO Loading embedder model BAAI/bge-small-en-v1.5...
INFO Embedder loaded (dim=384)
ichor-tick.service: start operation timed out. Terminating.
```

**Why it matters:** Ichor is the long-term memory/learning substrate. If scheduled ticks never complete, learning and summarization quality slowly degrade while the service remains noisy.

**Fix options:**

Option A — quick operational fix:

- Increase service timeout to 10-15 minutes.
- Keep the current monolithic tick behavior.

Option B — better reliability fix:

- Split tick into bounded phases:
  1. retrieval log update
  2. embedder load/check
  3. promotions
  4. maintenance/forge/export
- Add checkpoints so reruns resume instead of restarting the full workload.

**Recommendation:** do Option A immediately, then design Option B.

**Verification:**

```bash
systemctl --user start ichor-tick.service
systemctl --user status ichor-tick.service --no-pager
journalctl --user -u ichor-tick.service -n 100 --no-pager
```

---

### 3. Hold Hermes upgrades until preflight is clean

**Evidence found:** Hermes is an editable git install with local divergence:

```text
Hermes Agent v0.20.0
+1 carried commit
checkout main...origin/main [ahead 1, behind 1]
```

Pantheon repo also has substantial local drift:

- 83 dirty paths observed.
- Branch `local-snapshot` has upstream divergence.
- Generated DBs/worktrees/reports exist inside the repo tree.

**Why it matters:** a Hermes update can combine upstream changes, local patch loss, stale service units, and gateway restarts into one messy failure. Bad deal. Very Chaos-coded.

**Fix:** create an upgrade-readiness preflight and require green status before upgrade.

Preflight must capture:

- Hermes version and carried commits.
- Hermes checkout status.
- Pantheon repo dirty status.
- Profile config parse status.
- Failed user services.
- Stale service paths.
- Cron job snapshot.
- Route baseline.
- Auth/profile config snapshots.

**Verification:** no Hermes upgrade should proceed while any P0 item is red.

---

## P1 — Operational Reliability

### 4. Disable/archive obsolete failed units

**Evidence found:** failed units include old Clawforge exports, old proxy, failed Ichor tick, and old duplicate Thoth gateway service.

**Fix:** classify each failed unit:

- **Keep and fix** — live function still needed.
- **Disable timer but keep unit** — future/paused work.
- **Archive/delete unit** — obsolete/no longer used.
- **Replace with Hermes cron** — better fit for scheduled lightweight jobs.

**Why it matters:** failed-unit noise trains the system to ignore red lights. Health reports should distinguish real incidents from archaeology.

**Verification:**

```bash
systemctl --user --failed
systemctl --user list-timers --all
```

Target: failed units should be zero, or every failed unit should have an explicit owner/status note.

---

### 5. Add fleet config drift guard

**Problem:** profile configs can drift back into known-bad or inconsistent states without a human noticing.

**Guard should check every profile for:**

- model provider and model route consistency
- required provider blocks
- plugin allow/deny list
- gateway allowed channels/routing
- required env file references
- stale or deleted script paths
- YAML validity

**Output style:** no-agent watchdog; silent when clean, concise alert when drift appears.

**Verification:** intentional test drift in one profile should produce one clear alert and no repeated spam.

---

### 6. Add memory/swap watchdog for god gateways

**Evidence found:** recent gateway pressure caused high swap and forced restarts. Marvin was confirmed as a swap hog earlier; Thoth historical service also had a prior large memory/swap failure on the old duplicate unit.

**Watchdog should record per gateway:**

- RSS
- swap
- cgroup memory current/peak
- open file descriptors
- `CLOSE-WAIT` sockets
- process uptime
- restart count

**Suggested thresholds:**

- Warn: RSS > 750MB or swap > 250MB
- Urgent: RSS > 1.5GB or swap > 1GB
- Controlled restart candidate: RSS > 2.5GB or swap > 2GB, only if safe/idle

**Verification:** watchdog emits nothing when clean; emits exact PID/unit/metrics when threshold crossed.

---

### 7. Add Conductor pending queue lifecycle policy

**Evidence found:** quarantine was cleared, but live pending handoffs remained across several inboxes after cleanup.

**Fix:** add age and owner visibility:

- pending count by inbox
- oldest pending item by inbox
- age buckets:
  - <1h
  - 1-24h
  - 1-7d
  - >7d
- action policy:
  - active work stays
  - stale non-protected items archive
  - protected/manual-review items stay but are called out

**Verification:** Conductor dashboard/report shows pending age, not just raw count.

---

### 8. Add Ichor DB retention and maintenance policy

**Evidence found:** live Ichor DB is large and active, with hundreds of thousands of events.

**Fix:** define tiers:

- hot recent events: full fidelity
- warm summarized events: compacted but queryable
- cold archive: retained for audit/history but excluded from hot paths

Add scheduled maintenance:

```sql
PRAGMA optimize;
VACUUM;
```

Only run heavy maintenance during quiet windows.

**Verification:** track DB size, query latency, event counts, and maintenance completion time.

---

## P2 — Repo/Test Hygiene

### 9. Clean generated/runtime artifacts out of the Pantheon repo

**Evidence found:** repo contains generated/runtime-heavy directories and files, including DBs, backups, graph indexes, old worktrees, and generated reports.

Examples observed:

- `.code-review-graph/`
- `.backups/`
- runtime/log/generated report files
- `pr35-*` worktree directories
- local DB files

**Fix:**

- Move runtime/generated data outside repo or add to `.gitignore`.
- Archive/delete old PR worktrees after confirming no needed changes.
- Keep source, docs, tests, and intentional fixtures in repo; keep runtime state out.

**Verification:**

```bash
git status --short
```

Target: dirty state should represent intentional source/doc changes, not runtime debris.

---

### 10. Fix pytest collection and dependency posture

**Evidence found:** test collection found many tests, then failed on missing `nats` dependency.

**Fix:**

- Add missing dependency (`nats-py`) to the correct requirements/pyproject path, or mark NATS integration tests optional.
- Add/verify pytest exclusions for generated and vendored directories:
  - `.venv`
  - `venv`
  - `hermes-agent`
  - `pr35-*`
  - `.code-review-graph`
  - runtime data dirs

**Verification:**

```bash
python3 -m pytest --collect-only -q tests
```

Target: collection completes, and test count is stable/intentional.

---

## P3 — Architecture / Efficiency

### 11. Evaluate gateway multiplexing/consolidation

**Current pattern:** many separate god gateway services, each with its own process, sidecars, config, and restart surface.

**Potential improvement:** use Hermes profile routing/multiplexing to collapse some gods into fewer gateway processes.

**Trade-off:**

- Pros: less RAM, less systemd/config drift, simpler upgrades.
- Cons: less process isolation; one crash can affect multiple gods.

**Recommendation:** staged evaluation only. Do not big-bang migrate.

Possible path:

1. Keep high-risk/heavy gods isolated.
2. Test multiplexing with low-traffic gods first.
3. Keep old per-profile service units as rollback.
4. Verify correct persona/profile routing by channel/thread.

---

### 12. Create route ownership map

**Evidence found:** multiple web/API layers expose overlapping or confusing routes across ports. Some routes return 200, some 401, some 404 depending on owner/service.

**Fix:** create a route ownership document/table:

| Route | Port/service | Owner | Auth behavior | Expected status | Upgrade risk |
|---|---|---|---|---|---|
| `/health` | gateway ports | Hermes gateway | public | 200 | low |
| `/api/status` | dashboard/webui | varies | varies | known baseline | medium |
| `/api/gods/` | dashboard/webui | varies | often auth-gated | known baseline | medium |

**Verification:** route baseline script should run before and after any upgrade.

---

### 13. Reduce health-report hallucination/noise

**Problem:** recent reports included phantom/stale claims, such as a proxy check for `:8640` even though the actual Hermes proxy listens on `:8645` and no health script referenced `:8640`.

**Fix:**

- Health collectors should emit machine-readable evidence.
- LLM synthesis must not invent service state beyond collector output.
- If collector has `## Script Error`, downstream digest must report only the error.
- Every red item should include source, command/check, timestamp, and owner.

**Verification:** inject a failed collector output and verify the digest reports the failure honestly without generated filler.

---

## Reference Commands

Useful audit commands:

```bash
systemctl --user --failed
systemctl --user list-units --type=service --state=running,failed
systemctl --user list-timers --all
free -h
ss -tlnp
ps -eo pid,ppid,rss,etime,cmd --sort=-rss | head -40
```

Repo checks:

```bash
cd /home/konan/pantheon
git status --short
git branch --show-current
git rev-list --left-right --count origin/local-snapshot...HEAD || true
python3 -m pytest --collect-only -q tests
```

Hermes upgrade preflight checks:

```bash
hermes version
cd /home/konan/.hermes/hermes-agent && git status --short --branch
hermes cron list
find /home/konan/.hermes/profiles -name config.yaml -print
```

Route baseline example:

```bash
for port in 8642 8644 8648 9119 9120 8787 8788; do
  for path in / /health /api/status /api/gods/ /api/auth/me; do
    curl -s -o /dev/null -w "$port $path %{http_code}\n" --max-time 2 "http://127.0.0.1:${port}${path}"
  done
done
```

---

## Out of Scope

- Thoth/Hermes-LCM canary analysis and rollback decisions.
- X/Twitter auth repair for `last30days`.
- Product/marketing roadmap prioritization.
- New feature work.

This document is the cleanup/reference plan for making Pantheon more reliable and efficient before the next major upgrade or architecture change.

---

## Completion Notes — 2026-08-07 Hermes Top-Moves Pass

Executed by Hermes after Konan approved the top reliability moves. This section records what actually landed and the verification evidence.

### Completed

1. **Systemd stale-path cleanup**
   - `hermes-gateway@.service`: `TimeoutStopSec=90`.
   - `hermes-webui.service`: `TimeoutStopSec=90`.
   - `consignment-thoth-bridge.service`: `PYTHONPATH=/usr/local/lib/hermes-agent/venv/lib/python3.11/site-packages`.
   - Removed stale `~/.hermes/vendor/py311` from live gateway/MCP drop-ins while preserving required messaging, zvec, and Pantheon paths.
   - Added `EnvironmentFile=-/home/konan/.hermes/.env` to `pantheon-mcp.service` and `ichor-tick.service`.
   - Removed inline provider keys from `pantheon-mcp.service.d/override.conf` and `ichor-tick.service.d/override.conf`; provider secrets now come from the global env file instead of systemd drop-ins.
   - Backups were written under:
     - `/home/konan/.config/systemd/user/.pantheon-fixes-backup/`
     - `/home/konan/pantheon/.ops-backups/`

2. **Ichor tick repair**
   - `ichor-tick.service`: `ICHOR_TICK_MAX_SECONDS=300`, `TimeoutStartSec=900`.
   - `lib/ichor_tick.py`: runtime cap now reads `ICHOR_TICK_MAX_SECONDS` for live service runs while preserving the 30s default for the original D1 gate behavior.
   - `lib/ichor_tick.py`: provider fallback now loads the provider named `opencode-go` directly instead of treating `opencode-go` as a god/profile name.
   - `lib/ichor_tick.py` and `lib/ichor/llm.py`: hyphenated provider env lookup now normalizes `opencode-go` to `OPENCODE_GO_API_KEY` instead of the invalid `OPENCODE-GO_API_KEY`.

3. **Failed/dead unit classification**
   - Live `systemctl --user --failed` check returned `0 loaded units listed` after repairs.
   - Clawforge export units were inactive but timer-owned and path-fixed, so they were not disabled.

4. **Watchdogs installed**
   - Script: `/home/konan/.hermes/scripts/pantheon-fleet-config-drift-guard.py`.
     - Cron: `3a5f66634ed4` — **Pantheon Fleet Config Drift Guard**, `every 60m`, `no_agent`, deliver `origin` only if stdout is non-empty.
   - Script: `/home/konan/.hermes/scripts/pantheon-gateway-memory-watchdog.py`.
     - Cron: `37f84f1bf0a2` — **Pantheon Gateway Memory/Swap Watchdog**, `every 15m`, `no_agent`, deliver `origin` only if stdout is non-empty.
   - Both scripts are silent when clean and exit `0` for alert delivery; non-zero is reserved for script/runtime failure.

### Verification Evidence

- Python parse/compile:
  - `py_compile` passed for `lib/ichor_tick.py`, `lib/ichor/llm.py`, and both watchdog scripts.
- Focused tests:
  - `/usr/local/lib/hermes-agent/venv/bin/python -m pytest tests/test_ichor_d1_learning_tick.py tests/test_ichor_b5_tier_a_plus.py -q`
  - Result: `48 passed in 2.99s`.
- Ichor live service run:
  - `systemctl --user start ichor-tick.service` exited `0`.
  - Latest proof: `extract 24.094s  batches=4 | events=40 | entities=39 | rels=55`.
  - `finalize 0.011s  flipped_ents=39 | flipped_rels=55`.
  - Service completed successfully with `258.6M memory peak` over `47.668s` wall clock.
- Live unit drift scan:
  - Result: `live_unit_drift_issues: []`, `count: 0`.
- Failed units:
  - `systemctl --user --failed --no-pager` returned `0 loaded units listed`.
- Watchdog smoke:
  - Fleet drift guard debug: `Pantheon fleet config drift guard: clean`.
  - Gateway memory/swap watchdog debug: `clean`; main gateway at roughly `571MB RSS / 214MB swap`, Thoth at roughly `290MB RSS / 63MB swap`, and all god gateways below alert thresholds.

### Still Explicitly Out of Scope

- Thoth/Hermes-LCM canary decision remains untouched by this pass.
- Existing gateway processes may retain old environment variables until their next normal restart; live unit/drop-in files are clean, and the watchdog watches config drift going forward without forcing a gateway bounce.

