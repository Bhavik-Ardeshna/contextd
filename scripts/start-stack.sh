#!/bin/bash

set -euo pipefail
if [ "${START_DEBUG:-}" = "1" ]; then
  set -x
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# ---- Optional flags/env (do not change default behavior) ---------------------
NONINTERACTIVE="${NONINTERACTIVE:-}"
SKIP_FRONTEND="${SKIP_FRONTEND:-}"  # Explicitly skip frontend
# Local dev: Docker infra only + backend/frontend/worker run locally (hot reload)
LOCAL_DEV="${LOCAL_DEV:-}"
# Set BUILD_IMAGES=1 to rebuild/pull images; default is up -d only (no pull/rebuild)
BUILD_IMAGES="${BUILD_IMAGES:-}"
# Set BUILD_NO_CACHE=1 with BUILD_IMAGES=1 to force backend rebuild with no cache (use after changing pyproject.toml or contextd-adk)
BUILD_NO_CACHE="${BUILD_NO_CACHE:-}"
# Set RESET_CONTAINERS=1 to remove existing ContextD containers and data volumes before starting.
RESET_CONTAINERS="${RESET_CONTAINERS:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --noninteractive) NONINTERACTIVE=1; shift ;;
    --skip-frontend) SKIP_FRONTEND=1; shift ;;
    --local-dev) LOCAL_DEV=1; shift ;;
    --build) BUILD_IMAGES=1; shift ;;
    *) echo "Unknown arg: $1"; exit 2 ;;
  esac
done

# ---- Helpers -----------------------------------------------------------------
have_cmd() { command -v "$1" >/dev/null 2>&1; }

# ---- .env handling -----------------------------------------------------------
# Check if .env exists, if not create it from example
if [ ! -f .env ]; then
    echo "Creating .env file from example..."
    cp .env.example .env
    echo ".env file created"
fi

# Check if ENCRYPTION_KEY exists AND has a non-empty value in .env
EXISTING_KEY=$(grep "^ENCRYPTION_KEY=" .env 2>/dev/null | head -1 | cut -d'=' -f2- | tr -d '"' | tr -d ' ')

if [ -n "$EXISTING_KEY" ]; then
    echo "Encryption key already exists in .env file, skipping generation."
    echo "Current ENCRYPTION_KEY value: ********"
else
    echo "No valid encryption key found. Generating new encryption key..."
    NEW_KEY=$(openssl rand -base64 32)
    echo "Generated ENCRYPTION_KEY: ********"

    # Remove any existing empty ENCRYPTION_KEY line
    grep -v "^ENCRYPTION_KEY=" .env > .env.tmp 2>/dev/null || true
    mv .env.tmp .env

    # Add the new encryption key at the end of the file
    echo "ENCRYPTION_KEY=\"$NEW_KEY\"" >> .env
    echo "Added new ENCRYPTION_KEY to .env file"
fi

# Check if STATE_SECRET exists AND has a non-empty value in .env
EXISTING_STATE_SECRET=$(grep "^STATE_SECRET=" .env 2>/dev/null | head -1 | cut -d'=' -f2- | tr -d '"' | tr -d ' ')

if [ -n "$EXISTING_STATE_SECRET" ]; then
    echo "STATE_SECRET already exists in .env file, skipping generation."
    echo "Current STATE_SECRET value: ********"
else
    echo "No valid STATE_SECRET found. Generating new HMAC secret..."
    # Generate a secure 32-byte URL-safe secret
    NEW_STATE_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))' 2>/dev/null || openssl rand -base64 32)
    echo "Generated STATE_SECRET: ********"

    # Remove any existing empty STATE_SECRET line
    grep -v "^STATE_SECRET=" .env > .env.tmp 2>/dev/null || true
    mv .env.tmp .env

    # Add the new STATE_SECRET at the end of the file
    echo "STATE_SECRET=\"$NEW_STATE_SECRET\"" >> .env
    echo "Added new STATE_SECRET to .env file"
fi

# Add SKIP_AZURE_STORAGE for faster local startup
if ! grep -q "^SKIP_AZURE_STORAGE=" .env; then
    echo "SKIP_AZURE_STORAGE=true" >> .env
    echo "Added SKIP_AZURE_STORAGE=true for faster startup"
fi

# ---- Local dev mode: infra in Docker + backend/frontend/worker on host ---------
if [ -n "${LOCAL_DEV}" ]; then
  echo "🔧 Local dev mode: starting Docker infra, then backend, frontend, and worker locally."
  # Compose/container detection (same as below)
  if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
  elif docker-compose --version >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
  elif podman-compose --version >/dev/null 2>&1; then
    COMPOSE_CMD="podman-compose"
  else
    echo "Neither 'docker compose', 'docker-compose', nor 'podman-compose' found."
    exit 1
  fi
  if docker info >/dev/null 2>&1; then
    CONTAINER_CMD="docker"
  elif command -v podman >/dev/null 2>&1 && podman info >/dev/null 2>&1; then
    CONTAINER_CMD="podman"
  else
    echo "Docker (or podman) daemon is not running."
    exit 1
  fi
  echo "Starting Docker infrastructure (postgres, redis, milvus, temporal, temporal-ui, neo4j)..."
  $COMPOSE_CMD -f docker/docker-compose.yml up -d postgres redis milvus-etcd milvus temporal temporal-ui neo4j
  echo "Waiting for infrastructure to be ready..."
  # Wait for Postgres (backend and worker need it) via container health
  for i in $(seq 1 60); do
    if ${CONTAINER_CMD} exec contextd-db pg_isready -U contextd 2>/dev/null; then
      echo "  Postgres is ready."
      break
    fi
    if [ "$i" -eq 60 ]; then
      echo "  Warning: Postgres did not become ready after 60 attempts. Starting backend anyway."
    fi
    sleep 2
  done
  # Brief pause for Temporal and other services to finish startup
  sleep 5
  BACKEND_PID=""
  FRONTEND_PID=""
  WORKER_PID=""
  cleanup() {
    echo ""
    echo "Stopping backend, frontend, and worker..."
    [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null || true
    [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null || true
    [ -n "$WORKER_PID" ] && kill "$WORKER_PID" 2>/dev/null || true
    exit 0
  }
  trap cleanup SIGINT SIGTERM
  echo "Starting backend..."
  (bash scripts/run-backend-local.sh) &
  BACKEND_PID=$!
  echo "Starting frontend..."
  (bash scripts/run-frontend-local.sh) &
  FRONTEND_PID=$!
  echo "Starting Temporal worker..."
  (bash scripts/run-worker-local.sh) &
  WORKER_PID=$!
  echo ""
  echo "✅ All started. Backend, frontend, and worker are running in the background."
  echo "   Backend:    http://localhost:${BACKEND_PORT:-8001}"
  echo "   Frontend:   http://localhost:${FRONTEND_DEV_PORT:-8080}"
  echo "   Temporal UI: http://localhost:8088"
  echo "   Press Ctrl+C to stop backend, frontend, and worker (Docker containers keep running)."
  echo ""
  wait
  exit 0
fi

# Ask for OpenAI API key (skip in NONINTERACTIVE)
if [ -z "${NONINTERACTIVE}" ]; then
  echo ""
  echo "OpenAI API key is required for files and natural language search functionality."
  read -p "Would you like to add your OPENAI_API_KEY now? You can also do this later by editing the .env file manually. (y/n): " ADD_OPENAI_KEY

  if [ "$ADD_OPENAI_KEY" = "y" ] || [ "$ADD_OPENAI_KEY" = "Y" ]; then
      read -p "Enter your OpenAI API key: " OPENAI_KEY

      # Remove any existing OPENAI_API_KEY line
      grep -v "^OPENAI_API_KEY=" .env > .env.tmp
      mv .env.tmp .env

      # Add the new OpenAI API key
      echo "OPENAI_API_KEY=\"$OPENAI_KEY\"" >> .env
      echo "OpenAI API key added to .env file."
  else
      echo "You can add your OPENAI_API_KEY later by editing the .env file manually."
      echo "Add the following line to your .env file:"
      echo "OPENAI_API_KEY=\"your-api-key-here\""
  fi
else
  echo "NONINTERACTIVE=1: Skipping OPENAI_API_KEY prompt."
fi

# Ask for Mistral API key (skip in NONINTERACTIVE)
if [ -z "${NONINTERACTIVE}" ]; then
  echo ""
  echo "Mistral API key is required for certain AI functionality."
  read -p "Would you like to add your MISTRAL_API_KEY now? You can also do this later by editing the .env file manually. (y/n): " ADD_MISTRAL_KEY

  if [ "$ADD_MISTRAL_KEY" = "y" ] || [ "$ADD_MISTRAL_KEY" = "Y" ]; then
      read -p "Enter your Mistral API key: " MISTRAL_KEY

      # Remove any existing MISTRAL_API_KEY line
      grep -v "^MISTRAL_API_KEY=" .env > .env.tmp
      mv .env.tmp .env

      # Add the new Mistral API key
      echo "MISTRAL_API_KEY=\"$MISTRAL_KEY\"" >> .env
      echo "Mistral API key added to .env file."
  else
      echo "You can add your MISTRAL_API_KEY later by editing the .env file manually."
      echo "Add the following line to your .env file:"
      echo "MISTRAL_API_KEY=\"your-api-key-here\""
  fi
else
  echo "NONINTERACTIVE=1: Skipping MISTRAL_API_KEY prompt."
fi

# ---- Compose tool selection ---------------------------------------------------
# Check if "docker compose" is available (Docker Compose v2)
if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD="docker compose"
# Else, fall back to "docker-compose" (Docker Compose v1)
elif docker-compose --version >/dev/null 2>&1; then
  COMPOSE_CMD="docker-compose"
elif podman-compose --version > /dev/null 2>&1; then
  COMPOSE_CMD="podman-compose"
else
  echo "Neither 'docker compose', 'docker-compose', nor 'podman-compose' found. Please install Docker Compose."
  exit 1
fi

# Add this block: Check if Docker daemon is running
if docker info > /dev/null 2>&1; then
    CONTAINER_CMD="docker"
elif have_cmd podman && podman info > /dev/null 2>&1; then
    CONTAINER_CMD="podman"
else
    echo "Error: Docker daemon is not running. Please start Docker and try again."
    exit 1
fi

echo "Using commands: ${CONTAINER_CMD} and ${COMPOSE_CMD}"

# ------------------------------------------------------------------------------
# Run each service individually (from repo root). Order respects dependencies.
# ------------------------------------------------------------------------------
# $COMPOSE_CMD -f docker/docker-compose.yml up -d postgres
# $COMPOSE_CMD -f docker/docker-compose.yml up -d redis
# $COMPOSE_CMD -f docker/docker-compose.yml up -d milvus-etcd
# $COMPOSE_CMD -f docker/docker-compose.yml up -d milvus
# $COMPOSE_CMD -f docker/docker-compose.yml up -d neo4j
# $COMPOSE_CMD -f docker/docker-compose.yml up -d temporal
# $COMPOSE_CMD -f docker/docker-compose.yml up -d temporal-ui
# $COMPOSE_CMD -f docker/docker-compose.yml up -d temporal-worker
# $COMPOSE_CMD -f docker/docker-compose.yml up -d backend
# $COMPOSE_CMD -f docker/docker-compose.yml --profile frontend-dev up -d frontend-dev   # hot reload
# (Add --build only when you add new dependencies; code changes auto-reload)
# ------------------------------------------------------------------------------
# Other useful commands (replace docker with podman if needed):
# List containers:    docker ps -a --filter "name=contextd"
# Remove all:          docker rm -f $(docker ps -a -q --filter "name=contextd")
# Remove all ContextD data volumes: docker volume ls --format '{{.Name}}' | awk '/^contextd_/ { print }' | xargs -r docker volume rm
# Logs:                docker logs contextd-backend
# Exec:                docker exec -it contextd-backend bash
# Backend health:     docker exec contextd-backend curl -f http://localhost:8001/health
# ------------------------------------------------------------------------------

# Check for existing contextd containers
EXISTING_CONTAINERS=$(${CONTAINER_CMD} ps -a --filter "name=contextd" --format "{{.Names}}" | tr '\n' ' ')

remove_contextd_data_volumes() {
  RESET_VOLUME_NAMES=$(${CONTAINER_CMD} volume ls --format "{{.Name}}" | awk '/^contextd_/ { print }' | tr '\n' ' ')
  if [ -n "$RESET_VOLUME_NAMES" ]; then
    ${CONTAINER_CMD} volume rm $RESET_VOLUME_NAMES || true
  else
    echo "No ContextD data volumes found."
  fi
}

if [ -n "${RESET_CONTAINERS}" ]; then
  if [ -n "$EXISTING_CONTAINERS" ]; then
    echo "Found existing contextd containers: $EXISTING_CONTAINERS"
    echo "RESET_CONTAINERS=1: Removing existing containers..."
    ${CONTAINER_CMD} rm -f $EXISTING_CONTAINERS || true
  else
    echo "RESET_CONTAINERS=1: No existing ContextD containers found."
  fi
  echo "Removing ContextD data volumes..."
  remove_contextd_data_volumes
elif [ -n "$EXISTING_CONTAINERS" ]; then
  echo "Found existing contextd containers: $EXISTING_CONTAINERS"
  if [ -z "${NONINTERACTIVE}" ]; then
    read -p "Would you like to remove them before starting? (y/n): " REMOVE_CONTAINERS
    if [ "$REMOVE_CONTAINERS" = "y" ] || [ "$REMOVE_CONTAINERS" = "Y" ]; then
      echo "Removing existing containers..."
      ${CONTAINER_CMD} rm -f $EXISTING_CONTAINERS || true
      echo "Removing ContextD data volumes..."
      remove_contextd_data_volumes
      echo "Containers and volumes removed."
    else
      echo "Warning: Starting with existing containers may cause conflicts."
    fi
  else
    echo "NONINTERACTIVE=1: Reusing existing containers. Set RESET_CONTAINERS=1 for a clean start."
  fi
fi

echo ""

# Show which images will be used
if [ -n "${BACKEND_IMAGE:-}" ] || [ -n "${FRONTEND_IMAGE:-}" ]; then
    echo "Using custom Docker images:"
    echo "  Backend:  ${BACKEND_IMAGE:-ghcr.io/contextd-ai/contextd-backend:latest}"
    echo "  Frontend: ${FRONTEND_IMAGE:-ghcr.io/contextd-ai/contextd-frontend:latest}"
    echo ""
fi

# Determine which optional services to start.
USE_FRONTEND=true

if [ -n "$SKIP_FRONTEND" ]; then
    echo "SKIP_FRONTEND is set - skipping frontend service"
    USE_FRONTEND=false
fi

# Build compose command with profiles.
COMPOSE_CMD_WITH_OPTS="$COMPOSE_CMD -f docker/docker-compose.yml"
if [ "$USE_FRONTEND" = true ]; then
    echo "Starting with frontend UI (hot reload - no rebuild on code change)"
    COMPOSE_CMD_WITH_OPTS="$COMPOSE_CMD_WITH_OPTS --profile frontend-dev"
else
    echo "Starting without frontend (backend-only mode)"
fi

if [ -n "$BUILD_IMAGES" ]; then
  echo "Starting Docker services (rebuilding images)..."
  if [ -n "$BUILD_NO_CACHE" ]; then
    echo "Building backend with --no-cache (use after changing pyproject.toml or contextd-adk)..."
    if ! $COMPOSE_CMD_WITH_OPTS build --no-cache backend; then
      echo "❌ Backend build failed"
      exit 1
    fi
  fi
  UP_CMD="$COMPOSE_CMD_WITH_OPTS up -d --build"
else
  echo "Starting Docker services (no pull/rebuild - use --build or BUILD_IMAGES=1 to rebuild)..."
  UP_CMD="$COMPOSE_CMD_WITH_OPTS up -d"
fi
if ! $UP_CMD; then
    echo "❌ Failed to start Docker services"
    echo "Check the error messages above and try running:"
    echo "  docker logs contextd-backend"
    echo "  docker logs contextd-frontend-dev"
    exit 1
fi

# Wait a moment for services to initialize
echo ""
echo "Waiting for services to initialize..."
sleep 15

# Check if backend is healthy (with retries)
echo "Checking backend health..."
MAX_RETRIES=30
RETRY_COUNT=0
BACKEND_HEALTHY=false

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
  if ${CONTAINER_CMD} exec contextd-backend curl -f http://localhost:8001/health >/dev/null 2>&1; then
    echo "✅ Backend is healthy!"
    BACKEND_HEALTHY=true
    break
  else
    echo "⏳ Backend is still starting... (attempt $((RETRY_COUNT + 1))/$MAX_RETRIES)"
    RETRY_COUNT=$((RETRY_COUNT + 1))
    sleep 5
  fi
done

if [ "$BACKEND_HEALTHY" = false ]; then
  echo "❌ Backend failed to start after $MAX_RETRIES attempts"
  echo "Check backend logs with: docker logs contextd-backend"
  echo "Common issues:"
  echo "  - Database connection problems"
  echo "  - Missing environment variables"
  echo "  - Platform sync errors"
fi

# Check if frontend-dev needs to be started manually (only if we started it)
if [ "$USE_FRONTEND" = true ]; then
  FRONTEND_CONTAINER="contextd-frontend-dev"
  FRONTEND_STATUS=$(${CONTAINER_CMD} inspect "$FRONTEND_CONTAINER" --format='{{.State.Status}}' 2>/dev/null || true)
  if [ "$FRONTEND_STATUS" = "created" ] || [ "$FRONTEND_STATUS" = "exited" ]; then
    echo "Starting frontend container..."
    ${CONTAINER_CMD} start "$FRONTEND_CONTAINER" || true
    sleep 5
  fi
fi

# Final status check
echo ""
echo "🚀 ContextD Status:"
echo "=================="

SERVICES_HEALTHY=true

# Check each service
if ${CONTAINER_CMD} exec contextd-backend curl -f http://localhost:8001/health >/dev/null 2>&1; then
  echo "✅ Backend API:    http://localhost:8001"
else
  echo "❌ Backend API:    Not responding (check logs with: docker logs contextd-backend)"
  SERVICES_HEALTHY=false
fi

# Only check frontend if we started it
if [ "$USE_FRONTEND" = true ]; then
  if curl -f http://localhost:8080 >/dev/null 2>&1; then
    echo "✅ Frontend UI:    http://localhost:8080 (hot reload)"
  else
    echo "❌ Frontend UI:    Not responding (check logs with: docker logs contextd-frontend-dev)"
    SERVICES_HEALTHY=false
  fi
else
  echo "⏭️  Frontend UI:    Skipped (backend-only mode)"
fi

echo ""
echo "Other services:"
echo "📊 Temporal UI:    http://localhost:8088"
echo "🗄️  PostgreSQL:    localhost:5436"
echo "🔎 Milvus:         localhost:19530"
echo "🧠 Neo4j:          bolt://localhost:7687"
echo ""
echo "To view logs: docker logs <container-name>"
echo "To stop all services: make stop"
echo ""

if [ "$SERVICES_HEALTHY" = true ]; then
  echo "🎉 All services started successfully!"
else
  echo "⚠️  Some services failed to start properly. Check the logs above for details."
  exit 1
fi
