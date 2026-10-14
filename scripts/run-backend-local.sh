#!/bin/bash
set -euo pipefail

# Run backend locally with hot reload.
# Usage: bash scripts/run-backend-local.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR/backend"

# Load root .env first so DB credentials and secrets match Docker/compose
if [ -f "$ROOT_DIR/.env" ]; then
    echo "🔐 Loading encryption keys from root .env file..."
    set -a
    source "$ROOT_DIR/.env"
    set +a
    echo "✅ Loaded ENCRYPTION_KEY and STATE_SECRET from .env"
else
    echo "❌ Root .env file not found at $ROOT_DIR/.env"
    echo "   Please run: make start or cp .env.example .env"
    exit 1
fi

# Override only what's needed when connecting from host to Dockerized services
export POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
export POSTGRES_PORT="${POSTGRES_PORT:-5436}"
export REDIS_HOST="${REDIS_HOST:-localhost}"
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
export ENVIRONMENT="${ENVIRONMENT:-local}"
export LOCAL_DEVELOPMENT=true
export AUTH_ENABLED="${AUTH_ENABLED:-false}"
export SKIP_AZURE_STORAGE="${SKIP_AZURE_STORAGE:-true}"

BACKEND_PORT="${BACKEND_PORT:-8001}"
echo "🚀 Starting ContextD Backend (Hot Reload Mode)"
echo "Backend will be available at: http://localhost:${BACKEND_PORT}"
echo "Press Ctrl+C to stop"
echo ""

# Check that PostgreSQL is reachable before running migrations
if command -v pg_isready >/dev/null 2>&1; then
  if ! pg_isready -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -q 2>/dev/null; then
    echo "❌ PostgreSQL is not reachable at ${POSTGRES_HOST}:${POSTGRES_PORT}"
    echo "   Start the database with:"
    echo "   make infra"
    exit 1
  fi
fi

# Run database migrations so the schema exists before initial_data
echo "📦 Running database migrations..."
poetry run alembic upgrade head
echo ""

# Run initial data configuration (for source tokens etc.)
echo "⚙️  Configuring sources from environment variables..."
poetry run python -m contextd.initial_data
echo ""

# Run with uvicorn hot reload (if port in use, set BACKEND_PORT=8002 in .env)
poetry run uvicorn contextd.main:app --host 0.0.0.0 --port "${BACKEND_PORT}" --reload
