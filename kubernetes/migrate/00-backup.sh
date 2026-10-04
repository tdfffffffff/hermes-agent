#!/usr/bin/env bash
# Phase 0: Backup current VM data to local machine
# Run this BEFORE any AKS work. VM is never modified.
set -euo pipefail

SSH_KEY="$HOME/.ssh/hermes-sandbox-01_key.pem"
SSH_ARGS="-o StrictHostKeyChecking=no -p 2222 -i $SSH_KEY"
REMOTE="azureuser@127.0.0.1"
BACKUP_DIR="$(dirname "$0")/../backup"

echo "=== Phase 0: Backup ==="
echo "Backup destination: $BACKUP_DIR"
echo "Make sure your SSH tunnel is running (start-hermes-tunnel) before proceeding."
echo ""
read -p "Press Enter to start backup..."

mkdir -p "$BACKUP_DIR"/{hermes,openwebui,tokens,outputs,datasets,litellm,certs}

echo "[1/7] Backing up /data/hermes/ (profiles, state, api-keys, skills-template)..."
rsync -az --progress -e "ssh $SSH_ARGS" \
  "$REMOTE:/data/hermes/" "$BACKUP_DIR/hermes/"

echo "[2/7] Backing up OpenWebUI data (webui.db, uploads, cache)..."
rsync -az --progress -e "ssh $SSH_ARGS" \
  "$REMOTE:/data/docker/volumes/open-webui/_data/" "$BACKUP_DIR/openwebui/"

echo "[3/7] Backing up Gmail OAuth tokens..."
rsync -az --progress -e "ssh $SSH_ARGS" \
  "$REMOTE:/data/tokens/" "$BACKUP_DIR/tokens/"

echo "[4/7] Backing up user outputs..."
rsync -az --progress -e "ssh $SSH_ARGS" \
  "$REMOTE:/data/outputs/" "$BACKUP_DIR/outputs/"

echo "[5/7] Backing up datasets (382MB, may take a few minutes)..."
rsync -az --progress -e "ssh $SSH_ARGS" \
  "$REMOTE:/data/datasets/" "$BACKUP_DIR/datasets/"

echo "[6/7] Backing up LiteLLM config and stack.env..."
rsync -az --progress -e "ssh $SSH_ARGS" \
  "$REMOTE:/data/litellm/" "$BACKUP_DIR/litellm/"

echo "[7/7] Exporting LiteLLM Postgres database..."
ssh $SSH_ARGS "$REMOTE" \
  'docker exec hermes-litellm-db pg_dumpall -U litellm' \
  > "$BACKUP_DIR/litellm-postgres.sql"

echo "[cert] Backing up TLS certificate..."
rsync -az -e "ssh $SSH_ARGS" \
  "$REMOTE:/home/azureuser/certs/certbundle.crt" "$BACKUP_DIR/certs/certbundle.crt"

echo ""
echo "=== Backup complete! ==="
echo "Contents:"
du -sh "$BACKUP_DIR"/*
echo ""
echo "IMPORTANT: Now take an Azure VM disk snapshot from the Portal"
echo "  Portal → hermes-sandbox-01 → Disks → Create snapshot"
echo "  Do this before proceeding to Phase 1."
