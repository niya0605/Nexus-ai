"""Tests for app/core/security.py's S1C.1 primitives.

Pure unit tests — no database, no HTTP client, per this milestone's
explicit scope. `run_db_test`/`run_http_test` (backend/tests/db.py) are
deliberately not used here.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.config import settings
from app.core.security import (
    ACCESS_TOKEN_TYPE,
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    refresh_token_expires_at,
    verify_password,
)

# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------


def test_hash_password_does_not_return_plaintext() -> None:
    password = "a-strong-password"
    hashed = hash_password(password)

    assert hashed != password
    assert password not in hashed
    assert hashed.startswith("$argon2")


def test_verify_password_succeeds_for_correct_password() -> None:
    password = "a-strong-password"
    hashed = hash_password(password)

    assert verify_password(password, hashed) is True


def test_verify_password_fails_for_wrong_password() -> None:
    hashed = hash_password("a-strong-password")

    assert verify_password("a-different-password", hashed) is False


def test_verify_password_fails_for_malformed_hash_without_raising() -> None:
    # A corrupted/foreign hash string must fail closed, not raise an
    # Argon2 exception up through this function.
    assert verify_password("anything", "not-a-real-argon2-hash") is False


def test_hash_password_is_salted_two_hashes_differ() -> None:
    password = "a-strong-password"

    assert hash_password(password) != hash_password(password)


# ---------------------------------------------------------------------------
# Access tokens
# ---------------------------------------------------------------------------


def test_create_access_token_returns_a_jwt_string() -> None:
    token = create_access_token(uuid.uuid4())

    assert isinstance(token, str)
    assert token.count(".") == 2  # header.payload.signature


def test_access_token_contains_expected_claims() -> None:
    user_id = uuid.uuid4()
    token = create_access_token(user_id)

    payload = decode_access_token(token)

    assert payload["sub"] == str(user_id)
    assert payload["type"] == ACCESS_TOKEN_TYPE
    assert "iat" in payload
    assert "exp" in payload
    assert payload["exp"] > payload["iat"]


def test_access_token_expiry_matches_configured_ttl() -> None:
    token = create_access_token(uuid.uuid4())
    payload = decode_access_token(token)

    actual_ttl_seconds = payload["exp"] - payload["iat"]
    expected_ttl_seconds = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

    assert actual_ttl_seconds == expected_ttl_seconds


def test_expired_access_token_is_rejected() -> None:
    now = datetime.now(UTC)
    expired_payload = {
        "sub": str(uuid.uuid4()),
        "type": ACCESS_TOKEN_TYPE,
        "iat": now - timedelta(minutes=30),
        "exp": now - timedelta(minutes=15),
    }
    expired_token = jwt.encode(
        expired_payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(expired_token)


def test_valid_access_token_can_be_decoded() -> None:
    user_id = uuid.uuid4()
    token = create_access_token(user_id)

    payload = decode_access_token(token)

    assert payload["sub"] == str(user_id)


def test_malformed_token_is_rejected() -> None:
    with pytest.raises(InvalidTokenError):
        decode_access_token("this-is-not-a-jwt")


def test_token_signed_with_wrong_secret_is_rejected() -> None:
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid.uuid4()),
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(minutes=15),
    }
    wrongly_signed = jwt.encode(
        payload,
        "a-completely-different-and-sufficiently-long-secret",
        algorithm=settings.JWT_ALGORITHM,
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(wrongly_signed)


def test_token_with_wrong_type_is_rejected() -> None:
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid.uuid4()),
        "type": "refresh",  # not "access"
        "iat": now,
        "exp": now + timedelta(minutes=15),
    }
    wrong_type_token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    with pytest.raises(InvalidTokenError):
        decode_access_token(wrong_type_token)


# ---------------------------------------------------------------------------
# Refresh tokens
# ---------------------------------------------------------------------------


def test_refresh_tokens_are_random_and_different_between_calls() -> None:
    assert create_refresh_token() != create_refresh_token()


def test_refresh_token_hash_is_not_equal_to_plaintext() -> None:
    token = create_refresh_token()

    assert hash_refresh_token(token) != token


def test_refresh_token_hash_is_deterministic_for_the_same_token() -> None:
    token = create_refresh_token()

    assert hash_refresh_token(token) == hash_refresh_token(token)


def test_refresh_token_generation_has_sufficient_entropy() -> None:
    # 32 bytes (256 bits) urlsafe-base64-encoded is ~43 characters — a
    # short/low-entropy token would be nowhere close to this length.
    token = create_refresh_token()
    assert len(token) >= 40

    # A large batch generated with zero collisions is a practical sanity
    # check on top of the length check above — a weak/narrow random
    # source would show collisions well before 2,000 draws.
    tokens = {create_refresh_token() for _ in range(2000)}
    assert len(tokens) == 2000


def test_refresh_token_expires_at_uses_configured_ttl() -> None:
    before = datetime.now(UTC)
    expires_at = refresh_token_expires_at()
    after = datetime.now(UTC)

    assert expires_at.tzinfo is not None
    assert before + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS) <= expires_at
    assert expires_at <= after + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
