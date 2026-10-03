"""Security primitives: password hashing, JWT access tokens, and opaque
refresh tokens.

Argon2 (via `argon2-cffi`) for passwords and PyJWT for access tokens —
no custom cryptography, per the Technical Design Document's Security
Architecture (Section 19) and Authentication Flow (Section 5). Uses each
library's own default, security-reviewed parameters rather than
hand-tuning them.

Scope note (S1C.1 — "Authentication Security & Token Primitives"): this
module builds the primitives login will use, not login itself. No
Session creation, no Redis, no `/auth/login` or `/auth/me` endpoint —
those are later milestones. Nothing here is wired into an API route yet.

Never log a password, a password hash, a refresh token, or a JWT — not
here, not at any call site.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import settings

# ---------------------------------------------------------------------------
# Passwords — Argon2. Hashing was implemented in S1B; verification arrives
# here with the first thing that actually needs it (login prep work).
# ---------------------------------------------------------------------------
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a plaintext password. The input is never stored, logged, or echoed."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Check a plaintext password against a stored Argon2 hash.

    Returns `False` for a wrong password or a malformed/foreign hash
    string alike — the caller never needs to know which, and no Argon2
    exception (which could end up in a stack trace or log) escapes this
    function.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


# ---------------------------------------------------------------------------
# JWT access tokens — short-lived, self-contained, verified on every
# request. Deliberately minimal claims: just enough to identify the
# subject and the token's own type/lifetime, per the Technical Design
# Document's Authentication Flow — no email, no profile data, nothing a
# leaked (e.g. logged, cached) token would expose beyond a user ID.
# ---------------------------------------------------------------------------
ACCESS_TOKEN_TYPE = "access"

_REQUIRED_ACCESS_CLAIMS = ["sub", "type", "iat", "exp"]


class InvalidTokenError(Exception):
    """Raised by `decode_access_token` for any token that isn't a
    currently-valid access token — malformed, expired, wrong signature,
    missing claims, or the wrong `type`.

    Deliberately not an `app.core.exceptions.AppException` subclass: it
    carries no HTTP status/error code of its own. A future auth
    dependency (S1C.2+) catches this and maps it to the API's 401
    envelope — that mapping decision belongs there, not here.
    """


def create_access_token(user_id: uuid.UUID | str) -> str:
    """Issue a new access token for `user_id`.

    Claims are exactly `sub` (the user ID, as a string), `type`
    (`"access"`, distinguishing this from any future token kind), `iat`,
    and `exp` — both UTC-aware, `exp` set `ACCESS_TOKEN_EXPIRE_MINUTES`
    from now (`app.config.settings`, never hardcoded here).
    """
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Verify and decode an access token, returning its claims.

    Verifies the signature (`settings.SECRET_KEY`/`JWT_ALGORITHM`),
    expiration, and the presence of every required claim — all via
    PyJWT's own checks, not hand-rolled. Also verifies `type == "access"`,
    which PyJWT has no built-in concept of. Any failure raises the one
    `InvalidTokenError` above; no PyJWT exception (whose message can
    include raw token content) ever reaches the caller.
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": _REQUIRED_ACCESS_CLAIMS},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError("Invalid or expired access token.") from exc

    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise InvalidTokenError("Token is not an access token.")

    return payload


# ---------------------------------------------------------------------------
# Refresh tokens — deliberately NOT JWTs. A refresh token is a bearer
# credential with no need to be self-describing; making it an opaque
# random value means a leaked database (`sessions.refresh_token_hash`)
# reveals nothing usable, and revocation is a plain row update rather
# than needing a denylist for otherwise-still-valid JWTs.
# ---------------------------------------------------------------------------
_REFRESH_TOKEN_BYTES = 32  # 256 bits of entropy — `secrets` uses a CSPRNG.


def create_refresh_token() -> str:
    """Generate a new opaque refresh token. Return it exactly once — the
    caller is responsible for returning it to the client and storing
    only its hash (see `hash_refresh_token`); this module never persists
    or logs it."""
    return secrets.token_urlsafe(_REFRESH_TOKEN_BYTES)


def hash_refresh_token(token: str) -> str:
    """Hash a refresh token for storage in `Session.refresh_token_hash`.

    SHA-256, not Argon2: a refresh token is already a high-entropy random
    value (unlike a user-chosen password), so there's nothing for
    Argon2's deliberately slow, memory-hard design to defend against
    here — and a session lookup needs to hash an incoming token and
    match it against a stored value by equality, which requires a
    deterministic hash. Argon2's own `hash()` salts every call, so equal
    inputs never produce equal outputs — unusable for this lookup.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_token_expires_at() -> datetime:
    """The `expires_at` value a newly created Session row should use —
    `REFRESH_TOKEN_EXPIRE_DAYS` from now, UTC-aware. Session creation
    itself is out of scope for this milestone; this only supplies the
    timestamp the later code will need."""
    return datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
