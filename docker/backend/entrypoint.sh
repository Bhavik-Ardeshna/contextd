#!/bin/bash
set -e

# Wait for database to be ready
echo "Waiting for database..."
echo "POSTGRES_HOST: $POSTGRES_HOST"
echo "POSTGRES_USER: $POSTGRES_USER"
echo "POSTGRES_DB: $POSTGRES_DB"
echo "POSTGRES_PORT: ${POSTGRES_PORT:-5432}"
echo "POSTGRES_SSLMODE: ${POSTGRES_SSLMODE:-prefer}"

poetry run python -c "
from tenacity import retry, stop_after_attempt, wait_fixed
from sqlalchemy import create_engine
import os
import sys

@retry(stop=stop_after_attempt(15), wait=wait_fixed(5))
def check_db():
    try:
        user = os.getenv('POSTGRES_USER', 'contextd')
        password = os.getenv('POSTGRES_PASSWORD', 'contextd-dev-password')
        host = os.getenv('POSTGRES_HOST', 'db')
        db = os.getenv('POSTGRES_DB', 'contextd')
        port = os.getenv('POSTGRES_PORT', '5432')
        sslmode = os.getenv('POSTGRES_SSLMODE', 'prefer')

        print(f'Attempting to connect to: postgresql://{user}:***@{host}:{port}/{db}?sslmode={sslmode}')

        # Use SSL mode from environment variable
        connection_string = f'postgresql://{user}:{password}@{host}:{port}/{db}?sslmode={sslmode}'
        engine = create_engine(connection_string, connect_args={'connect_timeout': 10})
        connection = engine.connect()
        connection.close()
        print('Database connection successful!')

    except Exception as e:
        print(f'Database connection failed: {str(e)}')
        print(f'Error type: {type(e).__name__}')
        raise e

try:
    check_db()
except Exception as e:
    print(f'Final database connection error: {e}')
    sys.exit(1)
"

# Run migrations using the ContextD Alembic baseline.
echo "Running database migrations..."
cd /app && poetry run alembic upgrade head
# cd /app #dev time to not rerun alembic on conflicting branches

# Run initial data script (configures sources from env vars)
echo "Configuring sources from environment variables..."
poetry run python -m contextd.initial_data

# Start application (--reload: auto-restart on code change when using volume mount; no rebuild needed)
echo "Starting application (hot reload enabled)..."
poetry run uvicorn contextd.main:app --host 0.0.0.0 --port 8001 --reload --reload-dir /app/contextd
