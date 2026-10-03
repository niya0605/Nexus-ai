"""Application middleware: request ID, request timing, and CORS.

Exactly the three concerns this milestone calls for — nothing else.
Registered together in app/core/application.py, in an order explained
there.
"""

import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings
from app.core.logging import request_id_var

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attaches a request ID to every request and echoes it back.

    Honors a client-supplied `X-Request-ID` header if present (per the
    REST API Contract's Standard Request Format, Section 3); generates a
    new UUID4 otherwise. The ID is attached to `request.state` for
    anything downstream that wants it (route handlers, exception
    handlers) and to a context variable so every log line emitted during
    this request is automatically correlated to it.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming if incoming else str(uuid.uuid4())

        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)

        response.headers[REQUEST_ID_HEADER] = request_id
        return response


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Measures request duration and returns it as a response header.

    Purely observational — no behavior varies based on timing.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Process-Time-Ms"] = f"{duration_ms:.2f}"
        return response


def get_cors_origins() -> list[str]:
    """Resolve allowed CORS origins for the current environment.

    Hardcoded rather than settings-driven: `app.config.settings` has no
    dedicated `CORS_ORIGINS` field yet, and adding one is out of scope
    for this milestone's file list. Fails closed on purpose — only
    `local`/`development` get an origin at all (matching the frontend's
    default dev port); `staging`/`production` get none until a real,
    explicit origin list is configured in a later milestone. Never a
    wildcard, per the Technical Design Document's Security Architecture
    (Section 19).
    """
    if settings.APP_ENV in ("local", "development"):
        return ["http://localhost:3000", "http://localhost:3001"]
    return []
