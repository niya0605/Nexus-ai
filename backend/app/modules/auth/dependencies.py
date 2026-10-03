"""FastAPI dependency for resolving the authenticated user from the
access-token cookie.

Not `/auth/me` (explicitly out of scope through S1D) — this is the
underlying auth *gate* several S1D endpoints need (`Auth: Yes` in the
frozen contract: logout, the `/sessions` endpoints), pulled out as its
own dependency because it's required infrastructure for those routes
regardless of whether a dedicated "who am I" endpoint exists yet.
`/refresh` deliberately does NOT use this — its own contract entry says
`Auth: refresh token`, not this access-token gate (and a client
refreshing is often doing so *because* its access token already
expired).
"""

import uuid

from fastapi import Request

from app.core.security import InvalidTokenError, decode_access_token
from app.modules.auth.cookies import ACCESS_TOKEN_COOKIE
from app.modules.auth.exceptions import AuthenticationRequiredError


async def get_current_user_id(request: Request) -> uuid.UUID:
    """Resolve the authenticated user's ID from the access-token cookie.

    Deliberately returns only the ID, not a fetched `User` row — every
    S1D use of this dependency only needs it to scope a query
    (`WHERE user_id = ...`); fetching a full profile nobody asked for
    is exactly the kind of thing a real `/auth/me` endpoint should own,
    not this dependency.

    See `AuthenticationRequiredError`'s docstring for why a missing,
    malformed, expired, or wrong-type access token all map to the same
    401 here.
    """
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if token is None:
        raise AuthenticationRequiredError()

    try:
        claims = decode_access_token(token)
    except InvalidTokenError as exc:
        raise AuthenticationRequiredError() from exc

    try:
        return uuid.UUID(claims["sub"])
    except (KeyError, ValueError, TypeError) as exc:
        raise AuthenticationRequiredError() from exc
