"""Service-level tests for `login_user`.

Runs against a real, transactionally-isolated PostgreSQL session (see
backend/tests/db.py) — same pattern as test_registration_service.py.
Covers successful login (tokens, Session creation, metadata updates)
and every failure path (wrong password, nonexistent email,
pending_verification, deactivated), plus that a failed attempt never
leaves the session unusable for a later call.
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
from app.modules.auth.exceptions import EmailNotVerifiedError, InvalidCredentialsError
from app.modules.auth.models import Session, SessionStatus, User, UserStatus
from app.modules.auth.schemas import LoginRequest, RegisterRequest
from app.modules.auth.service import login_user, register_user

_TEST_PASSWORD = "a-strong-password"
# RFC 5737 TEST-NET-3 — a documentation-only address block, never a real one.
_TEST_IP = "203.0.113.10"


def _register_request(**overrides: object) -> RegisterRequest:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4().hex[:8]}@example.com",
        "password": _TEST_PASSWORD,
        "display_name": "Test User",
    }
    defaults.update(overrides)
    return RegisterRequest(**defaults)  # type: ignore[arg-type]


def _login_request(email: str, password: str = _TEST_PASSWORD) -> LoginRequest:
    return LoginRequest(email=email, password=password)  # type: ignore[arg-type]


async def _register_active_user(session: AsyncSession, **overrides: object) -> User:
    """Register, then activate directly — there is no email-verification
    flow implemented yet (a later milestone), so tests needing an
    already-verified account set status/email_verified_at directly,
    same as other fixtures in this codebase construct rows outside the
    flow under test."""
    user = await register_user(session, _register_request(**overrides))
    user.status = UserStatus.ACTIVE
    user.email_verified_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(user)
    return user


async def _sessions_for(session: AsyncSession, user_id: object) -> list[Session]:
    return list(
        (await session.execute(select(Session).where(Session.user_id == user_id))).scalars().all()
    )


# ---------------------------------------------------------------------------
# Successful login
# ---------------------------------------------------------------------------


def test_login_succeeds_with_correct_credentials() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _register_active_user(session)

        result = await login_user(session, redis_client, _login_request(user.email), _TEST_IP)

        assert result.user.id == user.id

    run_db_test(body)


def test_login_returns_a_valid_access_token() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _register_active_user(session)

        result = await login_user(session, redis_client, _login_request(user.email), _TEST_IP)

        claims = decode_access_token(result.access_token)
        assert claims["sub"] == str(user.id)

    run_db_test(body)


def test_login_returns_a_refresh_token() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _register_active_user(session)

        result = await login_user(session, redis_client, _login_request(user.email), _TEST_IP)

        assert isinstance(result.refresh_token, str)
        assert len(result.refresh_token) >= 40  # see security.py's own entropy test

    run_db_test(body)


def test_login_stores_refresh_token_hash_not_raw_token() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _register_active_user(session)

        result = await login_user(session, redis_client, _login_request(user.email), _TEST_IP)

        [db_session] = await _sessions_for(session, user.id)
        assert db_session.refresh_token_hash == hash_refresh_token(result.refresh_token)
        assert db_session.refresh_token_hash != result.refresh_token

    run_db_test(body)


def test_login_creates_active_session_with_correct_fields() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _register_active_user(session)

        await login_user(session, redis_client, _login_request(user.email), _TEST_IP)

        [db_session] = await _sessions_for(session, user.id)
        assert db_session.status == SessionStatus.ACTIVE
        assert db_session.ip_address == _TEST_IP
        assert db_session.revoked_at is None

    run_db_test(body)


def test_login_stores_refresh_token_in_redis() -> None:
    """S1D: `login_user` must populate the Redis refresh-token store
    (not just Postgres), or the very first `/refresh` call for a brand
    new session would fail with `token_invalid` — see service.py's
    login_user docstring note on this."""

    async def body(session: AsyncSession) -> None:
        user = await _register_active_user(session)

        result = await login_user(session, redis_client, _login_request(user.email), _TEST_IP)

        [db_session] = await _sessions_for(session, user.id)
        try:
            redis_session_id = await refresh_store.get_session_id(
                redis_client, hash_refresh_token(result.refresh_token)
            )
            assert redis_session_id == str(db_session.id)
        finally:
            await refresh_store.invalidate(redis_client, db_session.refresh_token_hash)

    run_db_test(body)


def test_login_session_expiry_matches_configured_ttl() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _register_active_user(session)
        before = datetime.now(UTC)

        await login_user(session, redis_client, _login_request(user.email), _TEST_IP)

        after = datetime.now(UTC)
        [db_session] = await _sessions_for(session, user.id)
        ttl = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        assert before + ttl <= db_session.expires_at <= after + ttl

    run_db_test(body)


def test_login_sets_last_login_at() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _register_active_user(session)
        assert user.last_login_at is None
        before = datetime.now(UTC)

        result = await login_user(session, redis_client, _login_request(user.email), _TEST_IP)

        after = datetime.now(UTC)
        assert result.user.last_login_at is not None
        assert before <= result.user.last_login_at <= after

    run_db_test(body)


def test_login_resets_failed_login_count() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _register_active_user(session)

        with pytest.raises(InvalidCredentialsError):
            await login_user(
                session, redis_client, _login_request(user.email, password="wrong"), _TEST_IP
            )

        result = await login_user(session, redis_client, _login_request(user.email), _TEST_IP)

        assert result.user.failed_login_count == 0

    run_db_test(body)


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


def test_login_wrong_password_rejected() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _register_active_user(session)

        with pytest.raises(InvalidCredentialsError):
            await login_user(
                session,
                redis_client,
                _login_request(user.email, password="wrong-password"),
                _TEST_IP,
            )

    run_db_test(body)


def test_login_nonexistent_email_rejected() -> None:
    async def body(session: AsyncSession) -> None:
        with pytest.raises(InvalidCredentialsError):
            await login_user(
                session, redis_client, _login_request("nobody-here@example.com"), _TEST_IP
            )

    run_db_test(body)


def test_login_pending_verification_account_rejected() -> None:
    async def body(session: AsyncSession) -> None:
        user = await register_user(session, _register_request())  # stays pending_verification

        with pytest.raises(EmailNotVerifiedError):
            await login_user(session, redis_client, _login_request(user.email), _TEST_IP)

    run_db_test(body)


def test_login_deactivated_account_rejected() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _register_active_user(session)
        user.status = UserStatus.DEACTIVATED
        await session.commit()

        # See login_user's docstring: reusing InvalidCredentialsError for
        # "deactivated" is a flagged contract gap, not a confirmed spec.
        with pytest.raises(InvalidCredentialsError):
            await login_user(session, redis_client, _login_request(user.email), _TEST_IP)

    run_db_test(body)


def test_login_wrong_password_increments_failed_login_count() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _register_active_user(session)

        with pytest.raises(InvalidCredentialsError):
            await login_user(
                session, redis_client, _login_request(user.email, password="wrong"), _TEST_IP
            )
        fetched = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        assert fetched.failed_login_count == 1

        with pytest.raises(InvalidCredentialsError):
            await login_user(
                session, redis_client, _login_request(user.email, password="still-wrong"), _TEST_IP
            )
        fetched = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        assert fetched.failed_login_count == 2

    run_db_test(body)


def test_no_session_created_on_wrong_password() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _register_active_user(session)

        with pytest.raises(InvalidCredentialsError):
            await login_user(
                session, redis_client, _login_request(user.email, password="wrong"), _TEST_IP
            )

        assert await _sessions_for(session, user.id) == []

    run_db_test(body)


def test_no_session_created_for_pending_verification_account() -> None:
    async def body(session: AsyncSession) -> None:
        user = await register_user(session, _register_request())

        with pytest.raises(EmailNotVerifiedError):
            await login_user(session, redis_client, _login_request(user.email), _TEST_IP)

        assert await _sessions_for(session, user.id) == []

    run_db_test(body)


def test_session_still_usable_after_a_failed_login_attempt() -> None:
    """The closest analogue here to registration's own
    "transaction rolls back" test: a failed attempt's own commit (the
    failed_login_count increment) must never leave the session in a
    broken/aborted state that a later, unrelated call on the same
    session would trip over."""

    async def body(session: AsyncSession) -> None:
        user = await _register_active_user(session)

        with pytest.raises(InvalidCredentialsError):
            await login_user(
                session, redis_client, _login_request(user.email, password="wrong"), _TEST_IP
            )

        result = await login_user(session, redis_client, _login_request(user.email), _TEST_IP)
        assert result.user.id == user.id

    run_db_test(body)
