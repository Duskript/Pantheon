# Forge cron dedup finding — 2026-08-01 23:37 MDT (2nd dispatch of the night)

The 23:30 forge cron dispatched TWICE tonight (two full cycles ran 4 min apart).
Root cause: THREE registrations named "Ichor Forge — Nightly Harness Analysis",
all on `30 23 * * *`:

- /home/konan/.hermes/cron/jobs.json          id=9a8a0bae3225  CORRECT prompt (lib/ichor_forge.py)
- /home/konan/.hermes/cron/jobs.json          id=1cef23871068  STALE (pantheon-core/ichor/forge.py)
- /home/konan/.hermes/profiles/thoth/cron/jobs.json  id=741e0fca4fd3  STALE (same)

Earlier cycle summary (NIGHTLY-SUMMARY.md 2026-08-02/05:33 UTC) flagged the two
stale jobs but did NOT find 9a8a0bae3225 (correct prompt). Recommended fix for
Konan: keep 9a8a0bae3225, DELETE 1cef23871068 and 741e0fca4fd3 (or rewrite their
prompts to the correct path + HOME=/home/konan). Manual cron edit required —
cross-profile cron files are not agent-editable.

Findings of both cycles agree: 15 interventions / 7d, all logic_gate, 100% block
rate = healthy gate (12x leftover print, 2x bare except, 1x mislabeled gumroad
JSON). Smith's 1 proposal (print rule → god_system_prompt) REJECTED — already
deployed everywhere (behavioral gap). Weights unchanged (+0.00%). Posture STABLE.
