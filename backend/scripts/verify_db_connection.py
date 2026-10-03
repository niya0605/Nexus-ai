"""Lightweight database connectivity check.

Not part of the application — never imported by app startup, a route,
or a service (no startup hook exists, and none should be added on
account of this file). Run manually, on demand, to confirm the
currently configured database is actually reachable:

    cd backend
    python -m scripts.verify_db_connection

Creates its own short-lived engine (deliberately not app.db.session's
module-level `engine`) so this can be run in isolation, disposes of it
when done either way, and never raises — failure is reported, not
thrown, since this is a manual diagnostic, not application code.
"""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.db.session import build_database_url


async def verify_connection() -> bool:
    """Attempt one connection and one trivial query; report the result."""
    target = f"{settings.database.HOST}:{settings.database.PORT}/{settings.database.DB}"
    engine = create_async_engine(build_database_url(), pool_pre_ping=True)

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        print(f"[ok] Connected to Postgres at {target}")
        return True
    except Exception as exc:  # noqa: BLE001 — intentionally broad: manual diagnostic output, not app error handling
        print(f"[fail] Could not connect to Postgres at {target}")
        print(f"       {type(exc).__name__}: {exc}")
        return False
    finally:
        await engine.dispose()


if __name__ == "__main__":
    success = asyncio.run(verify_connection())
    raise SystemExit(0 if success else 1)
