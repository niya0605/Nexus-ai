"""Top-level API router.

Aggregates versioned API routers under `/api` — currently just v1. A
future version (per the REST API Contract's Versioning Strategy, Section
29) is added here as an additional `include_router` call, never by
modifying v1's existing routes.
"""

from fastapi import APIRouter

from app.api.v1.router import api_router as api_v1_router

api_router = APIRouter(prefix="/api")
api_router.include_router(api_v1_router)
