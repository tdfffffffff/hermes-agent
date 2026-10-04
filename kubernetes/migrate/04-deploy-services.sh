#!/usr/bin/env bash
# Phase 4: Deploy all core services to AKS
# Run AFTER 03-create-secrets.sh
set -euo pipefail

ACR_NAME="${ACR_NAME:-hermesaksacr}"
ACR_LOGIN_SERVER="${ACR_NAME}.azurecr.io"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
K8S_DIR="$SCRIPT_DIR/../k8s"
NS="hermes"

echo "=== Phase 4: Deploying services to AKS ==="
echo "ACR: $ACR_LOGIN_SERVER"
echo ""

# Substitute ACR_LOGIN_SERVER placeholder in manifests and apply
apply_manifest() {
  local file="$1"
  echo "Applying $file..."
  sed "s|ACR_LOGIN_SERVER|${ACR_LOGIN_SERVER}|g" "$file" | kubectl apply -f -
}

echo "[1/9] Namespace + RBAC..."
kubectl apply -f "$K8S_DIR/namespace.yaml"
kubectl apply -f "$K8S_DIR/rbac.yaml"

echo "[2/9] Datasets PVC..."
kubectl apply -f "$K8S_DIR/datasets-pvc.yaml"

echo "[3/9] Mailpit..."
kubectl apply -f "$K8S_DIR/mailpit.yaml"

echo "[4/9] LiteLLM Postgres..."
kubectl apply -f "$K8S_DIR/litellm-postgres.yaml"
echo "Waiting for Postgres to be ready (up to 2 min)..."
kubectl rollout status statefulset/litellm-postgres -n "$NS" --timeout=120s

echo "[5/9] LiteLLM proxy..."
kubectl apply -f "$K8S_DIR/litellm.yaml"

echo "[6/9] OpenWebUI..."
kubectl apply -f "$K8S_DIR/openwebui.yaml"

echo "[7/9] Hermes wrapper..."
apply_manifest "$K8S_DIR/hermes-wrapper.yaml"

echo "[8/9] MCP services..."
apply_manifest "$K8S_DIR/mcp-services.yaml"

echo "[9/9] Waiting for all deployments to be ready..."
for deploy in mailpit hermes-litellm-proxy openwebui hermes-wrapper \
              hermes-mailpit-mcp hermes-gmail-mcp hermes-graph-mcp \
              hermes-cve-mcp hermes-framework-mcp; do
  echo "  Waiting for $deploy..."
  kubectl rollout status deployment/$deploy -n "$NS" --timeout=120s 2>/dev/null || \
  kubectl rollout status statefulset/$deploy -n "$NS" --timeout=120s 2>/dev/null || true
done

echo ""
echo "=== Services deployed. Current pod status: ==="
kubectl get pods -n "$NS"
