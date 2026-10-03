"""Nexus AI backend — application entrypoint.

Delegates entirely to the application factory in
app/core/application.py — this module exists only so an ASGI server
(`uvicorn app.main:app`) has something to import. No configuration,
middleware, or routing logic lives here; see app/core/application.py
for all of that.
"""

from app.core.application import create_application

app = create_application()
