"""Authentication endpoints.

Sprint 1B: `POST /api/v1/auth/register`. S1C.2 added `POST
/api/v1/auth/login`. S1D added refresh, logout, and session management.
S1E adds email verification and password recovery. Every route here is
exactly the route, request/response shape, status code, and error
envelope already frozen in the REST API Contract (with specific,
individually-flagged gaps noted inline and in each sprint's report
where the frozen documents were silent) — never changing an existing
route's contract to add a new one.

Registration does not require the `Idempotency-Key` header to be
honored yet, despite the frozen contract marking it idempotency-
required: enforcing it needs the Redis-backed key store described in
the Technical Design Document (Section 30) — Redis exists starting S1D,
but that store is specifically the *idempotency-key* store, a different
piece of infrastructure than the refresh-token store S1D actually
builds. Still deferred; see docs/development/README.md. None of the
other routes here are marked idempotency-required in the contract.

**Cookie naming/attributes note (S1C.2, unchanged by S1D per its own
instruction not to change these without a demonstrated defect):** the
frozen contract specifies the *requirement* (httpOnly, Secure, SameSite,
short-lived access + rotating refresh) but not exact cookie names or a
specific SameSite value. `nexus_access_token`/`nexus_refresh_token`
(app.modules.auth.cookies) and `SameSite=lax` are this implementation's
choice, flagged the same way other gaps are: reasonable and minimal,
not a quoted contract value.
"""

import uuid

from fastapi import APIRouter, Depends, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.responses import SuccessEnvelope, envelope
from app.db.dependencies import get_db
from app.db.redis import get_redis
from app.modules.auth.cookies import ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE
from app.modules.auth.dependencies import get_current_user_id
from app.modules.auth.exceptions import TokenInvalidError
from app.modules.auth.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    SessionPublic,
    UserPublic,
    VerifyEmailRequest,
)
from app.modules.auth.service import (
    apply_password_reset,
    consume_email_verification_token,
    initiate_password_reset,
    list_sessions,
    login_user,
    logout_session,
    refresh_session,
    register_user,
    resend_email_verification,
    revoke_other_sessions,
    revoke_session,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# Cookies must not carry `Secure` on plain-HTTP local/development —
# browsers silently drop a `Secure` cookie sent over non-TLS, which
# would make login appear to "succeed" (200, user profile returned) but
# never actually authenticate anything on localhost. Same environment
# split already used for CORS origins (app/core/middleware.py), applied
# to the same problem here rather than a new one-off rule.
_COOKIES_SECURE = settings.APP_ENV not in ("local", "development")


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """Set both authentication cookies — shared by `/login` and
    `/refresh` so the two can never define these attributes differently."""
    response.set_cookie(
        ACCESS_TOKEN_COOKIE,
        access_token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=_COOKIES_SECURE,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        REFRESH_TOKEN_COOKIE,
        refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=_COOKIES_SECURE,
        samesite="lax",
        path="/",
    )


def _clear_auth_cookies(response: Response) -> None:
    """Clear both authentication cookies — `/logout` only. `path="/"`
    must match what `_set_auth_cookies` used, or the browser treats it
    as a different cookie and won't actually remove the original."""
    response.delete_cookie(ACCESS_TOKEN_COOKIE, path="/")
    response.delete_cookie(REFRESH_TOKEN_COOKIE, path="/")


@router.post(
    "/register",
    response_model=SuccessEnvelope[UserPublic],
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SuccessEnvelope[UserPublic]:
    user = await register_user(db, payload)
    return envelope(UserPublic.model_validate(user), request)


@router.post(
    "/login",
    response_model=SuccessEnvelope[UserPublic],
    status_code=status.HTTP_200_OK,
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> SuccessEnvelope[UserPublic]:
    # The direct TCP peer address only — no X-Forwarded-For parsing, no
    # proxy-trust policy. Session.ip_address (Sprint 1A) is NOT NULL
    # with no default, so *some* value is required to create the row at
    # all; this is the one value available with zero invented policy
    # (see login_user's docstring for the corresponding Session-field
    # notes).
    ip_address = request.client.host if request.client else "unknown"

    result = await login_user(db, redis, payload, ip_address)
    _set_auth_cookies(response, result.access_token, result.refresh_token)

    return envelope(UserPublic.model_validate(result.user), request)


@router.post(
    "/refresh",
    response_model=SuccessEnvelope[None],
    status_code=status.HTTP_200_OK,
)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> SuccessEnvelope[None]:
    """Rotate the access/refresh tokens carried by the request's cookies.

    **Flagged gap:** the frozen contract doesn't specify a response body
    shape for this route, only that tokens must not appear in it "unless
    explicitly required" — they aren't here either, so `data` is `null`
    rather than inventing a payload (e.g. re-returning the user profile,
    which nothing in the contract asks for).
    """
    raw_refresh_token = request.cookies.get(REFRESH_TOKEN_COOKIE)
    if raw_refresh_token is None:
        raise TokenInvalidError()

    result = await refresh_session(db, redis, raw_refresh_token)
    _set_auth_cookies(response, result.access_token, result.refresh_token)

    return envelope(None, request)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> None:
    raw_refresh_token = request.cookies.get(REFRESH_TOKEN_COOKIE)
    await logout_session(db, redis, current_user_id, raw_refresh_token)
    _clear_auth_cookies(response)


@router.get(
    "/sessions",
    response_model=SuccessEnvelope[list[SessionPublic]],
    status_code=status.HTTP_200_OK,
)
async def get_sessions(
    request: Request,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> SuccessEnvelope[list[SessionPublic]]:
    sessions = await list_sessions(db, current_user_id)
    return envelope([SessionPublic.model_validate(s) for s in sessions], request)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> None:
    await revoke_session(db, redis, current_user_id, session_id)


@router.delete("/sessions", status_code=status.HTTP_204_NO_CONTENT)
async def delete_other_sessions(
    request: Request,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> None:
    raw_refresh_token = request.cookies.get(REFRESH_TOKEN_COOKIE)
    await revoke_other_sessions(db, redis, current_user_id, raw_refresh_token)


@router.post(
    "/verify-email",
    response_model=SuccessEnvelope[None],
    status_code=status.HTTP_200_OK,
)
async def verify_email(
    payload: VerifyEmailRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> SuccessEnvelope[None]:
    """**Flagged gap:** the frozen contract doesn't specify a response
    body shape for this route — `data` is `null` (the smallest
    consistent envelope), not an invented user/token payload."""
    await consume_email_verification_token(db, redis, payload.token)
    return envelope(None, request)


@router.post(
    "/resend-verification",
    response_model=SuccessEnvelope[None],
    status_code=status.HTTP_202_ACCEPTED,
)
async def resend_verification(
    payload: ResendVerificationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> SuccessEnvelope[None]:
    """Always 202 regardless of whether `email` exists, is already
    active, or is pending — see `resend_email_verification`'s docstring
    for the anti-enumeration reasoning (a flagged inference, not a
    quoted contract requirement for this specific endpoint)."""
    await resend_email_verification(db, redis, payload.email)
    return envelope(None, request)


@router.post(
    "/forgot-password",
    response_model=SuccessEnvelope[None],
    status_code=status.HTTP_202_ACCEPTED,
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> SuccessEnvelope[None]:
    """Always 202 regardless of whether `email` corresponds to an
    account — the frozen anti-enumeration requirement, applied exactly
    as specified."""
    await initiate_password_reset(db, redis, payload.email)
    return envelope(None, request)


@router.post(
    "/reset-password",
    response_model=SuccessEnvelope[None],
    status_code=status.HTTP_200_OK,
)
async def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> SuccessEnvelope[None]:
    """No cookies are touched here — this request is unauthenticated
    (`Auth: No`) and carries none of its own; every *other* session this
    user holds is revoked server-side by `apply_password_reset`, but
    there is no "current" session/cookie on this particular request to
    clear."""
    await apply_password_reset(db, redis, payload.token, payload.new_password)
    return envelope(None, request)
