"""Service-level tests for `logout_session`, `list_sessions`,
`revoke_session`, and `revoke_other_sessions`.

Same real-Postgres + real-Redis integration approach as
test_refresh_service.py — see that file's module docstring.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.db import run_db_test

from app.core.security import hash_refresh_token
from app.db.redis import redis_client
from app.modules.auth import refresh_store
from app.modules.auth.exceptions import SessionNotFoundError
from app.modules.auth.models import Session, SessionStatus, User, UserStatus
from app.modules.auth.schemas import LoginRequest, RegisterRequest
from app.modules.auth.service import (
    list_sessions,
    login_user,
    logout_session,
    register_user,
    revoke_other_sessions,
    revoke_session,
)

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


async def _active_user(session: AsyncSession, **overrides: object) -> User:
    user = await register_user(session, _register_request(**overrides))
    user.status = UserStatus.ACTIVE
    user.email_verified_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(user)
    return user


async def _login(session: AsyncSession, user: User) -> str:
    """Log in as `user`, returning the raw refresh token — a fresh
    "device"/session each call, exactly like a real second login would
    produce."""
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


async def _cleanup(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Best-effort: invalidate every Redis record this user's test
    sessions still hold, regardless of status."""
    for db_session in await _sessions_for(session, user_id):
        await refresh_store.invalidate(redis_client, db_session.refresh_token_hash)


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


def test_logout_revokes_the_current_session() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)
        raw_refresh_token = await _login(session, user)
        try:
            await logout_session(session, redis_client, user.id, raw_refresh_token)

            [db_session] = await _sessions_for(session, user.id)
            assert db_session.status == SessionStatus.REVOKED
        finally:
            await _cleanup(session, user.id)

    run_db_test(body)


def test_logout_invalidates_the_redis_record() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)
        raw_refresh_token = await _login(session, user)
        try:
            [db_session] = await _sessions_for(session, user.id)
            token_hash = db_session.refresh_token_hash

            await logout_session(session, redis_client, user.id, raw_refresh_token)

            assert await refresh_store.get_session_id(redis_client, token_hash) is None
        finally:
            await _cleanup(session, user.id)

    run_db_test(body)


def test_logout_sets_revoked_at() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)
        raw_refresh_token = await _login(session, user)
        try:
            before = datetime.now(UTC)
            await logout_session(session, redis_client, user.id, raw_refresh_token)
            after = datetime.now(UTC)

            [db_session] = await _sessions_for(session, user.id)
            assert db_session.revoked_at is not None
            assert before <= db_session.revoked_at <= after
        finally:
            await _cleanup(session, user.id)

    run_db_test(body)


def test_logout_with_no_cookie_is_a_silent_no_op() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)
        # No prior login at all — nothing to revoke, must not raise.
        await logout_session(session, redis_client, user.id, None)

    run_db_test(body)


def test_logout_does_not_touch_another_users_session() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _active_user(session)
        other = await _active_user(session)
        owner_token = await _login(session, owner)
        try:
            # `other` tries to log out using `owner`'s refresh cookie —
            # must not revoke it, since it doesn't belong to `other`.
            await logout_session(session, redis_client, other.id, owner_token)

            [owner_session] = await _sessions_for(session, owner.id)
            assert owner_session.status == SessionStatus.ACTIVE
        finally:
            await _cleanup(session, owner.id)

    run_db_test(body)


# ---------------------------------------------------------------------------
# List sessions
# ---------------------------------------------------------------------------


def test_list_sessions_returns_own_active_sessions() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)
        await _login(session, user)
        await _login(session, user)
        try:
            sessions = await list_sessions(session, user.id)
            assert len(sessions) == 2
            assert all(s.status == SessionStatus.ACTIVE for s in sessions)
        finally:
            await _cleanup(session, user.id)

    run_db_test(body)


def test_list_sessions_never_returns_another_users_sessions() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)
        other = await _active_user(session)
        await _login(session, other)
        try:
            sessions = await list_sessions(session, user.id)
            assert sessions == []
        finally:
            await _cleanup(session, other.id)

    run_db_test(body)


def test_list_sessions_excludes_revoked_sessions() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)
        raw_refresh_token = await _login(session, user)
        try:
            await logout_session(session, redis_client, user.id, raw_refresh_token)

            sessions = await list_sessions(session, user.id)
            assert sessions == []
        finally:
            await _cleanup(session, user.id)

    run_db_test(body)


def test_session_rows_never_carry_refresh_token_hash_off_the_model() -> None:
    """Not a serialization test (that's the HTTP-level suite) — proves
    the *hash itself* the schema must never leak is exactly what backs
    `Session.refresh_token_hash`, i.e. the field genuinely exists and
    genuinely isn't blank/placeholder data a schema test could pass
    against by accident."""

    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)
        await _login(session, user)
        try:
            [db_session] = await list_sessions(session, user.id)
            assert db_session.refresh_token_hash
            assert len(db_session.refresh_token_hash) == 64  # sha256 hex digest
        finally:
            await _cleanup(session, user.id)

    run_db_test(body)


# ---------------------------------------------------------------------------
# Revoke a specific session
# ---------------------------------------------------------------------------


def test_revoke_session_revokes_own_session() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)
        await _login(session, user)
        try:
            [db_session] = await _sessions_for(session, user.id)

            await revoke_session(session, redis_client, user.id, db_session.id)

            [after] = await _sessions_for(session, user.id)
            assert after.status == SessionStatus.REVOKED
            assert after.revoked_at is not None
        finally:
            await _cleanup(session, user.id)

    run_db_test(body)


def test_revoke_session_invalidates_redis_record() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)
        await _login(session, user)
        try:
            [db_session] = await _sessions_for(session, user.id)
            token_hash = db_session.refresh_token_hash

            await revoke_session(session, redis_client, user.id, db_session.id)

            assert await refresh_store.get_session_id(redis_client, token_hash) is None
        finally:
            await _cleanup(session, user.id)

    run_db_test(body)


def test_revoke_session_rejects_another_users_session() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _active_user(session)
        attacker = await _active_user(session)
        await _login(session, owner)
        try:
            [owner_session] = await _sessions_for(session, owner.id)

            with pytest.raises(SessionNotFoundError):
                await revoke_session(session, redis_client, attacker.id, owner_session.id)

            [still_active] = await _sessions_for(session, owner.id)
            assert still_active.status == SessionStatus.ACTIVE
        finally:
            await _cleanup(session, owner.id)

    run_db_test(body)


def test_revoke_session_rejects_nonexistent_session_id() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)

        with pytest.raises(SessionNotFoundError):
            await revoke_session(session, redis_client, user.id, uuid.uuid4())

    run_db_test(body)


# ---------------------------------------------------------------------------
# Revoke all other sessions
# ---------------------------------------------------------------------------


def test_revoke_other_sessions_revokes_all_but_current() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)
        current_token = await _login(session, user)
        await _login(session, user)
        await _login(session, user)
        try:
            await revoke_other_sessions(session, redis_client, user.id, current_token)

            sessions = await _sessions_for(session, user.id)
            active = [s for s in sessions if s.status == SessionStatus.ACTIVE]
            revoked = [s for s in sessions if s.status == SessionStatus.REVOKED]
            assert len(active) == 1
            assert len(revoked) == 2
        finally:
            await _cleanup(session, user.id)

    run_db_test(body)


def test_revoke_other_sessions_keeps_current_session_active() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)
        current_token = await _login(session, user)
        await _login(session, user)
        try:
            await revoke_other_sessions(session, redis_client, user.id, current_token)

            active = await list_sessions(session, user.id)
            assert len(active) == 1
            assert active[0].refresh_token_hash == hash_refresh_token(current_token)
        finally:
            await _cleanup(session, user.id)

    run_db_test(body)


def test_revoke_other_sessions_invalidates_all_their_redis_records() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)
        current_token = await _login(session, user)
        await _login(session, user)
        try:
            all_sessions_before = await _sessions_for(session, user.id)
            current_hash = hash_refresh_token(current_token)
            other_hashes = [
                s.refresh_token_hash
                for s in all_sessions_before
                if s.refresh_token_hash != current_hash
            ]

            await revoke_other_sessions(session, redis_client, user.id, current_token)

            for token_hash in other_hashes:
                assert await refresh_store.get_session_id(redis_client, token_hash) is None
        finally:
            await _cleanup(session, user.id)

    run_db_test(body)


def test_revoke_other_sessions_never_touches_another_user() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _active_user(session)
        other = await _active_user(session)
        current_token = await _login(session, user)
        await _login(session, other)
        try:
            await revoke_other_sessions(session, redis_client, user.id, current_token)

            [other_session] = await _sessions_for(session, other.id)
            assert other_session.status == SessionStatus.ACTIVE
        finally:
            await _cleanup(session, user.id)
            await _cleanup(session, other.id)

    run_db_test(body)
