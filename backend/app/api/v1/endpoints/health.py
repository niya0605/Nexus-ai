"""Application health endpoint.

Confirms the application process itself is up and correctly configured
— nothing more. Deliberately does NOT check Postgres, Redis, Qdrant, or
MinIO connectivity; that's a distinct, future concern (see
backend/scripts/verify_db_connection.py, introduced in M0.2C, for the
manual database check). A dependency-checking `/health/ready`-style
endpoint is a natural addition once those clients exist — not this one.

Returns a flat body (not the standard `{"data": ...}` envelope) —
a deliberate, common exception for health endpoints, since load
balancers and uptime monitors expect a predictable, unwrapped shape.
"""

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    application: str
    version: str
    environment: str
    timestamp: datetime


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="ok",
        application=settings.APP_NAME,
        version="0.1.0",
        environment=settings.APP_ENV,
        timestamp=datetime.now(UTC),
    )
