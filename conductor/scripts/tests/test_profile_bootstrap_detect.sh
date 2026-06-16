#!/usr/bin/env bash
# test_profile_bootstrap_detect.sh — smoke test for profile-bootstrap-detect.py
#
# Verifies the 6-step brief verification end-to-end, in an isolated
# test sandbox under $TMPDIR (so canonical and per-profile are not
# touched). The script is exercised with --canonical-root and
# --profiles-root pointing at fixtures.
#
# Run:  bash ~/pantheon/conductor/scripts/tests/test_profile_bootstrap_detect.sh
# Exit: 0 on all pass, 1 on any failure.
set -uo pipefail

SCRIPT="$HOME/pantheon/conductor/scripts/profile-bootstrap-detect.py"
WORK="$(mktemp -d -t pbd-test-XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

pass=0
fail=0

assert() {
  local label="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    echo "  PASS  $label (got $actual)"
    pass=$((pass + 1))
  else
    echo "  FAIL  $label  expected=$expected  actual=$actual"
    fail=$((fail + 1))
  fi
}

# --- build fixtures ---------------------------------------------------------
# Layout: $WORK/canon/<cat>/<skill>/SKILL.md
#         $WORK/profiles/<god>/skills/<cat>/<skill>/SKILL.md  (regular file = drift)
#         $WORK/profiles/<god>/skills/<cat>/<skill>/SKILL.md  (symlink  = good)
#         $WORK/profiles/<god>/skills/<cat>/<no-canon-skill>/SKILL.md (drift; will be filtered)
#         $WORK/no_canon.txt  (no_canon report listing the filterable entry)

mkdir -p "$WORK/canon/dev/caddy-vhost-routing"
echo "canonical caddy" > "$WORK/canon/dev/caddy-vhost-routing/SKILL.md"
mkdir -p "$WORK/canon/dev/ci-test-skill"
echo "canonical ci test" > "$WORK/canon/dev/ci-test-skill/SKILL.md"
mkdir -p "$WORK/canon/dev/ci-fixture-only"
echo "canonical ci fixture" > "$WORK/canon/dev/ci-fixture-only/SKILL.md"

# 7 target god profiles; mark 3 of them as having a symlink for ci-test-skill
# (correct state), the other 4 as missing, and 1 with a regular file (drift).
for god in apollo cachyos hephaestus iris marvin rheta thoth; do
  mkdir -p "$WORK/profiles/$god/skills/dev/ci-test-skill"
  mkdir -p "$WORK/profiles/$god/skills/dev/caddy-vhost-routing"
  mkdir -p "$WORK/profiles/$god/skills/dev/ci-fixture-only"
done
# good state: apollo symlinks both
ln -sf "$WORK/canon/dev/ci-test-skill/SKILL.md" "$WORK/profiles/apollo/skills/dev/ci-test-skill/SKILL.md"
ln -sf "$WORK/canon/dev/caddy-vhost-routing/SKILL.md" "$WORK/profiles/apollo/skills/dev/caddy-vhost-routing/SKILL.md"
# drift (regular file): cachyos has ci-test-skill as a real file
echo "drift" > "$WORK/profiles/cachyos/skills/dev/ci-test-skill/SKILL.md"
# missing: hephaestus, iris, marvin, rheta, thoth have nothing for ci-test-skill

# NO-CANON fixture: pretend ci-fixture-only is intentional per-profile-only for rheta
cat > "$WORK/no_canon.txt" <<'EOF'
# test no_canon fixture
rheta|dev|ci-fixture-only|/dummy/path/SKILL.md|2026-06-15 00:00:00|0
EOF

# --- run tests -------------------------------------------------------------

echo "--- Test 1: --canonical-root/--profiles-root flags work + exit 0 on good run ---"
out=$(python3 "$SCRIPT" --canonical-root "$WORK/canon" --profiles-root "$WORK/profiles" --no-canon-report "$WORK/no_canon.txt" 2>/dev/null)
rc=$?
assert "exit code" 0 "$rc"
echo "  output: $(echo "$out" | tr '\n' '|' | sed 's/|$//')"

echo "--- Test 2: NO-CANON filter applied (rheta ci-fixture-only absent) ---"
if echo "$out" | grep -q "rheta.*ci-fixture-only"; then
  assert "rheta ci-fixture-only filtered" 0 "1"
else
  assert "rheta ci-fixture-only filtered" 0 "0"
fi

echo "--- Test 3: caddy-vhost-routing appears 6 times (apollo has symlink, other 6 don't) ---"
count=$(echo "$out" | grep -c "caddy-vhost-routing")
assert "caddy-vhost-routing count" 6 "$count"

echo "--- Test 4: ci-test-skill appears 5 times (apollo symlink, cachyos drift logged but not in output, other 5 missing) ---"
count=$(echo "$out" | grep -c "ci-test-skill")
assert "ci-test-skill count (drift in stderr not stdout)" 5 "$count"

echo "--- Test 5: cachyos ci-test-skill is NOT in output (path is present as regular file) ---"
if echo "$out" | grep -q "^cachyos.*ci-test-skill"; then
  assert "cachyos ci-test-skill in output" "no" "yes"
else
  assert "cachyos ci-test-skill in output" "no" "no"
fi

echo "--- Test 6: cachyos ci-test-skill IS in stderr as drift ---"
err=$(python3 "$SCRIPT" --canonical-root "$WORK/canon" --profiles-root "$WORK/profiles" --no-canon-report "$WORK/no_canon.txt" 2>&1 >/dev/null)
if echo "$err" | grep -q "cachyos.*ci-test-skill.*regular file"; then
  assert "cachyos drift in stderr" "yes" "yes"
else
  assert "cachyos drift in stderr" "yes" "no"
fi

echo "--- Test 7: --json output is valid JSON with right shape ---"
json=$(python3 "$SCRIPT" --canonical-root "$WORK/canon" --profiles-root "$WORK/profiles" --no-canon-report "$WORK/no_canon.txt" --json 2>/dev/null)
if echo "$json" | python3 -c "import json, sys; data = json.load(sys.stdin); assert all('god' in d and 'category' in d and 'skill_name' in d for d in data); sys.exit(0)" 2>/dev/null; then
  assert "json shape" "ok" "ok"
else
  assert "json shape" "ok" "bad"
fi

echo "--- Test 8: exit 1 on missing canonical root ---"
rc=$(python3 "$SCRIPT" --canonical-root /no/such/path --profiles-root "$WORK/profiles" >/dev/null 2>&1; echo $?)
assert "exit code on bad root" 1 "$rc"

echo "--- Test 9: no_canon tuple count from stderr ---"
err=$(python3 "$SCRIPT" --canonical-root "$WORK/canon" --profiles-root "$WORK/profiles" --no-canon-report "$WORK/no_canon.txt" 2>&1 >/dev/null)
loaded=$(echo "$err" | grep -oP "loaded: \K\d+" || echo "0")
assert "no_canon tuples loaded" 1 "$loaded"

echo "--- Test 10: no_canon report missing -> warn to stderr, filter disabled, exit 0 ---"
# When the no_canon report is missing, parse_no_canon warns to stderr and
# returns an empty set, so the script runs normally. We just want to
# verify it doesn't crash with exit 1.
out=$(python3 "$SCRIPT" --canonical-root "$WORK/canon" --profiles-root "$WORK/profiles" --no-canon-report /no/such/file 2>/dev/null)
rc=$?
assert "exit with missing no_canon report" 0 "$rc"
# And the output should still include the rheta ci-fixture-only entry
# (since the filter is disabled, nothing is filtered out)
if echo "$out" | grep -q "rheta.*ci-fixture-only"; then
  assert "rheta ci-fixture-only NOT filtered (filter disabled)" "yes" "yes"
else
  assert "rheta ci-fixture-only NOT filtered (filter disabled)" "yes" "no"
fi

echo
echo "============================================================"
echo "Results: $pass passed, $fail failed"
echo "============================================================"
[[ "$fail" -eq 0 ]] || exit 1
exit 0
