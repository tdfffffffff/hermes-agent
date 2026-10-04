#!/usr/bin/env bash
# Phase 2: Create private AKS cluster
set -euo pipefail

RESOURCE_GROUP="rg-hermes"
LOCATION="eastus2"
ACR_NAME="hermesaksacr"
CLUSTER_NAME="hermes-aks"
VNET_NAME="hermes-sandbox-01-vnet"
SUBNET_NAME="hermes-aks-subnet"   # dedicated /22 subnet, no conflict with VM
NODE_COUNT=2
NODE_SIZE="Standard_D4s_v3"

SUBNET_ID=$(az network vnet subnet show \
  --resource-group "$RESOURCE_GROUP" \
  --vnet-name "$VNET_NAME" \
  --name "$SUBNET_NAME" \
  --query id -o tsv)

echo "=== Phase 2: Creating private AKS cluster ==="
echo "Resource group : $RESOURCE_GROUP"
echo "Cluster name   : $CLUSTER_NAME"
echo "Node size      : $NODE_SIZE x $NODE_COUNT"
echo "VNet subnet    : $SUBNET_ID"
echo "(This takes ~10 minutes...)"
echo ""

az aks create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$CLUSTER_NAME" \
  --location "$LOCATION" \
  --node-count "$NODE_COUNT" \
  --node-vm-size "$NODE_SIZE" \
  --network-plugin azure \
  --vnet-subnet-id "$SUBNET_ID" \
  --service-cidr 10.96.0.0/16 \
  --dns-service-ip 10.96.0.10 \
  --enable-private-cluster \
  --attach-acr "$ACR_NAME" \
  --generate-ssh-keys \
  --enable-managed-identity

echo ""
echo "=== Cluster created. ==="
echo "IMPORTANT: Credentials and kubectl must be used from the VM (hermes-sandbox-01)"
echo "because the API server is private (only reachable within the VNet)."
echo ""
echo "Run on the VM:"
echo "  az aks get-credentials --resource-group $RESOURCE_GROUP --name $CLUSTER_NAME"
echo "  kubectl get nodes"
