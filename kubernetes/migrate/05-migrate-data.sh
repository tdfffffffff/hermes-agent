#!/usr/bin/env bash
# Phase 6: Migrate existing user data from VM backup into AKS PVCs
# Run AFTER 04-deploy-services.sh and after services are Running.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="$SCRIPT_DIR/../backup"
NS="hermes"

echo "=== Phase 6: Data Migration ==="
echo "Reading backup from: $BACKUP_DIR"
echo ""

# ── Helper: run a temporary busybox pod with a PVC mounted ───────────
loader_pod() {
  local pod="$1"
  local pvc="$2"
  local mount="$3"
  kubectl run "$pod" -n "$NS" \
    --image=busybox --restart=Never \
    --overrides="{
      \"spec\": {
        \"volumes\": [{\"name\": \"vol\", \"persistentVolumeClaim\": {\"claimName\": \"$pvc\"}}],
        \"containers\": [{
          \"name\": \"c\",
          \"image\": \"busybox\",
          \"command\": [\"sleep\", \"600\"],
          \"volumeMounts\": [{\"name\": \"vol\", \"mountPath\": \"$mount\"}]
        }]
      }
    }" 2>/dev/null || true
  # Wait for it to be Running
  local deadline=$((SECONDS + 60))
  while [[ $SECONDS -lt $deadline ]]; do
    status=$(kubectl get pod "$pod" -n "$NS" -o jsonpath='{.status.phase}' 2>/dev/null || echo "")
    [[ "$status" == "Running" ]] && return 0
    sleep 2
  done
  echo "ERROR: loader pod $pod did not reach Running state"
  return 1
}

cleanup_pod() {
  kubectl delete pod "$1" -n "$NS" --ignore-not-found=true
}

# ── 1. Wrapper data (api-keys.json, skills-template, profile templates) ─
echo "[1/6] Migrating hermes wrapper data into hermes-wrapper-data PVC..."
loader_pod "loader-wrapper" "hermes-wrapper-data" "/data"
kubectl cp "$BACKUP_DIR/hermes/" "$NS/loader-wrapper:/data/hermes/"
cleanup_pod "loader-wrapper"
echo "  Done."

# ── 2. Datasets ─────────────────────────────────────────────────────
echo "[2/6] Migrating datasets into hermes-datasets PVC (this may take a few minutes)..."
loader_pod "loader-datasets" "hermes-datasets" "/data"
kubectl cp "$BACKUP_DIR/datasets/" "$NS/loader-datasets:/data/"
cleanup_pod "loader-datasets"
echo "  Done."

# ── 3. Gmail OAuth tokens ────────────────────────────────────────────
echo "[3/6] Migrating Gmail OAuth tokens into hermes-gmail-tokens PVC..."
loader_pod "loader-tokens" "hermes-gmail-tokens" "/tokens"
kubectl cp "$BACKUP_DIR/tokens/." "$NS/loader-tokens:/tokens/"
cleanup_pod "loader-tokens"
echo "  Done."

# ── 4. OpenWebUI SQLite DB ───────────────────────────────────────────
echo "[4/6] Migrating OpenWebUI webui.db..."
OWUI_POD=$(kubectl get pod -n "$NS" -l app=openwebui -o jsonpath='{.items[0].metadata.name}')
kubectl cp "$BACKUP_DIR/openwebui/webui.db" "$NS/$OWUI_POD:/app/backend/data/webui.db"
kubectl exec -n "$NS" "$OWUI_POD" -- sh -c "chown 1000:1000 /app/backend/data/webui.db 2>/dev/null || true"
# Also copy uploads, cache, vector_db if they exist
for subdir in uploads cache vector_db; do
  if [[ -d "$BACKUP_DIR/openwebui/$subdir" ]]; then
    kubectl cp "$BACKUP_DIR/openwebui/$subdir/." "$NS/$OWUI_POD:/app/backend/data/$subdir/"
  fi
done
echo "  Restarting OpenWebUI to pick up new DB..."
kubectl rollout restart statefulset/openwebui -n "$NS"
kubectl rollout status statefulset/openwebui -n "$NS" --timeout=60s
echo "  Done."

# ── 5. LiteLLM Postgres ─────────────────────────────────────────────
echo "[5/6] Restoring LiteLLM Postgres from dump..."
PG_POD=$(kubectl get pod -n "$NS" -l app=litellm-postgres -o jsonpath='{.items[0].metadata.name}')
kubectl exec -i -n "$NS" "$PG_POD" -- psql -U litellm < "$BACKUP_DIR/litellm-postgres.sql"
echo "  Done."

# ── 6. Per-user state, profiles, outputs ────────────────────────────
echo "[6/6] Migrating per-user data (state, profiles, outputs) for existing users..."
USERS=$(ls "$BACKUP_DIR/hermes/state/" 2>/dev/null | grep -v "engineer-a" || true)
for username in $USERS; do
  echo "  Processing user: $username"
  pod_name="hermes-${username}"

  # Create PVCs for this user
  for pvc_suffix in "profiles:1Gi" "state:5Gi" "outputs:10Gi"; do
    suffix="${pvc_suffix%%:*}"
    size="${pvc_suffix##*:}"
    pvc_name="${pod_name}-${suffix}"
    kubectl get pvc "$pvc_name" -n "$NS" &>/dev/null 2>&1 || \
    kubectl apply -n "$NS" -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ${pvc_name}
  namespace: ${NS}
spec:
  accessModes: ["ReadWriteOnce"]
  storageClassName: managed-premium
  resources:
    requests:
      storage: ${size}
EOF
  done

  # Wait for PVCs to be Bound (up to 30s)
  for pvc_suffix in profiles state outputs; do
    pvc="${pod_name}-${pvc_suffix}"
    local_deadline=$((SECONDS + 30))
    while [[ $SECONDS -lt $local_deadline ]]; do
      status=$(kubectl get pvc "$pvc" -n "$NS" -o jsonpath='{.status.phase}' 2>/dev/null || echo "")
      [[ "$status" == "Bound" ]] && break
      sleep 2
    done
  done

  # Profiles
  if [[ -d "$BACKUP_DIR/hermes/profiles/$username" ]]; then
    loader_pod "loader-${username}-profiles" "${pod_name}-profiles" "/profiles"
    kubectl cp "$BACKUP_DIR/hermes/profiles/$username/." "$NS/loader-${username}-profiles:/profiles/"
    cleanup_pod "loader-${username}-profiles"
  fi

  # State (includes skills)
  if [[ -d "$BACKUP_DIR/hermes/state/$username" ]]; then
    loader_pod "loader-${username}-state" "${pod_name}-state" "/state"
    kubectl cp "$BACKUP_DIR/hermes/state/$username/." "$NS/loader-${username}-state:/state/"
    kubectl exec -n "$NS" "loader-${username}-state" -- chown -R 10000:10000 /state/ 2>/dev/null || true
    cleanup_pod "loader-${username}-state"
  fi

  # Outputs
  if [[ -d "$BACKUP_DIR/outputs/$username" ]]; then
    loader_pod "loader-${username}-outputs" "${pod_name}-outputs" "/outputs"
    kubectl cp "$BACKUP_DIR/outputs/$username/." "$NS/loader-${username}-outputs:/outputs/"
    cleanup_pod "loader-${username}-outputs"
  fi

  echo "  User $username: data migrated."
done

echo ""
echo "=== Data migration complete ==="
echo "API keys: already in wrapper-data PVC (from step 1)"
echo "Next step: run 06-test.sh to verify the system"
