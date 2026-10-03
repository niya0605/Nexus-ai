"""Request/response schemas for the auth module.

Sprint 1B: registration only. Field-level validation reuses the
centralized normalizers in app/core/validation.py (per the frozen Data
Dictionary's Shared Validation Standards, Section 15) rather than
reimplementing the rules here — a future module needing the same
email/display-name rules imports the same functions.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.core.validation import normalize_display_name, normalize_email, validate_password
from app.modules.auth.models import SessionStatus, UserStatus


class RegisterRequest(BaseModel):
    """POST /api/v1/auth/register request body."""

    email: EmailStr
    password: str
    display_name: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("password")
    @classmethod
    def _validate_password(cls, value: str) -> str:
        return validate_password(value)

    @field_validator("display_name")
    @classmethod
    def _normalize_display_name(cls, value: str) -> str:
        return normalize_display_name(value)


class LoginRequest(BaseModel):
    """POST /api/v1/auth/login request body.

    Per the frozen REST API Contract: the email is normalized exactly as
    registration does (trim, lowercase), but the password is passed
    through completely unmodified — no trim, no case change, no length
    validation. Login verifies a password against whatever hash was
    produced at registration time; rejecting on today's composition
    rules here would be both wrong (an old password may not satisfy a
    rule added later) and a distinguishing signal the contract's
    indistinguishable-failure requirement doesn't allow.
    """

    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return normalize_email(value)


class VerifyEmailRequest(BaseModel):
    """POST /api/v1/auth/verify-email request body — field name (`token`)
    frozen exactly as given."""

    token: str


class ResendVerificationRequest(BaseModel):
    """POST /api/v1/auth/resend-verification request body.

    **IMPLEMENTATION CHOICE, not a frozen field name:** the contract
    excerpt this was built from didn't specify this endpoint's request
    shape — `email` is used because every other request in this module
    that identifies an account by email (`RegisterRequest`,
    `LoginRequest`) already uses that exact field name; this is the
    established convention repeated, not a new name invented from
    nothing.
    """

    email: EmailStr

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return normalize_email(value)


class ForgotPasswordRequest(BaseModel):
    """POST /api/v1/auth/forgot-password request body — same
    `email`-field convention/reasoning as `ResendVerificationRequest`."""

    email: EmailStr

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return normalize_email(value)


class ResetPasswordRequest(BaseModel):
    """POST /api/v1/auth/reset-password request body — field names
    (`token`, `new_password`) frozen exactly as given.

    `new_password` deliberately has no Pydantic-level length validator
    (unlike `RegisterRequest.password`'s `validate_password`): S1E names
    a *dedicated* `password_too_weak` error code distinct from the
    generic Pydantic-driven `validation_error` register uses for the
    same underlying rule, so this check happens in the service layer
    (`apply_password_reset`) instead, where it can raise that specific
    exception.
    """

    token: str
    new_password: str


class UserPublic(BaseModel):
    """The public-safe projection of a User — never includes `password_hash`
    (Restricted, per the Data Dictionary's Sensitivity Classification) or
    any other internal-only field."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    avatar_url: str | None
    status: UserStatus
    created_at: datetime


class SessionPublic(BaseModel):
    """One entry in GET /api/v1/auth/sessions's list.

    The frozen contract's exposed fields exactly: `device_label`,
    `ip_address`, `created_at`, `status`. `id` is also included — not
    explicitly named in the contract excerpt this was built from, but
    included because `DELETE /api/v1/auth/sessions/{session_id}` (also
    S1D, also frozen) is unusable unless the client can learn a
    session's ID somewhere; this is a flagged inference, not a quoted
    contract field. Never `refresh_token_hash` — Restricted, per the
    Data Dictionary, and not part of this schema at all (not merely
    excluded at serialization time).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_label: str | None
    ip_address: str
    created_at: datetime
    status: SessionStatus
