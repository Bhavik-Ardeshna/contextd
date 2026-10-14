#!/bin/bash
set -e

# Wait for database to be ready
echo "Waiting for database..."
poetry run python -c "
from tenacity import retry, stop_after_attempt, wait_fixed
from sqlalchemy import create_engine
import os

@retry(stop=stop_after_attempt(5), wait=wait_fixed(2))
def check_db():
    user = os.getenv('POSTGRES_USER', 'contextd')
    password = os.getenv('POSTGRES_PASSWORD', 'contextd-dev-password')
    host = os.getenv('POSTGRES_HOST', 'db')
    db = os.getenv('POSTGRES_DB', 'contextd')
    port = os.getenv('POSTGRES_PORT', '5432')
    engine = create_engine(f'postgresql://{user}:{password}@{host}:{port}/{db}')
    engine.connect()

check_db()
"

# Run migrations using the ContextD Alembic baseline.
echo "Running database migrations..."
cd /app && poetry run alembic upgrade head
# cd /app #dev time to not rerun alembic on conflicting branches

# Run initial data script so dev/test containers match the main startup path.
echo "Configuring sources from environment variables..."
poetry run python -m contextd.initial_data

# Start application with hot reloading enabled
echo "Starting application with hot reloading..."
poetry run uvicorn contextd.main:app --host 0.0.0.0 --port 8001 --reload --reload-dir /app/contextd
