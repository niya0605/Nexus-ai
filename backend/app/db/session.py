"""Async SQLAlchemy engine and session factory.

Builds one `AsyncEngine` from the shared `Settings` object (never a
duplicated or hardcoded connection string) and one `async_sessionmaker`
bound to it. Nothing in this module executes a query, opens a
connection eagerly, or is invoked automatically — `create_async_engine`
is lazy; the first real connection happens only when something actually
uses the engine (a session, or the verification script in
backend/scripts/).
"""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings


def build_database_url() -> str:
    """Assemble the asyncpg connection string from `settings.database`.

    Kept as its own function — rather than inlined where the engine is
    created — so there is exactly one place this shape is defined;
    alembic/env.py reuses it instead of re-deriving its own copy.
    """
    db = settings.database
    return f"postgresql+asyncpg://{db.USER}:{db.PASSWORD}@{db.HOST}:{db.PORT}/{db.DB}"


DATABASE_URL = build_database_url()

# Production-friendly pooling defaults for a single backend instance, per
# the Technical Design Document's Performance Strategy (Section 22):
#   - pool_size / max_overflow: a modest persistent pool with headroom
#     for bursts, sized for one process rather than a cluster.
#   - pool_recycle: recycle connections before they can go stale against
#     a database-side idle timeout.
#   - pool_pre_ping: verify a pooled connection is still alive before
#     handing it out, trading a small latency cost for avoiding "server
#     closed the connection unexpectedly" errors.
engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    echo=settings.APP_DEBUG,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True,
)

# expire_on_commit=False: objects remain usable after commit without an
# implicit re-fetch — required for the async session pattern, since
# attribute access after commit would otherwise trigger an implicit I/O
# call outside of an awaited context.
AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
