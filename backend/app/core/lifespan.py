"""Application lifespan handler.

For this milestone: initialize logging, log startup, log shutdown —
nothing else. No connection to Postgres, Redis, Qdrant, MinIO, or mail
is opened here; that begins once the modules owning those connections
exist and have a real reason to open one at startup.
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging(debug=settings.APP_DEBUG)
    logger.info(f"Starting {settings.APP_NAME} (env={settings.APP_ENV}, version={app.version})")

    yield

    logger.info(f"Shutting down {settings.APP_NAME}")
