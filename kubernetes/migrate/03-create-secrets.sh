#!/usr/bin/env bash
# Phase 3: Create K8s Secrets and ConfigMaps from backup
# Run AFTER 02-create-cluster.sh. Reads from ../backup/
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="$SCRIPT_DIR/../backup"
NS="hermes"

echo "=== Phase 3: Creating Secrets and ConfigMaps ==="

# ── Extract WEBUI_SECRET_KEY from stack.env ───────────────────
WEBUI_SECRET_KEY=$(grep '^WEBUI_SECRET_KEY=' "$BACKUP_DIR/litellm/stack.env" | cut -d= -f2-)
if [[ -z "$WEBUI_SECRET_KEY" ]]; then
  echo "ERROR: WEBUI_SECRET_KEY not found in backup/litellm/stack.env"
  exit 1
fi

# ── LiteLLM env (all credentials) ────────────────────────────
echo "[1/5] Creating litellm-env secret..."
kubectl create secret generic litellm-env -n "$NS" \
  --from-env-file="$BACKUP_DIR/litellm/stack.env" \
  --dry-run=client -o yaml | kubectl apply -f -

# ── TLS certificate ───────────────────────────────────────
# Use server-side apply for large cert — avoids 256KB client annotation limit
echo "[2/5] Creating hermes-cert secret..."
kubectl create secret generic hermes-cert -n "$NS" \
  --from-file=certbundle.crt="$BACKUP_DIR/certs/certbundle.crt" \
  --dry-run=client -o yaml | kubectl apply --server-side -f -

# ── OpenWebUI secret key ──────────────────────────────────────
echo "[3/5] Creating openwebui-env secret..."
kubectl create secret generic openwebui-env -n "$NS" \
  --from-literal=WEBUI_SECRET_KEY="$WEBUI_SECRET_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

# ── LiteLLM config.yaml ───────────────────────────────────────
echo "[4/5] Creating litellm-config ConfigMap..."
kubectl create configmap litellm-config -n "$NS" \
  --from-file=config.yaml="$BACKUP_DIR/litellm/config.yaml" \
  --dry-run=client -o yaml | kubectl apply -f -

# ── Per-user API keys ─────────────────────────────────────────
echo "[5/5] Creating hermes-api-keys secret..."
kubectl create secret generic hermes-api-keys -n "$NS" \
  --from-file=api-keys.json="$BACKUP_DIR/hermes/api-keys.json" \
  --dry-run=client -o yaml | kubectl apply -f -

echo ""
echo "=== Secrets created. Verify with: kubectl get secrets -n hermes ==="
kubectl get secrets -n "$NS"
