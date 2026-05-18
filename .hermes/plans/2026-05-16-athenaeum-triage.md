# Athenaeum triage implementation plan

Goal: add a small failure triage layer that turns Hades/Athenaeum noise into actionable morning status.

Architecture: core logic lives in `pantheon-core/gods/athenaeum_triage.py` so it can be tested and reused. A thin script at `~/athenaeum/scripts/athenaeum-triage.py` writes reports and emits a short summary for cron or morning briefing. `~/.hermes/scripts/morning-briefing.py` calls the script and includes the `ATHENAEUM_TRIAGE` section.

## Tasks

1. Add tests for Hades markdown parsing and issue classification.
Files: `pantheon-core/tests/test_athenaeum_triage.py`
Verify: `cd ~/pantheon/pantheon-core && pytest tests/test_athenaeum_triage.py -q` fails before implementation.

2. Implement triage core.
Files: `pantheon-core/gods/athenaeum_triage.py`
Verify: targeted tests pass.

3. Add executable wrapper script.
Files: `~/athenaeum/scripts/athenaeum-triage.py`
Verify: `python3 ~/athenaeum/scripts/athenaeum-triage.py --stdout-only` prints compact status.

4. Wire morning briefing data collection.
Files: `~/.hermes/scripts/morning-briefing.py`
Verify: running the script includes `=== ATHENAEUM_TRIAGE ===` and does not crash if triage fails.

5. Run full verification.
Commands: targeted pytest, script against live Hades report, output file readback.
