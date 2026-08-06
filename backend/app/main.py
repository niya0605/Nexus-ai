"""Nexus AI backend — application entrypoint.

This module currently does nothing beyond instantiating the FastAPI
application object. Middleware, exception handlers, and API routers are
intentionally NOT wired up here yet — that begins in a later milestone,
once the corresponding modules exist (per the frozen Technical Design
Document's module-by-module build order).

Milestone M0.1 scope: repository scaffolding only. No business logic.
"""

from fastapi import FastAPI

app = FastAPI(
    title="Nexus AI API",
    version="0.1.0",
)
