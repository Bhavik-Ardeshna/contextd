FROM python:3.13-slim

WORKDIR /app

# Install system dependencies and poetry in one optimized layer
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    g++ \
    unixodbc \
    unixodbc-dev \
    exiftool \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean \
    && pip install --no-cache-dir poetry==1.8.4

# Configure poetry for Docker environment
RUN poetry config virtualenvs.create false \
    && poetry config virtualenvs.in-project false \
    && poetry config cache-dir /opt/poetry-cache

# Copy locked dependency inputs. Docker builds must not resolve fresh dependency graphs.
COPY backend/pyproject.toml backend/poetry.lock ./
COPY backend/contextd-adk ./contextd-adk

# Install dependencies with cache mount
RUN --mount=type=cache,target=/opt/poetry-cache \
    poetry install --only=main --no-interaction --no-ansi --no-root

# P-Agent needs matplotlib for plot generation; ensure it's available (may be missing from lock)
RUN pip install --no-cache-dir "matplotlib>=3.8"

# Copy entrypoint script outside /app so dev bind mounts cannot hide it.
COPY --chmod=755 docker/backend/entrypoint.sh /usr/local/bin/contextd-backend-entrypoint.sh

# Copy application code
COPY backend/ .

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/root/.local/bin:$PATH"

ENTRYPOINT ["/bin/bash", "/usr/local/bin/contextd-backend-entrypoint.sh"]
