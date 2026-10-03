"""Redis-backed storage for email-verification and password-reset
tokens.

**DESIGN GAP, explicitly flagged, not a frozen mechanism:** no frozen
Database Design exists (docs/database/README.md marks `DATABASE_DESIGN.md`
"not yet added") specifying how these tokens should be persisted. Rather
than inventing a new SQL table, this reuses the architecture S1D already
established for refresh tokens (`app.modules.auth.refresh_store`) — an
opaque random token, hashed before ever touching storage, Redis-backed
— since that's "the smallest implementation-compatible mechanism"
already present in this codebase, per S1E's own instruction for exactly
this situation.

**One real difference from `refresh_store`, and why:** a refresh token's
expiry could be authoritatively checked against the *Postgres* `Session`
row's own `expires_at` column, so Redis's own TTL only needed to be an
approximate cleanup mechanism. Verification/reset tokens have no
equivalent Postgres row — Redis is the *only* place either lives, so if
expiry were left to Redis's TTL alone, an expired key and a never-issued
key would be indistinguishable (both just "not found"), and the frozen
contract requires distinguishing `token_expired` from `token_invalid`.
So the real expiry decision is made here in application code, against an
`expires_at` stored *inside* the Redis hash; Redis's own TTL is set with
a grace period past that and exists only so an abandoned token doesn't
linger forever, not as the authoritative expiry check.

Single-use: a token is deleted the moment it's looked up here,
regardless of whether it turns out to be expired — "consumed" and
"successfully used" are different questions, and only this module
answers the first one.

Reuses `app.core.security`'s existing opaque-token primitives
(`create_refresh_token`/`hash_refresh_token`) rather than duplicating
that cryptography under new names — they're already fully generic
"random opaque token" / "hash a token" functions that happen to be
named after their first consumer (S1C.1's refresh tokens); imported
here under names that read correctly for this module's own purpose.
"""

import uuid
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis

from app.core.security import create_refresh_token as _generate_token
from app.core.security import hash_refresh_token as _hash_token
from app.modules.auth.exceptions import TokenExpiredError, TokenInvalidError

# A Redis TTL past the real (application-checked) expiry — purely so an
# abandoned token's storage doesn't linger indefinitely; never the
# authoritative expiry decision (see module docstring).
_CLEANUP_GRACE_SECONDS = 3600

_VERIFICATION_TOKEN_PREFIX = "email_verification_token:"
_VERIFICATION_BY_USER_PREFIX = "email_verification_by_user:"
_RESET_TOKEN_PREFIX = "password_reset_token:"
_RESET_BY_USER_PREFIX = "password_reset_by_user:"


async def _issue_token(
    redis: Redis, *, token_prefix: str, by_user_prefix: str, user_id: uuid.UUID, ttl_seconds: int
) -> str:
    """Issue a new token for `user_id`, first invalidating whatever
    previous token (of this same kind) that user held — "the previous
    token must not remain accidentally usable" applies to both
    verification and reset tokens alike, so this one helper serves both.
    """
    raw_token = _generate_token()
    token_hash = _hash_token(raw_token)
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    redis_ttl = ttl_seconds + _CLEANUP_GRACE_SECONDS

    previous_hash = await redis.get(f"{by_user_prefix}{user_id}")

    async with redis.pipeline(transaction=True) as pipe:
        if previous_hash:
            pipe.delete(f"{token_prefix}{previous_hash}")
        pipe.hset(
            f"{token_prefix}{token_hash}",
            mapping={"user_id": str(user_id), "expires_at": expires_at.isoformat()},
        )
        pipe.expire(f"{token_prefix}{token_hash}", redis_ttl)
        pipe.set(f"{by_user_prefix}{user_id}", token_hash, ex=redis_ttl)
        await pipe.execute()

    return raw_token


async def _consume_token(
    redis: Redis, *, token_prefix: str, by_user_prefix: str, raw_token: str
) -> uuid.UUID:
    """Look up, delete (single-use), and validate a token.

    Raises `TokenInvalidError` if the token was never issued, was
    already consumed, or was replaced by a newer one (see `_issue_token`).
    Raises `TokenExpiredError` if it was found but its stored
    `expires_at` has passed. Either way the token is gone afterward —
    never revalidates.
    """
    token_hash = _hash_token(raw_token)
    data = await redis.hgetall(f"{token_prefix}{token_hash}")

    if not data:
        raise TokenInvalidError()

    user_id = uuid.UUID(data["user_id"])
    expires_at = datetime.fromisoformat(data["expires_at"])

    async with redis.pipeline(transaction=True) as pipe:
        pipe.delete(f"{token_prefix}{token_hash}")
        pipe.delete(f"{by_user_prefix}{user_id}")
        await pipe.execute()

    if datetime.now(UTC) >= expires_at:
        raise TokenExpiredError()

    return user_id


async def issue_verification_token(redis: Redis, user_id: uuid.UUID, ttl_seconds: int) -> str:
    return await _issue_token(
        redis,
        token_prefix=_VERIFICATION_TOKEN_PREFIX,
        by_user_prefix=_VERIFICATION_BY_USER_PREFIX,
        user_id=user_id,
        ttl_seconds=ttl_seconds,
    )


async def consume_verification_token(redis: Redis, raw_token: str) -> uuid.UUID:
    return await _consume_token(
        redis,
        token_prefix=_VERIFICATION_TOKEN_PREFIX,
        by_user_prefix=_VERIFICATION_BY_USER_PREFIX,
        raw_token=raw_token,
    )


async def issue_reset_token(redis: Redis, user_id: uuid.UUID, ttl_seconds: int) -> str:
    return await _issue_token(
        redis,
        token_prefix=_RESET_TOKEN_PREFIX,
        by_user_prefix=_RESET_BY_USER_PREFIX,
        user_id=user_id,
        ttl_seconds=ttl_seconds,
    )


async def consume_reset_token(redis: Redis, raw_token: str) -> uuid.UUID:
    return await _consume_token(
        redis,
        token_prefix=_RESET_TOKEN_PREFIX,
        by_user_prefix=_RESET_BY_USER_PREFIX,
        raw_token=raw_token,
    )
