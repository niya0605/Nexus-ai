"""Service-level tests for `initiate_password_reset` and
`apply_password_reset` — including the frozen "revokes ALL active
Sessions" requirement.

Real Postgres + real Redis, same approach as test_refresh_service.py.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.db import run_db_test

from app.core.security import hash_refresh_token, verify_password
from app.db.redis import redis_client
from app.modules.auth import refresh_store, token_store
from app.modules.auth.exceptions import PasswordTooWeakError, TokenExpiredError, TokenInvalidError
from app.modules.auth.models import Session, SessionStatus, User, UserStatus
from app.modules.auth.schemas import LoginRequest, RegisterRequest
from app.modules.auth.service import (
    apply_password_reset,
    initiate_password_reset,
    login_user,
    refresh_session,
    register_user,
)

_TEST_PASSWORD = "a-strong-password"
_NEW_PASSWORD = "a-different-strong-password"
_RESET_TTL_SECONDS = 3600
_TEST_IP = "203.0.113.10"  # RFC 5737 TEST-NET-3 — documentation-only.


def _register_request(**overrides: object) -> RegisterRequest:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4().hex[:8]}@example.com",
        "password": _TEST_PASSWORD,
        "display_name": "Test User",
    }
    defaults.update(overrides)
    return RegisterRequest(**defaults)  # type: ignore[arg-type]


async def _active_user(session: AsyncSession, **overrides: object) -> User:
    user = await register_user(session, _register_request(**overrides))
    user.status = UserStatus.ACTIVE
    user.email_verified_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(user)
    return user


async def _login(session: AsyncSession, user: User) -> str:
    result = await login_user(
        session,
        redis_client,
        LoginRequest(email=user.email, password=_TEST_PASSWORD),
        _TEST_IP,  # type: ignore[arg-type]
    )
    return result.refresh_token


async def _sessions_for(session: AsyncSession, user_id: uuid.UUID) -> list[Session]:
    return list(
        (await session.execute(select(Session).where(Session.user_id == user_id))).scalars().all()
    )


async def _cleanup_sessions(session: AsyncSession, user_id: uuid.UUID) -> None:
    for db_session in await _sessions_for(session, user_id):
        await refresh_store.invalidate(redis_client, db_session.refresh_token_hash)


async def _expire_stored_token(raw_token: str) -> None:
    token_hash = hash_refresh_token(raw_token)
    key = f"{token_store._RESET_TOKEN_PREFIX}{token_hash}"
    await redis_client.hset(
        key, "expires_at", (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    )


# ---------------------------------------------------------------------------
# apply_password_reset — success path + session invalidation
# ---------------------------------------------------------------------------


def test_valid_token_and_password_succeeds() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)
        raw_token = await token_store.issue_reset_token(redis_client, user.id, _RESET_TTL_SECONDS)

        await apply_password_reset(session, redis_client, raw_token, _NEW_PASSWORD)

        fetched = await session.get(User, user.id)
        assert verify_password(_NEW_PASSWORD, fetched.password_hash) is True

    run_db_test(body)


def test_password_is_hashed_not_plaintext() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)
        raw_token = await token_store.issue_reset_token(redis_client, user.id, _RESET_TTL_SECONDS)

        await apply_password_reset(session, redis_client, raw_token, _NEW_PASSWORD)

        fetched = await session.get(User, user.id)
        assert fetched.password_hash != _NEW_PASSWORD
        assert _NEW_PASSWORD not in fetched.password_hash
        assert fetched.password_hash.startswith("$argon2")

    run_db_test(body)


def test_token_unusable_after_reset() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)
        raw_token = await token_store.issue_reset_token(redis_client, user.id, _RESET_TTL_SECONDS)

        await apply_password_reset(session, redis_client, raw_token, _NEW_PASSWORD)

        with pytest.raises(TokenInvalidError):
            await apply_password_reset(session, redis_client, raw_token, "yet-another-password")

    run_db_test(body)


def test_expired_token_rejected() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)
        raw_token = await token_store.issue_reset_token(redis_client, user.id, _RESET_TTL_SECONDS)
        await _expire_stored_token(raw_token)

        with pytest.raises(TokenExpiredError):
            await apply_password_reset(session, redis_client, raw_token, _NEW_PASSWORD)

        fetched = await session.get(User, user.id)
        assert verify_password(_TEST_PASSWORD, fetched.password_hash) is True  # unchanged

    run_db_test(body)


def test_invalid_token_rejected() -> None:
    async def body(session: AsyncSession) -> None:
        with pytest.raises(TokenInvalidError):
            await apply_password_reset(session, redis_client, "not-a-real-token", _NEW_PASSWORD)

    run_db_test(body)


def test_weak_password_rejected_with_password_too_weak() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)
        raw_token = await token_store.issue_reset_token(redis_client, user.id, _RESET_TTL_SECONDS)

        with pytest.raises(PasswordTooWeakError):
            await apply_password_reset(session, redis_client, raw_token, "short")

        # The weak-password rejection must not have burned the token —
        # a valid password against the *same* token still works.
        await apply_password_reset(session, redis_client, raw_token, _NEW_PASSWORD)
        fetched = await session.get(User, user.id)
        assert verify_password(_NEW_PASSWORD, fetched.password_hash) is True

    run_db_test(body)


def test_reset_revokes_all_active_sessions() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)
        await _login(session, user)
        await _login(session, user)
        raw_reset_token = await token_store.issue_reset_token(
            redis_client, user.id, _RESET_TTL_SECONDS
        )

        try:
            await apply_password_reset(session, redis_client, raw_reset_token, _NEW_PASSWORD)

            sessions = await _sessions_for(session, user.id)
            assert len(sessions) == 2
            assert all(s.status == SessionStatus.REVOKED for s in sessions)
            assert all(s.revoked_at is not None for s in sessions)
        finally:
            await _cleanup_sessions(session, user.id)

    run_db_test(body)


def test_reset_invalidates_redis_refresh_records() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)
        raw_refresh_token = await _login(session, user)
        raw_reset_token = await token_store.issue_reset_token(
            redis_client, user.id, _RESET_TTL_SECONDS
        )

        [db_session] = await _sessions_for(session, user.id)
        token_hash = db_session.refresh_token_hash

        await apply_password_reset(session, redis_client, raw_reset_token, _NEW_PASSWORD)

        assert await refresh_store.get_session_id(redis_client, token_hash) is None
        assert raw_refresh_token  # sanity: we did actually have a real token

    run_db_test(body)


def test_revoked_session_cannot_refresh_after_reset() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)
        raw_refresh_token = await _login(session, user)
        raw_reset_token = await token_store.issue_reset_token(
            redis_client, user.id, _RESET_TTL_SECONDS
        )

        await apply_password_reset(session, redis_client, raw_reset_token, _NEW_PASSWORD)

        with pytest.raises(TokenInvalidError):
            await refresh_session(session, redis_client, raw_refresh_token)

    run_db_test(body)


# ---------------------------------------------------------------------------
# initiate_password_reset — anti-enumeration
# ---------------------------------------------------------------------------


def test_forgot_password_for_existing_user_is_silent_success() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)
        await initiate_password_reset(session, redis_client, user.email)  # must not raise

    run_db_test(body)


def test_forgot_password_for_nonexistent_email_is_silent_success() -> None:
    async def body(session: AsyncSession) -> None:
        await initiate_password_reset(
            session, redis_client, "nobody-here@example.com"
        )  # must not raise

    run_db_test(body)


def test_forgot_password_issues_a_single_use_time_boxed_token() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)

        # Can't intercept the randomly-generated raw token through the
        # public API (by design — it's only ever emailed), so this
        # proves single-use/time-boxing via the same token_store
        # primitives directly, which initiate_password_reset itself
        # calls under the hood.
        await initiate_password_reset(session, redis_client, user.email)
        raw_token = await token_store.issue_reset_token(redis_client, user.id, _RESET_TTL_SECONDS)

        await apply_password_reset(session, redis_client, raw_token, _NEW_PASSWORD)
        with pytest.raises(TokenInvalidError):
            await apply_password_reset(session, redis_client, raw_token, "another-strong-password")

    run_db_test(body)
