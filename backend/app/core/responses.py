"""Standard success-response envelope.

Every endpoint's success response is `{"data": ..., "meta": {"request_id": ...}}`
— per the REST API Contract's Standard Success Response (Section 4).
`GET /api/v1/health` is the one documented, deliberate exception (a
flat body, for load-balancer/uptime-monitor compatibility — see
app/api/v1/endpoints/health.py); every other endpoint, starting with
registration in Sprint 1B, uses this envelope.

This didn't need to exist before Sprint 1B, since the only endpoint so
far (health) is the documented exception to it.
"""

from typing import Generic, TypeVar

from fastapi import Request
from pydantic import BaseModel

T = TypeVar("T")


class ResponseMeta(BaseModel):
    request_id: str | None = None


class SuccessEnvelope(BaseModel, Generic[T]):
    data: T
    meta: ResponseMeta


def envelope(data: T, request: Request) -> SuccessEnvelope[T]:
    """Build a SuccessEnvelope, reading the request ID already attached
    to `request.state` by RequestIDMiddleware (app/core/middleware.py)."""
    return SuccessEnvelope(
        data=data, meta=ResponseMeta(request_id=getattr(request.state, "request_id", None))
    )


class CursorPageMeta(ResponseMeta):
    """**IMPLEMENTATION CHOICE (S1F)** — no frozen cursor-pagination
    envelope shape exists to copy (the REST API Contract itself isn't a
    file in this repository — see docs/api/README.md). `next_cursor`
    (opaque, base64; `null` on the last page) is the smallest addition
    to the existing, already-frozen `{"data": ..., "meta": {"request_id"}}`
    shape that supports "cursor pagination for list endpoints" without
    inventing a second, differently-shaped envelope. Flagged here and
    in docs/development/README.md.
    """

    next_cursor: str | None = None


class CursorPage(BaseModel, Generic[T]):
    data: list[T]
    meta: CursorPageMeta


def cursor_page(items: list[T], next_cursor: str | None, request: Request) -> CursorPage[T]:
    """Build a CursorPage — the list-endpoint sibling of `envelope()`."""
    return CursorPage(
        data=items,
        meta=CursorPageMeta(
            request_id=getattr(request.state, "request_id", None), next_cursor=next_cursor
        ),
    )
