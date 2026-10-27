"""Shared pytest configuration for the backend test suite.

`run_db_test` / `run_http_test` in backend/tests/db.py are plain helpers,
imported directly by each module's tests — not fixtures.
"""

from app.config import settings

# Tests assert production behaviour, regardless of local-dev conveniences in .env.
settings.AUTO_VERIFY_EMAILS = False
