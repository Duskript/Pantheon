#!/usr/bin/env bash
# u55-fix.sh — Quick U55 boot fix for sdhci cascade on Ubuntu 26.04
# Run once on each new U55 after install.
# Usage: sudo ./u55-fix.sh

set -euo pipefail

echo "=== U55 Boot Fix ==="

# 1. Blacklist the SDHCI driver that crashes on U55 hardware
echo "  → Blacklisting sdhci/sdhci_pci/sdhci_acpi..."
cat > /etc/modprobe.d/blacklist-sdhci.conf << 'EOF'
# U55: SDHCI controller hangs on kernel 7.0.0+, cascades into boot failure
blacklist sdhci
blacklist sdhci_pci
blacklist sdhci_acpi
EOF

# 2. Rebuild initramfs so the blacklist takes effect
echo "  → Rebuilding initramfs..."
update-initramfs -u

# 3. Update GRUB
echo "  → Updating GRUB..."
update-grub

echo ""
echo "=== Done! Reboot and the cascade should be gone. ==="
