FROM node:20-slim AS builder

WORKDIR /app

# Copy locked package files and install deterministic dependencies.
# Skip postinstall scripts to avoid @swc/core segfaults in slim builders.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund

# Copy application code
COPY frontend/ .

# Build the application in production mode
# Increase Node memory and use npx to run vite directly
RUN NODE_OPTIONS="--max-old-space-size=4096" npx vite build

# Runtime stage
FROM node:20-alpine

WORKDIR /app

# Install serve for hosting the built app
RUN npm install -g serve

# Copy built app from builder stage
COPY --from=builder /app/dist /app/dist
COPY docker/frontend/docker-entrypoint.sh /usr/local/bin/
COPY frontend/serve.json /app/serve.json

# Make entrypoint executable
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Use entrypoint script for runtime configuration
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
