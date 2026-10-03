"""FastAPI dependency for obtaining a database session.

Future routes will depend on this exactly as:

    from app.db.dependencies import get_db
    ...
    async def some_route(db: AsyncSession = Depends(get_db)) -> ...:
        ...

No route, service, or repository exists yet to consume this — this
milestone provides only the dependency itself.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionFactory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped `AsyncSession`, closed when the request ends.

    Deliberately does not commit or roll back here — owning the
    transaction boundary is a service-layer responsibility (per the
    Technical Design Document, Section 18: Transaction Management), not
    this dependency's. Closing the session on exit implicitly rolls back
    anything left uncommitted.
    """
    async with AsyncSessionFactory() as session:
        yield session
