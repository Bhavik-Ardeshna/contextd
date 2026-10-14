#!/bin/bash
set -euo pipefail

# Run frontend locally with hot module replacement.
# Usage: bash scripts/run-frontend-local.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR/frontend"

# Ensure npm is available: load shell profile, then try nvm/fnm/volta
if ! command -v npm &>/dev/null; then
  for f in "$HOME/.nvm/nvm.sh" "$HOME/.bashrc" "$HOME/.profile"; do
    [ -s "$f" ] && { . "$f" 2>/dev/null; command -v npm &>/dev/null && break; }
  done
fi
if ! command -v npm &>/dev/null; then
  if [ -s "$HOME/.nvm/nvm.sh" ]; then
    echo "Loading nvm..."
    . "$HOME/.nvm/nvm.sh"
  elif command -v fnm &>/dev/null; then
    echo "Loading fnm..."
    eval "$(fnm env)"
  elif [ -x "$HOME/.volta/bin/volta" ]; then
    echo "Loading volta..."
    export PATH="$HOME/.volta/bin:$PATH"
  fi
fi
if ! command -v npm &>/dev/null; then
  echo "❌ npm not found."
  echo ""
  echo "Install Node.js (includes npm), then run this script again. Options:"
  echo "  • nvm (recommended):  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash"
  echo "                        Then: source ~/.bashrc && nvm install --lts"
  echo "  • system (Ubuntu):    sudo apt update && sudo apt install -y nodejs npm"
  echo "  • nodejs.org:         https://nodejs.org"
  exit 1
fi

echo "🚀 Starting ContextD Frontend (Hot Reload Mode)"
echo "Press Ctrl+C to stop"
echo ""

# Load API URL and frontend port from root .env (trimmed) for local/network dev
if [ -f "$ROOT_DIR/.env" ]; then
  while IFS= read -r line; do
    case "$line" in
      VITE_API_URL=*) export VITE_API_URL="${line#*=}";;
      BACKEND_PORT=*) BACKEND_PORT="${line#*=}";;
      FRONTEND_DEV_PORT=*) export FRONTEND_DEV_PORT="${line#*=}";;
    esac
  done < <(grep -E "^(VITE_API_URL|BACKEND_PORT|FRONTEND_DEV_PORT)=" "$ROOT_DIR/.env" 2>/dev/null || true)
fi
# Trim whitespace/carriage return
BACKEND_PORT=$(echo "${BACKEND_PORT:-}" | tr -d '\r' | xargs)
VITE_API_URL=$(echo "${VITE_API_URL:-}" | tr -d '\r' | xargs)
FRONTEND_DEV_PORT=$(echo "${FRONTEND_DEV_PORT:-}" | tr -d '\r' | xargs)
# Default API URL: explicit VITE_API_URL, or http://localhost:${BACKEND_PORT}, or 8001
if [ -z "$VITE_API_URL" ]; then
  if [ -n "$BACKEND_PORT" ]; then
    VITE_API_URL="http://localhost:${BACKEND_PORT}"
  else
    VITE_API_URL="http://localhost:8001"
  fi
fi
export VITE_API_URL
export VITE_ENABLE_AUTH="${VITE_ENABLE_AUTH:-false}"

# Install dependencies if needed (e.g. first run or after clone)
if [ ! -d "node_modules" ] || [ ! -f "node_modules/.bin/vite" ]; then
  echo "📦 Installing dependencies (npm ci)..."
  npm ci --no-audit --no-fund
  echo ""
fi

# Frontend dev server port (default 8080); use FRONTEND_DEV_PORT=8082 for network access
DEV_PORT="${FRONTEND_DEV_PORT:-8080}"
echo "Frontend will be available at: http://localhost:${DEV_PORT}"
echo "API URL: ${VITE_API_URL}"
echo ""

# Run Vite dev server (host 0.0.0.0 so reachable at http://<your-ip>:port)
npm run dev -- --host --port "${DEV_PORT}"
