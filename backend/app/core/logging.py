"""Centralized application logging.

Standard library `logging` only — no third-party logging library. One
consistent, structured (JSON) formatter for every log line, with the
current request's ID attached automatically wherever one exists (see
app/core/middleware.py's RequestIDMiddleware), so every line emitted
while handling a request can be correlated back to it without every
call site having to pass the ID explicitly.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

# Set by RequestIDMiddleware for the duration of one request; read by
# RequestIDLogFilter so every log line emitted during that request
# carries the same ID. `None` outside of a request (e.g. startup/shutdown
# logs).
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIDLogFilter(logging.Filter):
    """Attaches the current request's ID (if any) to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JSONFormatter(logging.Formatter):
    """Renders each log record as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(*, debug: bool) -> None:
    """Configure the root logger once, at application startup.

    INFO by default; DEBUG when `debug` is true (i.e. `APP_DEBUG=true`).
    Replaces any handlers already attached to the root logger, so a
    repeated call (e.g. under a test runner reloading the app) doesn't
    produce duplicate log lines.
    """
    level = logging.DEBUG if debug else logging.INFO

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JSONFormatter())
    handler.addFilter(RequestIDLogFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
