"""Database session configuration."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from contextd.core.config import settings

# Connection Pool Sizing Strategy:
# - With proper connection management, workers only hold DB connections for milliseconds
# - Database operations: entity lookup (~0.1s), insert/update (~0.1s)
# - Even with 100 concurrent workers, only a few need connections at the same time
# - Pool size 15 + overflow 15 = 30 total connections available
# - This efficiently handles bursts while preventing connection exhaustion
# - Multiple sync jobs can run simultaneously without issues

# Determine pool size based on worker count (higher cap when SYNC_DB_POOL_SIZE set for high-memory)
# With graph events + entity persistence + indexing, each worker may need up to 3 concurrent
# connections. Pool size must account for this multiplier to prevent pool exhaustion.
worker_count = getattr(settings, "SYNC_MAX_WORKERS", 100)
_explicit_pool = getattr(settings, "SYNC_DB_POOL_SIZE", None)
if _explicit_pool is not None:
    POOL_SIZE = max(5, min(_explicit_pool, 80))
    MAX_OVERFLOW = POOL_SIZE
else:
    # Scale with workers: each worker may need multiple concurrent connections
    # (entity storage + graph events + indexing). Use 2x worker count, cap at 40.
    POOL_SIZE = min(40, max(10, worker_count * 2))
    MAX_OVERFLOW = POOL_SIZE

# Connection Pool Timeout Behavior:
# - pool_timeout=30: Wait up to 30 seconds for a connection to become available
# - If all connections are busy for 30+ seconds, raises TimeoutError
# - This prevents unbounded queueing and alerts to connection leaks
#
# Alternative configurations:
# - pool_timeout=0: Don't wait at all, fail immediately if no connections
# - pool_timeout=None: Wait forever (NOT RECOMMENDED - can cause deadlocks)

# Build connect_args based on environment
connect_args_config = {
    "timeout": 60,  # Connection timeout (seconds) when establishing new connection
    "server_settings": {
        # Kill idle transactions after 5 minutes
        "idle_in_transaction_session_timeout": "300000",
    },
    "command_timeout": 60,
}

# Disable SSL for PgBouncer connections (internal cluster traffic)
if settings.POSTGRES_SSLMODE == "disable":
    connect_args_config["ssl"] = False

async_engine = create_async_engine(
    str(settings.SQLALCHEMY_ASYNC_DATABASE_URI),
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_recycle=300,  # Recycle connections after 5 minutes
    pool_timeout=30,  # Wait up to 30 seconds for a connection
    isolation_level="READ COMMITTED",
    # Note: async engines automatically use AsyncAdaptedQueuePool
    # Settings to prevent connection buildup:
    connect_args=connect_args_config,
)

AsyncSessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=async_engine)


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session that can be used as a context manager.

    Yields:
        AsyncSession: An async database session

    Example:
    -------
        async with get_db_context() as db:
            await db.execute(...)

    Notes:
        Do not call ``session.close()`` manually around ``yield``. Closing inside a ``finally``
        while still inside ``async with AsyncSessionLocal()`` causes ``__aexit__`` to run on an
        already-closed session and can leave pooled connections in a state that surfaces as
        ``PendingRollbackError`` on the next checkout.
    """
    async with AsyncSessionLocal() as db:
        yield db


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session to be used in dependency injection.

    Yields:
    ------
        AsyncSession: An async database session

    """
    async with AsyncSessionLocal() as db:
        yield db
