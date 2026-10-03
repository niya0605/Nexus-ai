"""FastAPI application factory.

The single place a `FastAPI` instance is constructed. Every setting
(title, docs URLs, ...) is read from `app.config.settings` — never
hardcoded — and every cross-cutting concern (middleware, exception
handlers, routers, lifespan) is wired here, in one clearly-ordered
place, so app/main.py stays a one-line entrypoint.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.lifespan import lifespan
from app.core.middleware import (
    RequestIDMiddleware,
    RequestTimingMiddleware,
    get_cors_origins,
)

APP_VERSION = "0.1.0"


def create_application() -> FastAPI:
    """Construct and fully configure the FastAPI application."""

    # Hide interactive docs in production — "disable unnecessary
    # defaults if appropriate" — while keeping them available in every
    # environment a developer actually works in.
    docs_enabled = settings.APP_ENV != "production"

    app = FastAPI(
        title=settings.APP_NAME,
        version=APP_VERSION,
        description="Nexus AI — an AI-powered Knowledge Workspace API.",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )

    # Middleware order matters: Starlette applies the *last*-added
    # middleware as the *outermost* layer. Request ID and timing are
    # added first so their state is established as early as possible for
    # everything downstream; CORS is added last so it wraps everything,
    # including error responses.
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(RequestTimingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(api_router)

    return app
