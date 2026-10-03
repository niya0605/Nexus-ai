"""Service-level tests for `register_user`.

Runs against a real, transactionally-isolated PostgreSQL session (see
backend/tests/db.py) — covers initial user state, email normalization,
Argon2 hashing, duplicate-email handling (including case-insensitivity),
and transaction rollback behavior.
"""

import uuid

import pytest
from argon2 import PasswordHasher
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from tests.db import run_db_test

from app.modules.auth.exceptions import EmailAlreadyRegisteredError
from app.modules.auth.models import User, UserStatus
from app.modules.auth.schemas import RegisterRequest
from app.modules.auth.service import register_user

_verifier = PasswordHasher()


def _request(**overrides: object) -> RegisterRequest:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4().hex[:8]}@example.com",
        "password": "a-strong-password",
        "display_name": "Test User",
    }
    defaults.update(overrides)
    return RegisterRequest(**defaults)  # type: ignore[arg-type]


def test_register_creates_user_with_correct_initial_state() -> None:
    async def body(session: AsyncSession) -> None:
        user = await register_user(session, _request())

        assert user.status == UserStatus.PENDING_VERIFICATION
        assert user.email_verified_at is None
        assert user.failed_login_count == 0
        assert user.last_login_at is None
        assert user.deactivated_at is None
        assert user.avatar_url is None
        assert user.created_at is not None
        assert user.updated_at is not None

    run_db_test(body)


def test_register_normalizes_and_stores_email() -> None:
    async def body(session: AsyncSession) -> None:
        raw_email = "  MixedCase@Example.COM  "
        req = _request(email=raw_email)
        user = await register_user(session, req)

        assert user.email == "mixedcase@example.com"

        fetched = (await session.execute(select(User).where(User.id == user.id))).scalar_one()
        assert fetched.email == "mixedcase@example.com"

    run_db_test(body)


def test_register_hashes_password_with_argon2() -> None:
    async def body(session: AsyncSession) -> None:
        user = await register_user(session, _request(password="a-strong-password"))

        assert user.password_hash.startswith("$argon2")
        # The hash must actually verify against the original password —
        # proves it's a real, usable Argon2 hash, not just a
        # correctly-prefixed string.
        assert _verifier.verify(user.password_hash, "a-strong-password") is True

    run_db_test(body)


def test_register_does_not_store_plaintext_password() -> None:
    async def body(session: AsyncSession) -> None:
        raw_password = "a-strong-password"
        user = await register_user(session, _request(password=raw_password))

        assert user.password_hash != raw_password
        assert raw_password not in user.password_hash

    run_db_test(body)


def test_register_duplicate_email_rejected() -> None:
    async def body(session: AsyncSession) -> None:
        email = f"dup-{uuid.uuid4().hex[:8]}@example.com"
        await register_user(session, _request(email=email))

        with pytest.raises(EmailAlreadyRegisteredError):
            await register_user(session, _request(email=email))

    run_db_test(body)


def test_register_duplicate_email_different_casing_rejected() -> None:
    async def body(session: AsyncSession) -> None:
        base = f"dup-{uuid.uuid4().hex[:8]}"
        await register_user(session, _request(email=f"{base}@example.com"))

        # RegisterRequest itself normalizes case, so simulate the same
        # normalized-but-originally-different-case address a second
        # registration attempt would produce.
        with pytest.raises(EmailAlreadyRegisteredError):
            await register_user(session, _request(email=f"{base.upper()}@EXAMPLE.COM"))

    run_db_test(body)


def test_register_transaction_rolls_back_on_duplicate_email() -> None:
    async def body(session: AsyncSession) -> None:
        email = f"rollback-{uuid.uuid4().hex[:8]}@example.com"
        await register_user(session, _request(email=email))

        with pytest.raises(EmailAlreadyRegisteredError):
            await register_user(session, _request(email=email))

        # The session must still be usable after the failed attempt's
        # rollback — and exactly one row (the original) exists, never a
        # partial/duplicate one from the failed insert.
        count = (await session.execute(select(User).where(User.email == email))).scalars().all()
        assert len(count) == 1

        # A completely unrelated registration on the same session must
        # still succeed, proving the session wasn't left unusable.
        other = await register_user(session, _request())
        assert other.id is not None

    run_db_test(body)


def test_register_duplicate_email_raises_integrity_error_only_for_email_constraint() -> None:
    """Sanity check on the constraint-name matching itself: a
    non-duplicate-email IntegrityError must not be silently
    reinterpreted as EmailAlreadyRegisteredError."""

    async def body(session: AsyncSession) -> None:
        user = User(email="not-null-check@example.com", password_hash=None, display_name="X")  # type: ignore[arg-type]
        session.add(user)
        with pytest.raises(IntegrityError) as exc_info:
            await session.commit()
        assert "uq_users_email_lower" not in str(exc_info.value.orig)

    run_db_test(body)
