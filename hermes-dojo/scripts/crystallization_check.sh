#!/bin/bash

echo "=========================================="
echo "HERMES DOJO SKILL CRYSTALLIZATION CHECK"
echo "=========================================="
echo ""
echo "Checking for skills created by the script..."
echo ""

# List skills in the directory
echo "=== Skills in ~/.hermes/skills ==="
ls -1 ~/.hermes/skills/ 2>/dev/null | sort -u

echo ""
echo "=== Checking for specific target skills ==="

# Check if any of our target skills exist
echo ""
echo "Checking for target skill files..."

# Check for each target skill pattern
for pattern in "shortcut-phone" "relay-channel-reporting" "commitment" "give-topic"; do
    if [ -f "/home/konan/.hermes/skills/${pattern}.md" ]; then
        echo "✓ Found: ${pattern}.md"
    else
        echo "✗ Not found: ${pattern}.md"
    fi
done

echo ""
echo "=== Checking if there are any new skills in the directory ==="
# Count skills
skill_count=$(ls -1 ~/.hermes/skills/ 2>/dev/null | wc -l)
echo "Total skills in ~/.hermes/skills: $skill_count"

echo ""
echo "=== Summary ==="
echo "If you see new skill files above, the crystallization was successful!"
