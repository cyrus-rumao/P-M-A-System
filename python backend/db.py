from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from redis.asyncio import Redis

from config import get_settings

settings = get_settings()
mongo_client: AsyncIOMotorClient | None = None
database: AsyncIOMotorDatabase | None = None
redis_client: Redis | None = None


@asynccontextmanager
async def lifespan(app: Any):
    global mongo_client, database, redis_client
    if not settings.mongo_uri:
        raise RuntimeError("MONGO_URI is required")
    mongo_client = AsyncIOMotorClient(settings.mongo_uri)
    await mongo_client.admin.command("ping")
    database = mongo_client.get_default_database()
    if settings.redis_url:
        redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
        await redis_client.ping()
    try:
        yield
    finally:
        if redis_client:
            await redis_client.aclose()
        if mongo_client:
            mongo_client.close()


def db() -> AsyncIOMotorDatabase:
    if database is None:
        raise RuntimeError("MongoDB has not been initialized")
    return database


def now() -> datetime:
    return datetime.now(timezone.utc)
