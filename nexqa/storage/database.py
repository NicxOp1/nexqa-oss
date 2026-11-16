"""
NEXQA — MongoDB Connection (async via motor)

Provides a singleton async client + database reference.
Used by runs.py for persistent run storage and any future collections.
"""

import asyncio

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import AutoReconnect, NotPrimaryError, ServerSelectionTimeoutError
from nexqa.storage.config import Config
from nexqa.storage.logger import logger

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None

# Transient errors raised while an Atlas replica set is failing over (a new
# primary is being elected). They clear on their own within seconds, so the
# right response is a short retry, not a 500. See with_mongo_retry below.
MONGO_TRANSIENT_ERRORS = (AutoReconnect, NotPrimaryError, ServerSelectionTimeoutError)


def get_db() -> AsyncIOMotorDatabase:
    """Get or create the singleton MongoDB database connection."""
    global _client, _db
    if _db is None:
        # retryWrites lets the driver retry a single write once after a network
        # blip; serverSelectionTimeoutMS caps how long we wait for a primary so
        # a failover fails fast enough for with_mongo_retry to loop instead of
        # hanging 30s (the default) on the first attempt.
        _client = AsyncIOMotorClient(
            Config.MONGODB_URI,
            retryWrites=True,
            serverSelectionTimeoutMS=8000,
            connectTimeoutMS=10000,
        )
        _db = _client[Config.MONGODB_DB_NAME]
        logger.info(f"MongoDB connected: {Config.MONGODB_DB_NAME}")
    return _db


async def with_mongo_retry(operation, *, attempts: int = 3, base_delay: float = 1.0):
    """Run an async Mongo operation, retrying transient replica-set failovers.

    `operation` is a zero-arg callable returning the awaitable to run (e.g.
    ``lambda: db[COLLECTION].insert_one(doc)``). Retries on MONGO_TRANSIENT_ERRORS
    with exponential backoff; re-raises the last error if every attempt fails so
    the caller can surface a clean 503.
    """
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except MONGO_TRANSIENT_ERRORS as exc:
            last_exc = exc
            if attempt == attempts:
                break
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                f"MongoDB transient error (attempt {attempt}/{attempts}), "
                f"retrying in {delay:.0f}s: {exc}"
            )
            await asyncio.sleep(delay)
    raise last_exc


async def close_db() -> None:
    """Close the MongoDB connection (call on shutdown)."""
    global _client, _db
    if _client:
        _client.close()
        _client = None
        _db = None
        logger.info("MongoDB connection closed")
