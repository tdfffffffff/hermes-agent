#!/bin/bash
# start-hermes-tunnel.sh — Open Azure Bastion tunnel + port-forwards to Hermes VM
#
# Usage:
#   1. Set the four variables below to match your Azure environment.
#   2. Run: bash deployment/scripts/start-hermes-tunnel.sh
#   3. Open http://127.0.0.1:3000 for OpenWebUI.
#   4. Press Ctrl+C to close all tunnels cleanly.
#
# Requires: Azure CLI (az) authenticated + the SSH private key for the Hermes VM.

set -e

# ── Configure these for your environment ──────────────────────────────
SUBSCRIPTION_ID="<YOUR_SUBSCRIPTION_ID>"       # az account show --query id -o tsv
RESOURCE_GROUP="<YOUR_RESOURCE_GROUP>"         # e.g. rg-hermes
VM_NAME="<YOUR_VM_NAME>"                       # e.g. hermes-sandbox-01
BASTION_NAME="<YOUR_BASTION_NAME>"             # e.g. bastion-hermes
SSH_USER="<YOUR_SSH_USER>"                     # VM username, e.g. azureuser
SSH_KEY="<YOUR_SSH_KEY_PATH>"                  # e.g. ~/.ssh/hermes-vm-key.pem
# ──────────────────────────────────────────────────────────────────────

RESOURCE_ID="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.Compute/virtualMachines/${VM_NAME}"

echo "Opening Bastion tunnel on port 2222..."
az network bastion tunnel \
  --name "$BASTION_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --target-resource-id "$RESOURCE_ID" \
  --resource-port 22 \
  --port 2222 &

BASTION_PID=$!

# Wait for port 2222 to be ready (up to 30 seconds)
for i in $(seq 1 30); do
  if nc -z 127.0.0.1 2222 2>/dev/null; then
    break
  fi
  sleep 1
done

echo "Tunnel is ready. Opening port-forwards..."

ssh -N \
  -L 3000:localhost:3000 \
  -L 5000:localhost:5000 \
  -L 8025:localhost:8025 \
  -L 8084:localhost:8084 \
  -p 2222 -i "$SSH_KEY" \
  -o StrictHostKeyChecking=no \
  "${SSH_USER}@127.0.0.1" &

SSH_PID=$!

echo ""
echo "  OpenWebUI  → http://127.0.0.1:3000"
echo "  Wrapper    → http://127.0.0.1:5000"
echo "  Mailpit    → http://127.0.0.1:8025"
echo "  Gmail MCP  → http://127.0.0.1:8084"
echo ""
echo "Press Ctrl+C to close all tunnels."

trap "kill $BASTION_PID $SSH_PID 2>/dev/null" EXIT INT TERM
wait $BASTION_PID
