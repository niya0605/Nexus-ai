"""Service-level tests for `refresh_session`.

Runs against a real, transactionally-isolated PostgreSQL session
(backend/tests/db.py) *and* a real Redis (app.db.redis.redis_client) —
per S1D's own instruction to use real integration tests, not mocks, for
this. Every test that logs in cleans up its own Redis key at the end
(there is no automatic Redis rollback the way Postgres gets one).
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.db import run_db_test

from app.config import settings
from app.core.security import decode_access_token, hash_refresh_token
from app.db.redis import redis_client
from app.modules.auth import refresh_store
from app.modules.auth.exceptions import TokenExpiredError, TokenInvalidError
from app.modules.auth.models import Session, SessionStatus, User, UserStatus
from app.modules.auth.schemas import LoginRequest, RegisterRequest
from app.modules.auth.service import login_user, refresh_session, register_user

_TEST_PASSWORD = "a-strong-password"
_TEST_IP = "203.0.113.10"  # RFC 5737 TEST-NET-3 — documentation-only.


def _register_request(**overrides: object) -> RegisterRequest:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4().hex[:8]}@example.com",
        "password": _TEST_PASSWORD,
        "display_name": "Test User",
    }
    defaults.update(overrides)
    return RegisterRequest(**defaults)  # type: ignore[arg-type]


async def _login_active_user(session: AsyncSession) -> tuple[User, str]:
    """Register, activate, and log in — returns the user and the raw
    refresh token `refresh_session` will be exercised against."""
    user = await register_user(session, _register_request())
    user.status = UserStatus.ACTIVE
    user.email_verified_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(user)

    result = await login_user(
        session, redis_client, LoginRequest(email=user.email, password=_TEST_PASSWORD), _TEST_IP
    )  # type: ignore[arg-type]
    return user, result.refresh_token


async def _current_session_for(session: AsyncSession, user_id: uuid.UUID) -> Session:
    return (await session.execute(select(Session).where(Session.user_id == user_id))).scalar_one()


def test_valid_refresh_succeeds() -> None:
    async def body(session: AsyncSession) -> None:
        user, raw_refresh_token = await _login_active_user(session)
        try:
            result = await refresh_session(session, redis_client, raw_refresh_token)
            assert result.access_token
            assert result.refresh_token
        finally:
            db_session = await _current_session_for(session, user.id)
            await refresh_store.invalidate(redis_client, db_session.refresh_token_hash)

    run_db_test(body)


def test_refresh_issues_a_new_valid_access_token() -> None:
    async def body(session: AsyncSession) -> None:
        user, raw_refresh_token = await _login_active_user(session)
        try:
            result = await refresh_session(session, redis_client, raw_refresh_token)
            claims = decode_access_token(result.access_token)
            assert claims["sub"] == str(user.id)
        finally:
            db_session = await _current_session_for(session, user.id)
            await refresh_store.invalidate(redis_client, db_session.refresh_token_hash)

    run_db_test(body)


def test_refresh_issues_a_new_refresh_token() -> None:
    async def body(session: AsyncSession) -> None:
        user, raw_refresh_token = await _login_active_user(session)
        try:
            result = await refresh_session(session, redis_client, raw_refresh_token)
            assert result.refresh_token != raw_refresh_token
            assert len(result.refresh_token) >= 40
        finally:
            db_session = await _current_session_for(session, user.id)
            await refresh_store.invalidate(redis_client, db_session.refresh_token_hash)

    run_db_test(body)


def test_old_refresh_token_is_invalidated_after_rotation() -> None:
    async def body(session: AsyncSession) -> None:
        user, raw_refresh_token = await _login_active_user(session)
        result = await refresh_session(session, redis_client, raw_refresh_token)
        try:
            # The very token that just succeeded must never work again.
            with pytest.raises(TokenInvalidError):
                await refresh_session(session, redis_client, raw_refresh_token)
        finally:
            db_session = await _current_session_for(session, user.id)
            await refresh_store.invalidate(redis_client, db_session.refresh_token_hash)
            await refresh_store.invalidate(redis_client, hash_refresh_token(result.refresh_token))

    run_db_test(body)


def test_new_refresh_token_is_stored_and_usable() -> None:
    async def body(session: AsyncSession) -> None:
        user, raw_refresh_token = await _login_active_user(session)
        first = await refresh_session(session, redis_client, raw_refresh_token)
        try:
            # The *new* token from the first rotation must itself work.
            second = await refresh_session(session, redis_client, first.refresh_token)
            assert second.access_token
        finally:
            db_session = await _current_session_for(session, user.id)
            await refresh_store.invalidate(redis_client, db_session.refresh_token_hash)

    run_db_test(body)


def test_refresh_keeps_session_active_and_updates_hash() -> None:
    async def body(session: AsyncSession) -> None:
        user, raw_refresh_token = await _login_active_user(session)
        before = await _current_session_for(session, user.id)
        # Snapshot as plain values *before* mutating — `before` and any
        # later `_current_session_for(session, user.id)` call return the
        # exact same Python object (SQLAlchemy's identity map, same
        # session/PK), so comparing `before.refresh_token_hash` after
        # the fact would just compare the mutated object to itself.
        before_id, before_hash = before.id, before.refresh_token_hash
        try:
            result = await refresh_session(session, redis_client, raw_refresh_token)

            after = await _current_session_for(session, user.id)
            assert after.id == before_id  # same Session row, not a new one
            assert after.status == SessionStatus.ACTIVE
            assert after.refresh_token_hash == hash_refresh_token(result.refresh_token)
            assert after.refresh_token_hash != before_hash
        finally:
            db_session = await _current_session_for(session, user.id)
            await refresh_store.invalidate(redis_client, db_session.refresh_token_hash)

    run_db_test(body)


def test_refresh_extends_session_expiry() -> None:
    async def body(session: AsyncSession) -> None:
        user, raw_refresh_token = await _login_active_user(session)
        before = await _current_session_for(session, user.id)
        before_expires_at = before.expires_at  # snapshot — see identity-map note above
        try:
            now = datetime.now(UTC)
            await refresh_session(session, redis_client, raw_refresh_token)

            after = await _current_session_for(session, user.id)
            ttl = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
            assert after.expires_at > before_expires_at
            assert now + ttl <= after.expires_at <= now + ttl + timedelta(seconds=5)
        finally:
            db_session = await _current_session_for(session, user.id)
            await refresh_store.invalidate(redis_client, db_session.refresh_token_hash)

    run_db_test(body)


def test_expired_refresh_token_is_rejected() -> None:
    async def body(session: AsyncSession) -> None:
        user, raw_refresh_token = await _login_active_user(session)
        db_session = await _current_session_for(session, user.id)

        # Force the Session into the past — Redis's own TTL would
        # normally have expired the key around the same time; setting
        # both keeps this deterministic rather than sleeping in a test.
        db_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

        try:
            with pytest.raises(TokenExpiredError):
                await refresh_session(session, redis_client, raw_refresh_token)
        finally:
            await refresh_store.invalidate(redis_client, db_session.refresh_token_hash)

    run_db_test(body)


def test_invalid_refresh_token_is_rejected() -> None:
    async def body(session: AsyncSession) -> None:
        with pytest.raises(TokenInvalidError):
            await refresh_session(session, redis_client, "not-a-real-refresh-token")

    run_db_test(body)


def test_refresh_of_revoked_session_is_rejected() -> None:
    async def body(session: AsyncSession) -> None:
        user, raw_refresh_token = await _login_active_user(session)
        db_session = await _current_session_for(session, user.id)
        db_session.status = SessionStatus.REVOKED
        db_session.revoked_at = datetime.now(UTC)
        await session.commit()

        try:
            with pytest.raises(TokenInvalidError):
                await refresh_session(session, redis_client, raw_refresh_token)
        finally:
            await refresh_store.invalidate(redis_client, db_session.refresh_token_hash)

    run_db_test(body)


def test_refresh_response_never_exposes_restricted_fields() -> None:
    """`RefreshResult` (the only thing `refresh_session` hands back) must
    never carry `refresh_token_hash`, a password, or a password hash —
    it's just two fresh token strings."""

    async def body(session: AsyncSession) -> None:
        user, raw_refresh_token = await _login_active_user(session)
        try:
            result = await refresh_session(session, redis_client, raw_refresh_token)
            fields = result._asdict()
            assert set(fields) == {"access_token", "refresh_token"}
            for value in fields.values():
                assert "password" not in value
        finally:
            db_session = await _current_session_for(session, user.id)
            await refresh_store.invalidate(redis_client, db_session.refresh_token_hash)

    run_db_test(body)
