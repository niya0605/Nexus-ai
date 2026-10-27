"""Auth module service layer.

Sprint 1B added registration. S1C.2 added login. S1D added refresh-token
rotation, logout, and session management — Redis (`app.db.redis`,
`app.modules.auth.refresh_store`) is required starting there. S1E adds
email verification and password recovery, reusing that same Redis
architecture for its own tokens (`app.modules.auth.token_store`) and
S1D's session-revocation machinery (password reset revokes every active
Session). Every function still owns its own transaction boundary
exactly the same way registration does, per the Technical Design
Document's Transaction Management strategy (Section 18):
app/db/dependencies.py's `get_db` only yields a session and never
commits. No repository layer for Postgres yet — see
app/utils/db_enum.py sibling modules onward as that changes; Redis
access is already isolated behind `app.modules.auth.refresh_store`/
`app.modules.auth.token_store`, never called directly from a route, and
SMTP is isolated behind `app.core.mailer`/`app.modules.auth.mail`, never
called directly from this module.

`/auth/me`, RBAC, and workspace authorization are still out of scope —
see the Technical Design Document, Authentication Flow (Section 5), for
the full flow this and S1B/S1C.2/S1D/S1E are pieces of.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import NamedTuple

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_token_expires_at,
    verify_password,
)
from app.core.validation import validate_password
from app.modules.auth import mail, refresh_store, token_store
from app.modules.auth.exceptions import (
    EmailAlreadyRegisteredError,
    EmailNotVerifiedError,
    InvalidCredentialsError,
    PasswordTooWeakError,
    SessionNotFoundError,
    TokenExpiredError,
    TokenInvalidError,
)
from app.modules.auth.models import Session, SessionStatus, User, UserStatus
from app.modules.auth.schemas import LoginRequest, RegisterRequest

logger = logging.getLogger(__name__)

# The specific constraint whose violation means "duplicate email" — see
# alembic/versions/20260809_create_authentication_tables.py. Checked
# against IntegrityError.orig so a *different* constraint violation on
# this insert (were one ever added) surfaces as a real 500, not a
# misleading "email already registered".
_DUPLICATE_EMAIL_CONSTRAINT = "uq_users_email_lower"


async def register_user(session: AsyncSession, payload: RegisterRequest) -> User:
    """Create a new User in its initial `pending_verification` state.

    Does not log in, does not send a verification email, does not touch
    Redis — creates exactly one row and returns it. `payload.email` and
    `payload.display_name` arrive already normalized (Pydantic field
    validators run before this function is ever called); only the
    password is transformed here, into its Argon2 hash — never stored,
    logged, or returned in any other form.
    """
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        # avatar_url, status, email_verified_at, failed_login_count,
        # last_login_at, deactivated_at: left unset — the model's own
        # defaults (Sprint 1A) supply every initial value the frozen
        # Data Dictionary specifies.
    )

    if settings.AUTO_VERIFY_EMAILS:
        user.status = UserStatus.ACTIVE
        user.email_verified_at = datetime.now(UTC)

    session.add(user)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if _DUPLICATE_EMAIL_CONSTRAINT in str(exc.orig):
            raise EmailAlreadyRegisteredError() from exc
        raise

    await session.refresh(user)
    logger.info(f"User registered: {user.id}")  # never the email or any credential
    return user


class LoginResult(NamedTuple):
    """What a successful `login_user` call hands back to the endpoint.

    Not a Pydantic schema — never serialized directly. The endpoint
    reads `access_token`/`refresh_token` to set cookies and never puts
    either into the JSON response body (the frozen contract returns only
    the user profile there); this tuple is purely an internal handoff.
    """

    user: User
    access_token: str
    refresh_token: str


async def login_user(
    session: AsyncSession, redis: Redis, payload: LoginRequest, ip_address: str
) -> LoginResult:
    """Authenticate a user and, on success, create a new Session.

    **S1D note:** gained the `redis` parameter here — `/login`'s own
    frozen HTTP contract (request, response, status code, cookies) is
    completely unchanged; this is purely the internal wiring so the
    Session this function creates has a matching Redis refresh-token
    record from the moment it exists, which `refresh_session` (S1D)
    requires. Without this, every freshly logged-in session's first
    `/refresh` call would fail with `token_invalid`, since nothing
    would ever have populated Redis for it.

    `payload.email` arrives already normalized (Pydantic field validator
    runs before this is called); `payload.password` arrives exactly as
    submitted — never trimmed or otherwise altered, per the frozen
    contract.

    Failure handling, per the frozen REST API Contract's Authentication
    Endpoints:

    - No user with that email, or the wrong password: both raise the
      *same* `InvalidCredentialsError` (401) — the contract requires
      these to be indistinguishable, so a wrong password must never
      raise a different exception than "no such user" would. A wrong
      password additionally increments `failed_login_count`, committed
      immediately (this is the only DB write on this path — no Session,
      no tokens).
    - `pending_verification` (correct credentials, unverified account):
      `EmailNotVerifiedError` (403). No `failed_login_count` change —
      the credentials were correct; this is a status gate, not a failed
      authentication attempt.
    - `deactivated`: the frozen contract defines no dedicated error code
      for this case, and this function deliberately does not invent
      one — it raises the same `InvalidCredentialsError` a wrong
      password would. **This is a known contract gap, not a confirmed
      behavior** — see this module's docstring note in
      `app/modules/auth/exceptions.py` and the sprint report. No
      `failed_login_count` change here either, for the same reason as
      `pending_verification`.

    On success: `failed_login_count` resets to 0, `last_login_at` is set
    to now (UTC), an access token and a new opaque refresh token are
    issued (`app.core.security`), and a new active `Session` row is
    created storing only the refresh token's hash — the raw token is
    returned exactly once, in this function's return value, never
    logged, and the caller (the endpoint) is responsible for putting it
    only in a cookie, never in the JSON body. The user-metadata update
    and the Session insert are committed together, atomically, per the
    Technical Design Document's Transaction Management strategy.
    """
    normalized_email = payload.email
    # `func.lower(User.email)`, not `User.email ==`, to actually use the
    # `uq_users_email_lower` functional index (the only index on this
    # column — see app/modules/auth/models.py) rather than a full table
    # scan, and as defense-in-depth if a row's stored casing were ever
    # inconsistent with today's normalize_email behavior.
    user = (
        await session.execute(select(User).where(func.lower(User.email) == normalized_email))
    ).scalar_one_or_none()

    if user is None:
        raise InvalidCredentialsError()

    if not verify_password(payload.password, user.password_hash):
        user.failed_login_count += 1
        await session.commit()
        raise InvalidCredentialsError()

    if user.status == UserStatus.PENDING_VERIFICATION:
        raise EmailNotVerifiedError()

    if user.status == UserStatus.DEACTIVATED:
        # See this function's docstring: reusing InvalidCredentialsError
        # is a deliberate, flagged gap-fill, not an assumption that this
        # is definitely the intended contract behavior.
        raise InvalidCredentialsError()

    access_token = create_access_token(user.id)
    raw_refresh_token = create_refresh_token()
    refresh_hash = hash_refresh_token(raw_refresh_token)
    expires_at = refresh_token_expires_at()

    user.failed_login_count = 0
    user.last_login_at = datetime.now(UTC)
    new_session = Session(
        user_id=user.id,
        refresh_token_hash=refresh_hash,
        ip_address=ip_address,
        expires_at=expires_at,
        # status, device_label: left unset — ACTIVE and None are the
        # model's own defaults (Sprint 1A); the frozen contract this
        # milestone was built from says nothing about deriving a
        # device label, so none is invented (see Session model's
        # own default rather than a made-up value here).
    )
    session.add(new_session)

    try:
        await session.commit()
    except IntegrityError:
        # Session.refresh_token_hash is unique — a collision is
        # astronomically unlikely (SHA-256 of a 256-bit random value)
        # but not impossible to model for. Same pattern as
        # register_user: roll back and let this surface as a genuine
        # 500 (app/core/exceptions.py's unhandled-exception handler),
        # never a misleading success or a silently swallowed error.
        await session.rollback()
        raise

    await session.refresh(user)

    # Redis populated only after the Postgres commit succeeds, same
    # ordering rationale as refresh_session's rotation: never hand back
    # tokens whose server-side state didn't fully persist first.
    ttl_seconds = int((expires_at - datetime.now(UTC)).total_seconds())
    await refresh_store.store(redis, refresh_hash, str(new_session.id), ttl_seconds)

    logger.info(f"User logged in: {user.id}")  # never the email or any credential
    return LoginResult(user=user, access_token=access_token, refresh_token=raw_refresh_token)


class RefreshResult(NamedTuple):
    """What a successful `refresh_session` call hands back to the
    endpoint — new tokens only. Per the frozen contract, the response
    body itself carries neither (see this function's docstring)."""

    access_token: str
    refresh_token: str


async def refresh_session(
    session: AsyncSession, redis: Redis, raw_refresh_token: str
) -> RefreshResult:
    """Validate a presented refresh token and, on success, rotate it.

    Two layers are checked, per the frozen Technical Design Document's
    conceptual flow — Redis first (the fast, TTL-backed "is this
    specific token currently valid" answer), then the relational
    `Session` row (authoritative for the `token_expired`/`token_invalid`
    distinction the frozen contract requires, which Redis alone can't
    make: a missing Redis key looks the same whether it TTL'd out or was
    explicitly deleted on rotation).

    A token that was already rotated away no longer matches any
    `Session.refresh_token_hash` (rotation updates that column in
    place — see below), so presenting it again naturally raises
    `TokenInvalidError` the same way a garbage token would. **This is
    the one behavior implemented for "reuse of an already-rotated
    refresh token" — flagged per S1D's own instruction**: the frozen
    documents given don't specify any *additional* response (e.g.
    revoking every session for that user, alerting), so none is
    invented here.

    On success: a new access token and a new opaque refresh token are
    issued; the *same* Session row is updated in place (`refresh_token_hash`,
    `expires_at`) rather than a new row being created — refresh extends
    an existing session, it doesn't start a new one (only `login_user`
    creates Session rows). The Postgres update commits first; the Redis
    rotation (delete old key, set new key, one pipelined round trip —
    see `refresh_store.rotate`) happens only after that commit succeeds
    and is *not* swallowed on failure, so a Redis error here surfaces as
    a genuine 500 rather than a 200 whose tokens were only half-persisted.
    """
    old_hash = hash_refresh_token(raw_refresh_token)

    redis_session_id = await refresh_store.get_session_id(redis, old_hash)
    if redis_session_id is None:
        raise TokenInvalidError()

    db_session = (
        await session.execute(select(Session).where(Session.refresh_token_hash == old_hash))
    ).scalar_one_or_none()

    if (
        db_session is None
        or db_session.status != SessionStatus.ACTIVE
        or str(db_session.id) != redis_session_id
    ):
        # Redis says valid but Postgres disagrees (gone, revoked, or —
        # should be unreachable if the two are kept in sync — pointing
        # at a different session entirely). Clean up the stray Redis
        # record and treat the token as invalid either way.
        await refresh_store.invalidate(redis, old_hash)
        raise TokenInvalidError()

    if db_session.expires_at <= datetime.now(UTC):
        raise TokenExpiredError()

    access_token = create_access_token(db_session.user_id)
    new_raw_refresh_token = create_refresh_token()
    new_hash = hash_refresh_token(new_raw_refresh_token)
    new_expires_at = refresh_token_expires_at()

    db_session.refresh_token_hash = new_hash
    db_session.expires_at = new_expires_at

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise

    ttl_seconds = int((new_expires_at - datetime.now(UTC)).total_seconds())
    await refresh_store.rotate(
        redis,
        old_hash=old_hash,
        new_hash=new_hash,
        session_id=str(db_session.id),
        ttl_seconds=ttl_seconds,
    )

    logger.info(f"Session refreshed: {db_session.id}")  # never the token or its hash
    return RefreshResult(access_token=access_token, refresh_token=new_raw_refresh_token)


async def _find_session_by_raw_token(
    session: AsyncSession, user_id: uuid.UUID, raw_refresh_token: str | None
) -> Session | None:
    """Resolve "the current session" from a raw refresh-token cookie
    value — the same hash-based identification `refresh_session` uses,
    so the identifier stays consistent across the authentication
    cookie, the Redis record, and the Session row (per S1D's own
    instruction not to invent a second, unrelated mechanism for this).
    Scoped to `user_id` so a cookie can never resolve to someone else's
    session. Returns `None` (never raises) for a missing/foreign/stale
    cookie — every caller treats "no current session identifiable" as
    its own well-defined case, not an error.
    """
    if raw_refresh_token is None:
        return None
    token_hash = hash_refresh_token(raw_refresh_token)
    return (
        await session.execute(
            select(Session).where(
                Session.refresh_token_hash == token_hash, Session.user_id == user_id
            )
        )
    ).scalar_one_or_none()


async def logout_session(
    session: AsyncSession, redis: Redis, user_id: uuid.UUID, raw_refresh_token: str | None
) -> None:
    """Revoke the current session — the frozen contract's "Revoke
    current session", identified via the refresh-token cookie (see
    `_find_session_by_raw_token`).

    Per the frozen Technical Design Document: only the Redis refresh-
    token record is deleted and the Session row marked revoked — the
    access JWT itself is never server-side revoked (no blacklist is
    introduced; the existing ~15-minute access-token lifetime is the
    accepted blast radius). A missing/foreign/already-revoked cookie is
    a silent no-op success, not an error — logout should never fail
    visibly just because there was nothing left to revoke.
    """
    db_session = await _find_session_by_raw_token(session, user_id, raw_refresh_token)
    if db_session is None or db_session.status != SessionStatus.ACTIVE:
        return

    token_hash = db_session.refresh_token_hash
    db_session.status = SessionStatus.REVOKED
    db_session.revoked_at = datetime.now(UTC)
    await session.commit()

    await refresh_store.invalidate(redis, token_hash)
    logger.info(f"Session logged out: {db_session.id}")


async def list_sessions(session: AsyncSession, user_id: uuid.UUID) -> list[Session]:
    """The frozen contract's "List own active sessions" — explicitly
    active only, most recent first, scoped to `user_id` (never another
    user's rows)."""
    rows = (
        await session.execute(
            select(Session)
            .where(Session.user_id == user_id, Session.status == SessionStatus.ACTIVE)
            .order_by(Session.created_at.desc())
        )
    ).scalars()
    return list(rows.all())


async def revoke_session(
    session: AsyncSession, redis: Redis, user_id: uuid.UUID, session_id: uuid.UUID
) -> None:
    """Revoke one specific session by ID — only if it belongs to
    `user_id`. A session that doesn't exist *or* belongs to someone else
    both raise the same `SessionNotFoundError` (see that exception's
    docstring for why). Revoking an already-revoked session is a
    no-op success, not an error — DELETE is idempotent.
    """
    db_session = (
        await session.execute(
            select(Session).where(Session.id == session_id, Session.user_id == user_id)
        )
    ).scalar_one_or_none()

    if db_session is None:
        raise SessionNotFoundError()

    if db_session.status != SessionStatus.ACTIVE:
        return

    token_hash = db_session.refresh_token_hash
    db_session.status = SessionStatus.REVOKED
    db_session.revoked_at = datetime.now(UTC)
    await session.commit()

    await refresh_store.invalidate(redis, token_hash)
    logger.info(f"Session revoked: {db_session.id}")


async def revoke_other_sessions(
    session: AsyncSession, redis: Redis, user_id: uuid.UUID, raw_current_refresh_token: str | None
) -> None:
    """Revoke every one of `user_id`'s active sessions except the
    current one (identified the same way logout identifies it — see
    `_find_session_by_raw_token`). If no current session can be
    identified (missing/foreign cookie), there is nothing to exclude,
    so every active session is revoked — still never touching another
    user's rows.
    """
    current = await _find_session_by_raw_token(session, user_id, raw_current_refresh_token)

    conditions = [Session.user_id == user_id, Session.status == SessionStatus.ACTIVE]
    if current is not None:
        conditions.append(Session.id != current.id)

    rows = (await session.execute(select(Session).where(*conditions))).scalars().all()
    if not rows:
        return

    token_hashes = [row.refresh_token_hash for row in rows]
    now = datetime.now(UTC)
    for row in rows:
        row.status = SessionStatus.REVOKED
        row.revoked_at = now

    await session.commit()

    for token_hash in token_hashes:
        await refresh_store.invalidate(redis, token_hash)
    logger.info(f"Revoked {len(rows)} other session(s) for user: {user_id}")


# ---------------------------------------------------------------------------
# S1E — email verification
# ---------------------------------------------------------------------------


async def _issue_and_send_verification_email(redis: Redis, user: User) -> None:
    """Generate a new verification token and email it — the one place
    that pairing happens, used by both `resend_email_verification` and
    (were it ever wired into registration — see this function's own
    caller for why it currently isn't) any future first-send path.

    A send failure is logged (never the token) and swallowed, never
    raised: the token is already durably stored in Redis by this point,
    so "the business fact must not be lost simply because an email
    delivery attempt fails" already holds regardless of what SMTP does
    next. See the sprint report for why this — not a formal Outbox
    table plus a background worker — is this milestone's deliberately
    minimal implementation of that requirement (no Outbox/Celery
    infrastructure exists anywhere in this repository yet to build on).
    """
    ttl_seconds = settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS * 3600
    raw_token = await token_store.issue_verification_token(redis, user.id, ttl_seconds)
    try:
        await mail.send_verification_email(to=user.email, raw_token=raw_token)
    except Exception:  # noqa: BLE001 — deliberately broad, see this function's docstring
        logger.warning(f"Failed to send verification email for user: {user.id}")  # never the token


async def consume_email_verification_token(
    session: AsyncSession, redis: Redis, raw_token: str
) -> User:
    """`POST /verify-email` — the frozen `pending_verification → active`
    transition.

    `token_store.consume_verification_token` already enforces single-use
    (deleted on lookup, regardless of outcome) and raises
    `TokenExpiredError`/`TokenInvalidError` as appropriate; this function
    only handles what happens once a *currently valid* token resolves to
    a user.
    """
    user_id = await token_store.consume_verification_token(redis, raw_token)

    user = await session.get(User, user_id)
    # The token was valid a moment ago, but the account it names might
    # no longer be in a state verification should apply to (deleted
    # since — not possible today, no delete endpoint exists, but not
    # assumed away either; or deactivated). Both collapse to the same
    # `token_invalid` a garbage token would produce, not a new code.
    if user is None or user.status != UserStatus.PENDING_VERIFICATION:
        raise TokenInvalidError()

    user.status = UserStatus.ACTIVE
    user.email_verified_at = datetime.now(UTC)
    await session.commit()

    logger.info(f"Email verified: {user.id}")  # never the token or the email
    return user


async def resend_email_verification(session: AsyncSession, redis: Redis, email: str) -> None:
    """`POST /resend-verification`.

    **Flagged inference, not a confirmed contract quote:** the frozen
    documents available for this were silent on anti-enumeration for
    *this specific* endpoint (only `forgot-password`'s was explicit).
    This applies the identical policy anyway — always succeed (202) with
    an identical response regardless of which of the three states below
    actually applied — since resend-verification is the same shape of
    attack surface as forgot-password (a public endpoint that emails a
    claimed address), and the instructions explicitly required that
    policy for the sibling endpoint.

    - Nonexistent email: no-op.
    - Already `active`: no-op (nothing to verify).
    - `pending_verification`: a new token replaces any previous one for
      this user (`token_store.issue_verification_token`'s own
      invalidate-previous behavior) and is emailed.
    - `deactivated`: no-op — verifying a deactivated account's email
      wouldn't reactivate it (only `login`'s `deactivated` gap and this
      one share that a deactivated account gets no special-cased
      response anywhere in this API).
    """
    user = (
        await session.execute(select(User).where(func.lower(User.email) == email))
    ).scalar_one_or_none()

    if user is not None and user.status == UserStatus.PENDING_VERIFICATION:
        await _issue_and_send_verification_email(redis, user)


# ---------------------------------------------------------------------------
# S1E — password recovery
# ---------------------------------------------------------------------------


async def initiate_password_reset(session: AsyncSession, redis: Redis, email: str) -> None:
    """`POST /forgot-password`.

    Anti-enumeration per the frozen contract: always succeeds (202)
    with an identical response whether or not `email` belongs to an
    account. A reset token is generated and emailed only when it
    genuinely does — and only for `pending_verification`/`active`
    accounts; a `deactivated` one gets no token, the same "no special
    response, just silently no-op" treatment as everywhere else in this
    API a deactivated account is reached through a public endpoint.
    """
    user = (
        await session.execute(select(User).where(func.lower(User.email) == email))
    ).scalar_one_or_none()

    if user is not None and user.status != UserStatus.DEACTIVATED:
        ttl_seconds = settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES * 60
        raw_token = await token_store.issue_reset_token(redis, user.id, ttl_seconds)
        try:
            await mail.send_password_reset_email(to=user.email, raw_token=raw_token)
        except Exception:  # noqa: BLE001 — deliberately broad, see initiate_password_reset's docstring
            logger.warning(
                f"Failed to send password reset email for user: {user.id}"
            )  # never the token


async def apply_password_reset(
    session: AsyncSession, redis: Redis, raw_token: str, new_password: str
) -> None:
    """`POST /reset-password`.

    Password strength is checked *before* the token is even looked up
    — a `password_too_weak` response must never consume a token the
    user could still use once they resubmit with a valid password (see
    `PasswordTooWeakError`'s docstring). Consistent with how every other
    endpoint in this codebase validates request shape before any
    business logic runs at all (Pydantic field validators, which this
    can't be — see `ResetPasswordRequest`'s own docstring for why).

    On success: the new password is hashed and stored, and — the one
    piece of this flow the frozen contract is explicit and emphatic
    about — *every* active Session for this user is revoked, Postgres
    first (one atomic commit alongside the password change), Redis
    cleanup after, matching the exact ordering `revoke_session`/
    `revoke_other_sessions` (S1D) already established. No access-token
    blacklist is introduced — same accepted ~15-minute blast radius as
    logout.
    """
    try:
        validate_password(new_password)
    except ValueError as exc:
        raise PasswordTooWeakError(str(exc)) from exc

    user_id = await token_store.consume_reset_token(redis, raw_token)

    user = await session.get(User, user_id)
    if user is None or user.status == UserStatus.DEACTIVATED:
        raise TokenInvalidError()

    user.password_hash = hash_password(new_password)

    sessions = (
        (
            await session.execute(
                select(Session).where(
                    Session.user_id == user.id, Session.status == SessionStatus.ACTIVE
                )
            )
        )
        .scalars()
        .all()
    )
    token_hashes = [row.refresh_token_hash for row in sessions]
    now = datetime.now(UTC)
    for row in sessions:
        row.status = SessionStatus.REVOKED
        row.revoked_at = now

    await session.commit()

    for token_hash in token_hashes:
        await refresh_store.invalidate(redis, token_hash)

    logger.info(
        f"Password reset: {user.id} ({len(sessions)} session(s) revoked)"
    )  # never the password
