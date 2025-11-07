#!/bin/bash
set -e

echo "=========================================="
echo "Persistent Storage Setup for Kind"
echo "=========================================="
echo ""

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

print_green() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_yellow() {
    echo -e "${YELLOW}→ $1${NC}"
}

print_red() {
    echo -e "${RED}✗ $1${NC}"
}

# Step 1: Create local directory
print_yellow "Creating local storage directory..."
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
STORAGE_DIR="$PROJECT_DIR/storage"

mkdir -p "$STORAGE_DIR/submissions"
chmod 777 "$STORAGE_DIR"
print_green "Directory created: $STORAGE_DIR"
echo ""

# Step 2: Check if cluster exists
if kind get clusters | grep -q "kaggle-agent"; then
    print_yellow "Cluster 'kaggle-agent' exists. Delete and recreate? [y/N]"
    read -r response
    if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
        print_yellow "Deleting existing cluster..."
        kind delete cluster --name kaggle-agent
        print_green "Cluster deleted"
    else
        print_red "Aborted. Please delete cluster manually and run again."
        exit 1
    fi
fi
echo ""

# Step 3: Create cluster with persistent storage
print_yellow "Creating Kind cluster with persistent storage mounts..."
kind create cluster --config kind-config.yaml --wait 120s
kubectl cluster-info --context kind-kaggle-agent
print_green "Cluster created"
echo ""

# Step 4: Create namespace
print_yellow "Creating kaggle-agent namespace..."
kubectl create namespace kaggle-agent
kubectl config set-context --current --namespace=kaggle-agent
print_green "Namespace created"
echo ""

# Step 5: Deploy persistent storage
print_yellow "Deploying persistent storage (hostPath)..."
kubectl apply -f kaggle-infrastructure/kind/storage-persistent.yaml
sleep 5
kubectl get pv,pvc -n kaggle-agent
print_green "Storage deployed"
echo ""

# Step 6: Deploy PostgreSQL
print_yellow "Deploying PostgreSQL..."
kubectl apply -f kaggle-infrastructure/kind/postgres.yaml
echo "Waiting for PostgreSQL to be ready..."
kubectl wait --for=condition=ready pod -l app=postgres --timeout=180s
print_green "PostgreSQL deployed"
echo ""

# Step 7: Deploy Redis
print_yellow "Deploying Redis..."
kubectl apply -f kaggle-infrastructure/kind/redis.yaml
echo "Waiting for Redis to be ready..."
kubectl wait --for=condition=ready pod -l app=redis --timeout=120s
print_green "Redis deployed"
echo ""

# Step 8: Build Docker images
print_yellow "Building Docker images..."
docker build -f docker/Dockerfile.api -t kaggle-agent/api:latest . -q
docker build -f docker/Dockerfile.controller -t kaggle-agent/controller:latest . -q
docker build -f docker/Dockerfile.agent -t kaggle-agent/agent:latest . -q
print_green "Images built"
echo ""

# Step 9: Load images into Kind
print_yellow "Loading images into Kind cluster..."
kind load docker-image \
  kaggle-agent/api:latest \
  kaggle-agent/controller:latest \
  kaggle-agent/agent:latest \
  --name kaggle-agent
print_green "Images loaded"
echo ""

# Step 10: Deploy API
print_yellow "Deploying API..."
kubectl apply -f kaggle-infrastructure/kind/api.yaml
echo "Waiting for API to be ready..."
kubectl wait --for=condition=available deployment/kaggle-api --timeout=180s
print_green "API deployed"
echo ""

# Step 11: Deploy Controller
print_yellow "Deploying Job Controller..."
kubectl apply -f kaggle-infrastructure/kind/controller.yaml
echo "Waiting for controller to be ready..."
kubectl wait --for=condition=available deployment/job-controller --timeout=120s
print_green "Controller deployed"
echo ""

# Step 12: Verify
echo ""
echo "=========================================="
echo "DEPLOYMENT COMPLETE WITH PERSISTENT STORAGE!"
echo "=========================================="
echo ""
echo "Cluster Status:"
kubectl get nodes
echo ""
echo "Pods:"
kubectl get pods -n kaggle-agent
echo ""
echo "Storage:"
kubectl get pv,pvc -n kaggle-agent
echo ""
echo "=========================================="
echo "Persistent Storage:"
echo "  Project location: $STORAGE_DIR"
echo "  Pod mount:        /shared"
echo ""
echo "Test it:"
echo '  curl -X POST "http://localhost:8080/run" \'
echo '    -H "Content-Type: application/json" \'
echo '    -d '"'"'{"kaggle_url": "https://www.kaggle.com/competitions/titanic"}'"'"' | jq'
echo ""
echo "View submissions:"
echo "  ls -la $STORAGE_DIR/submissions/"
echo "=========================================="

