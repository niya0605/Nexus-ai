"""Async Redis client.

Builds one `redis.asyncio.Redis` client from the shared `Settings`
object (never a duplicated or hardcoded connection string) — the same
pattern app/db/session.py already establishes for the SQLAlchemy
engine. Nothing here opens a connection eagerly; `redis.asyncio.Redis`
lazily connects (via its internal connection pool) on first real use.

S1D (Refresh Tokens, Token Rotation, Logout, and Session Management) is
the first milestone that needs Redis at all — see
app/modules/auth/refresh_store.py for what it's actually used for.
"""

from redis.asyncio import Redis

from app.config import settings


def build_redis_url() -> str:
    """Assemble the Redis connection string from `settings.redis`.

    Kept as its own function — matching `app.db.session.build_database_url`
    — so there is exactly one place this shape is defined. No password/
    TLS fields exist on `RedisSettings` yet (M0.2B): local Redis, per
    docker-compose.yml, requires neither.
    """
    r = settings.redis
    return f"redis://{r.HOST}:{r.PORT}/0"


REDIS_URL = build_redis_url()

redis_client: Redis = Redis.from_url(REDIS_URL, decode_responses=True)


async def get_redis() -> Redis:
    """FastAPI dependency yielding the shared Redis client.

    Unlike `app.db.dependencies.get_db` (which must hand out a fresh,
    isolated session per request for transaction correctness), the
    Redis async client manages its own internal connection pool and is
    designed to be reused as a single shared instance across concurrent
    requests — so this returns the same `redis_client` every time
    rather than constructing a new one.
    """
    return redis_client
