"""Model tests for the Authentication domain's User and Session.

Covers table creation, uniqueness, nullable constraints, and
relationship integrity — nothing else. No password hashing, no JWT, no
login flow: this sprint is data shape only.

Requires a real, reachable PostgreSQL matching the backend's `.env`
configuration — see backend/tests/db.py.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from tests.db import run_db_test

from app.modules.auth.models import Session, SessionStatus, User, UserStatus


def _make_user(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4().hex[:8]}@example.com",
        "password_hash": "not-a-real-hash",
        "display_name": "Test User",
    }
    defaults.update(overrides)
    return User(**defaults)  # type: ignore[arg-type]


def _make_session(user_id: uuid.UUID, **overrides: object) -> Session:
    defaults: dict[str, object] = {
        "user_id": user_id,
        "refresh_token_hash": f"hash-{uuid.uuid4().hex}",
        "ip_address": "127.0.0.1",
        "expires_at": datetime.now(UTC) + timedelta(days=30),
    }
    defaults.update(overrides)
    return Session(**defaults)  # type: ignore[arg-type]


def test_create_and_fetch_user() -> None:
    async def body(session: AsyncSession) -> None:
        user = _make_user()
        session.add(user)
        await session.flush()

        fetched = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        assert fetched.email == user.email
        assert fetched.status == UserStatus.PENDING_VERIFICATION  # default applied
        assert fetched.failed_login_count == 0  # default applied
        assert fetched.display_name == "Test User"

    run_db_test(body)


def test_user_email_uniqueness_is_case_insensitive() -> None:
    async def body(session: AsyncSession) -> None:
        email = f"dup-{uuid.uuid4().hex[:8]}@example.com"
        session.add(_make_user(email=email))
        await session.flush()

        # Same email, different case — must still collide, per the
        # functional lower(email) unique index.
        session.add(_make_user(email=email.upper()))
        with pytest.raises(IntegrityError):
            await session.flush()

    run_db_test(body)


def test_user_required_field_cannot_be_null() -> None:
    async def body(session: AsyncSession) -> None:
        user = _make_user(password_hash=None)  # deliberately invalid
        session.add(user)
        with pytest.raises(IntegrityError):
            await session.flush()

    run_db_test(body)


def test_session_belongs_to_user_and_user_sees_it() -> None:
    async def body(session: AsyncSession) -> None:
        user = _make_user()
        session.add(user)
        await session.flush()

        sess = _make_session(user.id)
        session.add(sess)
        await session.flush()
        await session.refresh(user, attribute_names=["sessions"])

        assert sess.user_id == user.id
        assert sess.status == SessionStatus.ACTIVE  # default applied
        assert sess in user.sessions

    run_db_test(body)


def test_session_refresh_token_hash_uniqueness() -> None:
    async def body(session: AsyncSession) -> None:
        user = _make_user()
        session.add(user)
        await session.flush()

        shared_hash = f"hash-{uuid.uuid4().hex}"
        session.add(_make_session(user.id, refresh_token_hash=shared_hash))
        await session.flush()

        session.add(_make_session(user.id, refresh_token_hash=shared_hash))
        with pytest.raises(IntegrityError):
            await session.flush()

    run_db_test(body)


def test_deleting_user_cascades_to_sessions() -> None:
    async def body(session: AsyncSession) -> None:
        user = _make_user()
        session.add(user)
        await session.flush()

        sess = _make_session(user.id)
        session.add(sess)
        await session.flush()
        session_id = sess.id

        await session.delete(user)
        await session.flush()

        remaining = (
            await session.execute(select(Session).where(Session.id == session_id))
        ).scalar_one_or_none()
        assert remaining is None

    run_db_test(body)
