"""Schema-level validation tests for registration.

Pure Pydantic — no database involved. Covers the centralized
email/password/display-name rules (app/core/validation.py) as applied
through RegisterRequest.
"""

import pytest
from pydantic import ValidationError

from app.modules.auth.schemas import RegisterRequest


def test_email_is_trimmed_and_lowercased() -> None:
    req = RegisterRequest(
        email="  Someone@Example.COM  ", password="a-strong-password", display_name="Someone"
    )
    assert req.email == "someone@example.com"


def test_invalid_email_format_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        RegisterRequest(email="not-an-email", password="a-strong-password", display_name="Someone")
    assert any(err["loc"] == ("email",) for err in exc_info.value.errors())


def test_password_too_short_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        RegisterRequest(email="someone@example.com", password="short1", display_name="Someone")
    assert any(err["loc"] == ("password",) for err in exc_info.value.errors())


def test_password_too_long_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        RegisterRequest(email="someone@example.com", password="a" * 129, display_name="Someone")
    assert any(err["loc"] == ("password",) for err in exc_info.value.errors())


def test_password_at_length_boundaries_accepted() -> None:
    RegisterRequest(email="someone@example.com", password="a" * 8, display_name="Someone")
    RegisterRequest(email="someone2@example.com", password="a" * 128, display_name="Someone")


def test_display_name_too_long_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        RegisterRequest(
            email="someone@example.com", password="a-strong-password", display_name="a" * 101
        )
    assert any(err["loc"] == ("display_name",) for err in exc_info.value.errors())


def test_display_name_whitespace_is_trimmed_and_collapsed() -> None:
    req = RegisterRequest(
        email="someone@example.com", password="a-strong-password", display_name="  Jane   Doe  "
    )
    assert req.display_name == "Jane Doe"


def test_display_name_empty_after_trim_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        RegisterRequest(
            email="someone@example.com", password="a-strong-password", display_name="   "
        )
    assert any(err["loc"] == ("display_name",) for err in exc_info.value.errors())
