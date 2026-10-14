#!/bin/bash
set -euo pipefail

# Run Temporal worker locally (required for sync when not using Docker temporal-worker).
# Usage: bash scripts/run-worker-local.sh
# One-command startup: make local-dev

echo "🔨 Starting ContextD Temporal Worker (Hot Reload Mode)"
echo "Worker will process sync jobs from Temporal"
echo "Press Ctrl+C to stop"
echo ""

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR/backend"

# Load all environment variables from root .env file (same as backend)
if [ -f "$ROOT_DIR/.env" ]; then
    echo "🔐 Loading encryption keys from root .env file..."
    # Export all variables from .env
    set -a
    source "$ROOT_DIR/.env"
    set +a
    echo "✅ Loaded ENCRYPTION_KEY and STATE_SECRET from .env"
else
    echo "❌ Root .env file not found at $ROOT_DIR/.env"
    echo "   Please run: make start or cp .env.example .env"
    exit 1
fi
# Override only what's needed when connecting from host to Dockerized services.
export POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
export POSTGRES_PORT="${POSTGRES_PORT:-5436}"
export POSTGRES_DB="${POSTGRES_DB:-contextd}"
export POSTGRES_USER="${POSTGRES_USER:-contextd}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-contextd-dev-password}"
export REDIS_HOST="${REDIS_HOST:-localhost}"
export REDIS_PORT="${REDIS_PORT:-6379}"
export VECTOR_STORE_PROVIDER="${VECTOR_STORE_PROVIDER:-milvus}"
export MILVUS_HOST="${MILVUS_HOST:-localhost}"
export MILVUS_PORT="${MILVUS_PORT:-19530}"
export MILVUS_COLLECTION="${MILVUS_COLLECTION:-contextd_adk_memories}"
export SEARCH_INDEX_BACKEND="${SEARCH_INDEX_BACKEND:-neo4j-fulltext}"
export USE_ENTITY_INDEXING="${USE_ENTITY_INDEXING:-true}"
export INDEX_FULLTEXT_ENABLED="${INDEX_FULLTEXT_ENABLED:-true}"
export SESSION_REDIS_HOST="${SESSION_REDIS_HOST:-localhost}"
export SESSION_REDIS_PORT="${SESSION_REDIS_PORT:-6379}"
export LANGFUSE_ENABLED="${LANGFUSE_ENABLED:-false}"
export TEMPORAL_HOST="${TEMPORAL_HOST:-localhost}"
export TEMPORAL_PORT="${TEMPORAL_PORT:-7233}"
export TEMPORAL_NAMESPACE="${TEMPORAL_NAMESPACE:-default}"
export TEMPORAL_TASK_QUEUE="${TEMPORAL_TASK_QUEUE:-contextd-sync-queue}"
export TEMPORAL_ENABLED="${TEMPORAL_ENABLED:-true}"
export ENVIRONMENT="${ENVIRONMENT:-local}"
export LOCAL_DEVELOPMENT=true
export AUTH_ENABLED="${AUTH_ENABLED:-false}"
export SKIP_AZURE_STORAGE="${SKIP_AZURE_STORAGE:-true}"
echo "🚀 Starting Temporal worker..."
echo ""

# Run the Temporal worker
poetry run python -m contextd.platform.temporal.worker
