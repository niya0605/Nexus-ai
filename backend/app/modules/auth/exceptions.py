"""Auth module domain exceptions.

Sprint 1B added registration's one exception. S1C.2 (login) added two
more. S1D (refresh/sessions) added token and authorization errors —
`TokenExpiredError`/`TokenInvalidError` were written for the refresh
flow but are generic `token_expired`/`token_invalid` *codes*, not
refresh-specific ones, so S1E (email verification / password reset)
reuses them as-is for its own tokens rather than adding near-duplicate
classes — exactly what "use the existing exception/error-envelope
architecture, do not create arbitrary new error codes" calls for.
"""

from fastapi import status

from app.core.exceptions import AppException


class EmailAlreadyRegisteredError(AppException):
    """Raised when the normalized email already belongs to an existing user.

    Maps to the REST API Contract's Authentication Endpoints error
    catalog entry: 409, `email_already_registered`.
    """

    status_code = status.HTTP_409_CONFLICT
    error_code = "email_already_registered"

    def __init__(self) -> None:
        super().__init__("An account with this email already exists.")


class InvalidCredentialsError(AppException):
    """Raised for login failure — wrong password, or no user with that
    email at all. Deliberately the *same* exception for both cases (see
    `login_user`): the frozen contract requires the two to be
    indistinguishable, so there is intentionally no separate
    "no such user" exception to accidentally raise instead.

    Maps to the REST API Contract's Authentication Endpoints error
    catalog entry: 401, `invalid_credentials`.

    Also used for a `deactivated` account (see `login_user`'s docstring)
    — the frozen contract defines no dedicated error code for that case,
    and this is the closest existing one rather than an invented new
    code. Flagged as a contract gap, not a silent assumption.
    """

    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "invalid_credentials"

    def __init__(self) -> None:
        super().__init__("The email or password you entered is incorrect.")


class EmailNotVerifiedError(AppException):
    """Raised when login credentials are correct but the account is still
    `pending_verification`.

    Maps to the REST API Contract's Authentication Endpoints error
    catalog entry: 403, `email_not_verified`. The contract excerpt this
    was built from specifies the code but not an exact message string —
    unlike `InvalidCredentialsError`'s verbatim-specified text, this
    message is a reasonable choice, not a quoted contract value.
    """

    status_code = status.HTTP_403_FORBIDDEN
    error_code = "email_not_verified"

    def __init__(self) -> None:
        super().__init__("Please verify your email address before logging in.")


class TokenExpiredError(AppException):
    """Raised whenever a presented single-use token was found but its
    validity window has passed — `refresh_session`'s refresh token
    (S1D), and (S1E) `consume_email_verification_token`'s and
    `apply_password_reset`'s tokens via `app.modules.auth.token_store`.

    Maps to the REST API Contract's frozen error codes: 400,
    `token_expired` — distinct from `TokenInvalidError` because the
    frozen contract requires the two to be distinguishable (unlike
    login's deliberately-indistinguishable `invalid_credentials`).
    """

    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "token_expired"

    def __init__(self) -> None:
        super().__init__("This token has expired.")


class TokenInvalidError(AppException):
    """Raised whenever a presented single-use token isn't currently
    valid for any reason *other* than "found but expired" — missing,
    malformed, never issued, already consumed, or replaced by a newer
    one (see `app.modules.auth.token_store`, and `refresh_session`'s own
    docstring on the unresolved refresh-token-reuse-detection-response
    gap). Shared by `refresh_session` (S1D) and the S1E email-
    verification/password-reset flows alike — same code, same meaning,
    different token kind.

    Maps to the REST API Contract's frozen error codes: 400,
    `token_invalid`.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "token_invalid"

    def __init__(self) -> None:
        super().__init__("This token is invalid.")


class AuthenticationRequiredError(AppException):
    """Raised by the access-token auth dependency (`get_current_user_id`)
    for a missing, malformed, expired, or wrong-type access token on an
    endpoint the frozen contract marks `Auth: Yes`.

    **Flagged contract gap:** the S1D contract excerpt defines
    `token_expired`/`token_invalid` only for `/refresh`'s *refresh*
    token, explicitly under a "REFRESH ERRORS" heading — it does not
    define an error code for a missing/invalid *access* token on
    `/logout` or the `/sessions` endpoints. Rather than inventing a new
    code, this reuses `unauthorized` — already a recognized entry in
    `app/core/exceptions.py`'s generic `_STATUS_CODES` table (used for
    framework-level 401s) — for the same 401 case raised deliberately
    for a business reason instead of by the framework.
    """

    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "unauthorized"

    def __init__(self) -> None:
        super().__init__("Authentication is required to access this resource.")


class PasswordTooWeakError(AppException):
    """Raised by `apply_password_reset` when `new_password` fails the
    existing length policy (`app.core.validation.validate_password` —
    8-128 chars, no composition rules, per NIST 800-63B; reused as-is,
    not reimplemented).

    Maps to the error code S1E's own instructions name directly:
    422 `password_too_weak` — a *different* code from register's
    generic Pydantic-driven `validation_error` for the same underlying
    rule, because S1E explicitly calls out `password_too_weak` as a
    known code to use "where applicable". Checked before the reset
    token is even looked up (see `apply_password_reset`'s docstring),
    so a weak-password attempt never burns a token the user could
    still use once they submit a valid one.
    """

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "password_too_weak"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class SessionNotFoundError(AppException):
    """Raised by `revoke_session` when the given `session_id` doesn't
    exist, or exists but belongs to a different user.

    **Flagged contract gap:** the S1D contract says to "follow the
    existing authorization/not-found behavior" without stating which of
    the two. Deliberately reuses the generic `not_found` (404) —
    already a recognized `_STATUS_CODES` entry — for *both* cases rather
    than a distinguishing `forbidden` (403), matching the common
    security convention of not confirming a resource's existence to a
    caller who doesn't own it. No new error code invented either way.
    """

    status_code = status.HTTP_404_NOT_FOUND
    error_code = "not_found"

    def __init__(self) -> None:
        super().__init__("Session not found.")
