#!/bin/bash
systemctl --user restart hermes-gateway-iris hermes-gateway-hephaestus hermes-gateway-caduceus hermes-gateway-kairos hermes-gateway-rheta hermes-gateway-apollo pantheon-mcp
echo "Gateways restarted at $(date)"
