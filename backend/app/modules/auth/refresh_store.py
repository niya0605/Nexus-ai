"""Redis-backed refresh-token storage — the fast, TTL-based, server-side
validation layer the frozen Technical Design Document specifies,
alongside (not instead of) the relational `Session` row (see
app/modules/auth/models.py). Isolates every Redis command behind this
module so no route, and no other part of the service layer, ever issues
one directly.

Key scheme: `refresh_token:{sha256_hex_hash}` → the owning Session's
`id` (str), with a TTL matching `refresh_token_expires_at()`. The key
IS the refresh token's hash (app.core.security.hash_refresh_token) —
this module never receives or stores a raw token.

A Redis record's existence is the fast "is this specific refresh token
currently valid" answer. app/modules/auth/service.py additionally
cross-checks the relational Session row (status, expires_at) — Redis
alone can't distinguish "expired" from "explicitly invalidated" once a
key is gone, but the frozen contract's `token_expired` vs
`token_invalid` codes require exactly that distinction.
"""

from redis.asyncio import Redis

_KEY_PREFIX = "refresh_token:"


def _key(token_hash: str) -> str:
    return f"{_KEY_PREFIX}{token_hash}"


async def store(redis: Redis, token_hash: str, session_id: str, ttl_seconds: int) -> None:
    """Record a newly issued (or rotated-to) refresh token as currently valid."""
    await redis.set(_key(token_hash), session_id, ex=ttl_seconds)


async def get_session_id(redis: Redis, token_hash: str) -> str | None:
    """The owning Session's `id` if `token_hash` is currently valid, else `None`."""
    return await redis.get(_key(token_hash))


async def rotate(
    redis: Redis, *, old_hash: str, new_hash: str, session_id: str, ttl_seconds: int
) -> None:
    """Atomically invalidate `old_hash` and record `new_hash` as valid.

    One pipelined round trip, not two separate calls — the old token
    must never still read as valid at the same moment the new one does,
    and the new token must never be briefly missing while the old one
    still is.
    """
    async with redis.pipeline(transaction=True) as pipe:
        pipe.delete(_key(old_hash))
        pipe.set(_key(new_hash), session_id, ex=ttl_seconds)
        await pipe.execute()


async def invalidate(redis: Redis, token_hash: str) -> None:
    """Remove a refresh token's record — logout, explicit session
    revocation, or defensively cleaning up a record found inconsistent
    with the relational Session row."""
    await redis.delete(_key(token_hash))
