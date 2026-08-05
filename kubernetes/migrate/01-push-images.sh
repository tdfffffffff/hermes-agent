#!/usr/bin/env bash
# Phase 1: Push all Hermes images to ACR
# Run FROM the VM (SSH in first, then run this script)
# Or run from local machine if you have az CLI and Docker access
set -euo pipefail

ACR_NAME="${ACR_NAME:-hermesacr}"
ACR_LOGIN_SERVER="${ACR_NAME}.azurecr.io"

echo "=== Phase 1: Push images to ACR ($ACR_LOGIN_SERVER) ==="
az acr login --name "$ACR_NAME"

# --- Import public images directly into ACR (no local pull needed) ---
echo "[1/5] Importing public images into ACR..."

az acr import --name "$ACR_NAME" \
  --source docker.io/nousresearch/hermes-agent:latest \
  --image hermes-agent:latest \
  --force

az acr import --name "$ACR_NAME" \
  --source ghcr.io/open-webui/open-webui:main \
  --image openwebui:latest \
  --force

az acr import --name "$ACR_NAME" \
  --source ghcr.io/berriai/litellm:main-latest \
  --image litellm:latest \
  --force

az acr import --name "$ACR_NAME" \
  --source docker.io/axllent/mailpit:latest \
  --image mailpit:latest \
  --force

az acr import --name "$ACR_NAME" \
  --source docker.io/postgres:17.2-alpine3.21 \
  --image postgres:17.2-alpine3.21 \
  --force

# --- Build and push custom images (run this from the VM) ---
echo "[2/5] Building hermes-wrapper (MUST be run ON the VM)..."
SSH_KEY="$HOME/.ssh/hermes-sandbox-01_key.pem"
SSH_ARGS="-o StrictHostKeyChecking=no -p 2222 -i $SSH_KEY"
REMOTE="tdf@127.0.0.1"

CUSTOM_IMAGES=(
  "hermes-wrapper:latest:/data/hermes-wrapper"
  "hermes-mailpit-mcp:latest:/data/mailpit-mcp"
  "hermes-gmail-mcp:latest:/data/gmail-mcp"
  "hermes-graph-mcp:latest:/data/graph-mcp"
  "hermes-cve-mcp:latest:/data/hermes-cve-mcp"
  "hermes-framework-mcp:latest:/data/hermes-framework-mcp"
)

for entry in "${CUSTOM_IMAGES[@]}"; do
  image="${entry%%:*}"
  tag_and_path="${entry#*:}"
  tag="${tag_and_path%%:*}"
  src_path="${tag_and_path#*:}"
  full_tag="${ACR_LOGIN_SERVER}/${image}:${tag##*/}"

  echo "Building $full_tag from $src_path on VM..."
  ssh $SSH_ARGS "$REMOTE" "
    az acr login --name $ACR_NAME
    docker build -t ${full_tag} ${src_path}
    docker push ${full_tag}
  "
done

echo ""
echo "=== Image push complete ==="
echo "Verify with: az acr repository list --name $ACR_NAME"
