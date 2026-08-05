#!/usr/bin/env bash
# Phase 8: End-to-end smoke test for the AKS system
# Run AFTER migration is complete.
set -euo pipefail

NS="hermes"
WRAPPER_KEY="${WRAPPER_API_KEY}"
WRAPPER_URL="http://localhost:5001"
OPENWEBUI_URL="http://localhost:3001"

echo "=== Phase 8: AKS Smoke Tests ==="
echo ""
echo "PREREQUISITE: Port-forwards must be running:"
echo "  kubectl port-forward -n hermes svc/openwebui 3001:8080 &"
echo "  kubectl port-forward -n hermes svc/hermes-wrapper 5001:5000 &"
echo ""
read -p "Press Enter when port-forwards are ready..."

PASS=0
FAIL=0

check() {
  local desc="$1"
  local result="$2"
  local expected="$3"
  if echo "$result" | grep -q "$expected"; then
    echo "  ✅ $desc"
    PASS=$((PASS+1))
  else
    echo "  ❌ $desc"
    echo "     Expected: $expected"
    echo "     Got: $result"
    FAIL=$((FAIL+1))
  fi
}

echo "[1] All pods running..."
NOT_RUNNING=$(kubectl get pods -n "$NS" --field-selector=status.phase!=Running -o name 2>/dev/null | grep -v "loader-" || true)
if [[ -z "$NOT_RUNNING" ]]; then
  echo "  ✅ All pods Running"
  PASS=$((PASS+1))
else
  echo "  ❌ Non-running pods: $NOT_RUNNING"
  FAIL=$((FAIL+1))
fi

echo "[2] Wrapper health endpoint..."
HEALTH=$(curl -sf "$WRAPPER_URL/health" 2>/dev/null || echo "ERROR")
check "GET /health" "$HEALTH" '"ok"'

echo "[3] Models endpoint..."
MODELS=$(curl -sf -H "Authorization: Bearer $WRAPPER_KEY" "$WRAPPER_URL/v1/models" 2>/dev/null || echo "ERROR")
check "GET /v1/models" "$MODELS" "hermes-agent"

echo "[4] OpenWebUI reachable..."
OWUI=$(curl -sf "$OPENWEBUI_URL/health" 2>/dev/null || echo "ERROR")
check "OpenWebUI /health" "$OWUI" "ok"

echo "[5] LiteLLM reachable via wrapper route..."
LLM=$(curl -sf -H "Authorization: Bearer $WRAPPER_KEY" \
  "http://localhost:5001/v1/models" 2>/dev/null || echo "ERROR")
check "LiteLLM proxy accessible" "$LLM" "hermes-agent"

echo "[6] Admin: list keys..."
KEYS=$(curl -sf -H "Authorization: Bearer $WRAPPER_KEY" \
  "$WRAPPER_URL/v1/keys" 2>/dev/null || echo "ERROR")
check "GET /v1/keys" "$KEYS" '"users"'

echo "[7] Chat completions (pick an existing migrated user)..."
echo ""
echo "  Available migrated users:"
kubectl get pods -n "$NS" -l app=hermes-user --no-headers -o custom-columns='USER:.metadata.labels.hermes-user' 2>/dev/null || true
echo ""
read -p "  Enter a migrated username to test chat (or skip with Enter): " TEST_USER

if [[ -n "$TEST_USER" ]]; then
  # Get user's API key
  USER_KEY=$(curl -sf \
    -H "Authorization: Bearer $WRAPPER_KEY" \
    -H "X-OpenWebUI-User-Name: $TEST_USER" \
    "$WRAPPER_URL/v1/keys/me" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('key',''))" 2>/dev/null || echo "")

  if [[ -z "$USER_KEY" ]]; then
    echo "  ⚠️  No key found for $TEST_USER — using admin key for test"
    USER_KEY="$WRAPPER_KEY"
    EXTRA_HEADER="-H 'X-OpenWebUI-User-Name: $TEST_USER'"
  fi

  CHAT=$(curl -sf -X POST \
    -H "Authorization: Bearer $USER_KEY" \
    -H "Content-Type: application/json" \
    -H "X-OpenWebUI-User-Name: $TEST_USER" \
    -d '{"model":"hermes-agent","messages":[{"role":"user","content":"reply with exactly: HERMES_AKS_OK"}]}' \
    "$WRAPPER_URL/v1/chat/completions" 2>/dev/null | head -c 500 || echo "ERROR")
  check "Chat completions stream started" "$CHAT" "data:"
fi

echo ""
echo "=== Test Summary ==="
echo "  PASS: $PASS"
echo "  FAIL: $FAIL"
echo ""
if [[ $FAIL -eq 0 ]]; then
  echo "All tests passed. AKS system is operational."
  echo ""
  echo "VM system (unchanged): http://localhost:3000 (via SSH tunnel)"
  echo "AKS system:            http://localhost:3001 (via kubectl port-forward)"
else
  echo "Some tests failed. Check pod logs:"
  echo "  kubectl logs -n hermes deployment/hermes-wrapper"
  echo "  kubectl logs -n hermes statefulset/openwebui"
fi
