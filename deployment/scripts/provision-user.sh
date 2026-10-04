#!/bin/bash
# provision-user.sh <username>
# Creates a new Hermes engineer profile and starts their container.
# Run this on the Azure VM each time a new user is onboarded.
#
# Usage:
#   ./provision-user.sh alice
#   ./provision-user.sh bob

set -e

USERNAME=$1

# ── Validate input ────────────────────────────────────────────────────
if [[ -z "$USERNAME" ]]; then
    echo "Usage: $0 <username>"
    exit 1
fi

if [[ ! "$USERNAME" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "Error: username must contain only letters, numbers, hyphens, underscores"
    exit 1
fi

CONTAINER_NAME="hermes-$USERNAME"

# Check if container already exists
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Error: container '$CONTAINER_NAME' already exists"
    exit 1
fi

# ── Read LiteLLM key from stack.env ──────────────────────────────────
STACK_ENV="/data/litellm/stack.env"
if [[ ! -f "$STACK_ENV" ]]; then
    echo "Error: $STACK_ENV not found"
    exit 1
fi

LITELLM_KEY=$(grep "^LITELLM_MASTER_KEY=" "$STACK_ENV" | cut -d= -f2-)
if [[ -z "$LITELLM_KEY" ]]; then
    echo "Error: LITELLM_MASTER_KEY not found in $STACK_ENV"
    exit 1
fi

# ── Create directories ────────────────────────────────────────────────
echo "Creating directories for $USERNAME..."
mkdir -p /data/hermes/profiles/$USERNAME
mkdir -p /data/hermes/state/$USERNAME
mkdir -p /data/logs/$USERNAME
mkdir -p /data/outputs/$USERNAME
mkdir -p /data/datasets  # shared read-only datasets dir

# Hermes runs as UID 10000 inside the container — state dir must be writable by it
chown -R 10000:10000 /data/hermes/state/$USERNAME


# ── Copy base config ──────────────────────────────────────────────────
echo "Copying base config..."
cp /data/hermes/profiles/engineer_a/config.yaml \
   /data/hermes/profiles/$USERNAME/config.yaml

echo "Writing state config..."
cp /data/hermes/state/engineer_a/config.yaml \
   /data/hermes/state/$USERNAME/config.yaml
chown 10000:10000 /data/hermes/state/$USERNAME/config.yaml




# ── Start container ───────────────────────────────────────────────────
echo "Starting container $CONTAINER_NAME..."
docker run -d \
    --name "$CONTAINER_NAME" \
    --network hermes-net \
    -i \
    -t \
    -e HERMES_DASHBOARD="true" \
    -e HERMES_DASHBOARD_HOST="0.0.0.0" \
    -e HERMES_DASHBOARD_PORT="9119" \
    -e HERMES_DASHBOARD_INSECURE="true" \
    -e OPENAI_API_KEY="$LITELLM_KEY" \
    -e OPENAI_API_BASE="http://hermes-litellm-proxy:4000" \
    -v /data/hermes/profiles/$USERNAME:/root/.hermes \
    -v /data/hermes/state/$USERNAME:/opt/data \
    -v /data/datasets:/opt/datasets:ro \
    -v /data/outputs/$USERNAME:/opt/outputs \
    --security-opt no-new-privileges:true \
    --cap-drop ALL \
    --cap-add SETGID \
    --cap-add SETUID \
    --cap-add DAC_OVERRIDE \
    --read-only \
    --tmpfs /tmp:size=512m \
    --tmpfs /run:size=64m,exec \
    --memory 4g \
    --restart unless-stopped \
    nousresearch/hermes-agent:latest

# Wait for Hermes to initialise its default skills, then overlay custom skills
echo "Waiting for Hermes to initialise..."
sleep 8
echo "Writing hermes-username..."
echo -n "$USERNAME" > /data/hermes/state/$USERNAME/hermes-username
chown 10000:10000 /data/hermes/state/$USERNAME/hermes-username
echo "Copying skills from template..."
cp -r /data/hermes/skills-template/software-development/* \
  /data/hermes/state/$USERNAME/skills/software-development/
chown -R 10000:10000 /data/hermes/state/$USERNAME/skills/software-development/

echo ""
echo "Done. User '$USERNAME' provisioned:"
echo "  Container : $CONTAINER_NAME"
echo "  Profile   : /data/hermes/profiles/$USERNAME"
echo "  Outputs   : /data/outputs/$USERNAME"
echo ""
echo "Next: create an account for '$USERNAME' in OpenWebUI."
echo "They will automatically route to $CONTAINER_NAME on login."
