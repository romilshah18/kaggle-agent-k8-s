#!/bin/bash
set -e

echo "=========================================="
echo "Kaggle Agent K8s - Complete Setup (Kind)"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Function to print colored output
print_green() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_yellow() {
    echo -e "${YELLOW}→ $1${NC}"
}

print_red() {
    echo -e "${RED}✗ $1${NC}"
}

# Check prerequisites
print_yellow "Checking prerequisites..."

if ! command -v docker &> /dev/null; then
    print_red "Docker not found. Please install Docker Desktop"
    exit 1
fi

if ! command -v kind &> /dev/null; then
    print_red "Kind not found. Installing..."
    brew install kind
fi

if ! command -v kubectl &> /dev/null; then
    print_red "kubectl not found. Installing..."
    brew install kubectl
fi

print_green "All prerequisites installed"
echo ""

# Create Kind cluster
print_yellow "Creating Kind cluster..."

if kind get clusters | grep -q "kaggle-agent"; then
    print_yellow "Cluster already exists, deleting..."
    kind delete cluster --name kaggle-agent
fi

kind create cluster --config kind-config.yaml --wait 120s
kubectl cluster-info --context kind-kaggle-agent

print_green "Kind cluster created"
echo ""

# Install metrics server
print_yellow "Installing metrics server..."
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# Patch for Kind
kubectl patch deployment metrics-server -n kube-system --type='json' -p='[
  {
    "op": "add",
    "path": "/spec/template/spec/containers/0/args/-",
    "value": "--kubelet-insecure-tls"
  }
]'

print_green "Metrics server installed"
echo ""

# Create namespace
print_yellow "Creating kaggle-agent namespace..."
kubectl create namespace kaggle-agent
kubectl config set-context --current --namespace=kaggle-agent

print_green "Namespace created"
echo ""

# Deploy storage
print_yellow "Deploying storage..."
kubectl apply -f kaggle-infrastructure/kind/storage.yaml

print_green "Storage configured"
echo ""

# Deploy PostgreSQL
print_yellow "Deploying PostgreSQL..."
kubectl apply -f kaggle-infrastructure/kind/postgres.yaml

# Wait for postgres
echo "Waiting for PostgreSQL to be ready..."
kubectl wait --for=condition=ready pod -l app=postgres --timeout=180s

print_green "PostgreSQL deployed"
echo ""

# Deploy Redis
print_yellow "Deploying Redis..."
kubectl apply -f kaggle-infrastructure/kind/redis.yaml

# Wait for redis
echo "Waiting for Redis to be ready..."
kubectl wait --for=condition=ready pod -l app=redis --timeout=120s

print_green "Redis deployed"
echo ""

# Build Docker images
print_yellow "Building Docker images..."
echo "This may take a few minutes..."

docker build -f docker/Dockerfile.api -t kaggle-agent/api:latest . || {
    print_red "Failed to build API image"
    exit 1
}

docker build -f docker/Dockerfile.controller -t kaggle-agent/controller:latest . || {
    print_red "Failed to build controller image"
    exit 1
}

docker build -f docker/Dockerfile.agent -t kaggle-agent/agent:latest . || {
    print_red "Failed to build agent image"
    exit 1
}

print_green "Docker images built"
echo ""

# Load images into Kind
print_yellow "Loading images into Kind cluster..."

kind load docker-image kaggle-agent/api:latest --name kaggle-agent
kind load docker-image kaggle-agent/controller:latest --name kaggle-agent
kind load docker-image kaggle-agent/agent:latest --name kaggle-agent

print_green "Images loaded into Kind"
echo ""

# Initialize database
print_yellow "Initializing database..."

kubectl run db-init \
  --image=kaggle-agent/api:latest \
  --restart=Never \
  --rm -i \
  --env="DATABASE_URL=postgresql://kaggle_user:password@postgres:5432/kaggle_agent" \
  -- python -c "from api.models.database import init_db; init_db(); print('Database initialized')" \
  || print_yellow "Database may already be initialized"

print_green "Database initialized"
echo ""

# Deploy API
print_yellow "Deploying API..."
kubectl apply -f kaggle-infrastructure/kind/api.yaml

# Wait for API
echo "Waiting for API to be ready..."
kubectl wait --for=condition=available deployment/kaggle-api --timeout=180s

print_green "API deployed"
echo ""

# Deploy Controller
print_yellow "Deploying Job Controller..."
kubectl apply -f kaggle-infrastructure/kind/controller.yaml

# Wait for controller
echo "Waiting for controller to be ready..."
kubectl wait --for=condition=available deployment/job-controller --timeout=120s

print_green "Controller deployed"
echo ""

# Get status
echo ""
echo "=========================================="
echo "DEPLOYMENT COMPLETE!"
echo "=========================================="
echo ""
echo "Cluster Status:"
kubectl get nodes
echo ""
echo "Pods:"
kubectl get pods
echo ""
echo "Services:"
kubectl get services
echo ""
echo "=========================================="
echo "Access the API:"
echo "  http://localhost:8080/health"
echo "  http://localhost:8080/docs"
echo ""
echo "Or use port-forward:"
echo "  kubectl port-forward svc/kaggle-api 8000:80"
echo ""
echo "Test with:"
echo '  curl http://localhost:8080/health | jq'
echo ""
echo "View logs:"
echo "  kubectl logs -f deployment/kaggle-api"
echo "  kubectl logs -f deployment/job-controller"
echo "=========================================="

