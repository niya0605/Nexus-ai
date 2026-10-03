"""Global exception handlers.

Implements the standard error envelope already frozen in the REST API
Contract (Section 5) for every failure a request can hit — the three
framework-level cases (HTTPException, request validation errors,
anything truly unexpected), plus `AppException`: the base class every
module's own domain-specific exceptions inherit from (per the Technical
Design Document's exception taxonomy, Section 12). `AppException` itself
is introduced in Sprint 1B (see app/modules/auth/exceptions.py for its
first concrete subclass) — this module only defines the shared base and
its handler; it is deliberately never raised directly.
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

# Stable, machine-readable codes for the common HTTP statuses, per the
# REST API Contract's Error Catalog (Section 26). A status without an
# established name here still gets a response in the correct envelope
# shape — just a generic code — rather than being left unhandled.
_STATUS_CODES: dict[int, str] = {
    status.HTTP_400_BAD_REQUEST: "bad_request",
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_422_UNPROCESSABLE_ENTITY: "validation_error",
    status.HTTP_429_TOO_MANY_REQUESTS: "rate_limited",
}


def _error_envelope(
    *, code: str, message: str, request: Request, details: list[dict] | None = None
) -> dict:
    envelope: dict = {
        "error": {
            "code": code,
            "message": message,
            "request_id": getattr(request.state, "request_id", None),
        }
    }
    if details:
        envelope["error"]["details"] = details
    return envelope


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_envelope(
            code=_STATUS_CODES.get(exc.status_code, "error"),
            message=str(exc.detail),
            request=request,
        ),
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    details = [
        {"field": ".".join(str(part) for part in error["loc"]), "issue": error["msg"]}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=_error_envelope(
            code="validation_error",
            message="The request could not be validated.",
            request=request,
            details=details,
        ),
    )


class AppException(Exception):
    """Base class for domain-specific exceptions raised by service-layer code.

    Never raised directly — each module defines its own subclasses (see
    e.g. app/modules/auth/exceptions.py), each declaring the HTTP status
    and error `code` its response should carry. Keeping that mapping on
    the exception itself, rather than in a growing central dispatch
    table, is what lets each module add its own exceptions without
    touching this file.
    """

    status_code: int = status.HTTP_400_BAD_REQUEST
    error_code: str = "error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_envelope(code=exc.error_code, message=exc.message, request=request),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Full detail — including the stack trace — goes to the log only.
    # This is the one place a stack trace is allowed to exist at all;
    # the client never sees more than a generic, sanitized message,
    # regardless of environment.
    logger.exception("Unhandled exception while processing request", exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_error_envelope(
            code="internal_error",
            message="Something went wrong on our end — we're looking into it.",
            request=request,
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    # Registered against Starlette's base HTTPException — not fastapi's
    # subclass — specifically because Starlette's own routing layer
    # (e.g. an unmatched route) raises the *base* class directly. A
    # handler registered only for fastapi.HTTPException would miss those
    # and silently fall back to FastAPI's default, unwrapped {"detail":
    # ...} response. Registering the base class catches both, since
    # fastapi.HTTPException is itself a subclass of it.
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    # More specific than the bare Exception handler below — Starlette
    # resolves the most specific registered handler by MRO, so any
    # AppException subclass is caught here, not by the generic handler.
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
