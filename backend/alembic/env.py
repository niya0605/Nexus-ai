"""Alembic environment configuration.

Wired to the same `Settings` object and the same shared `Base` used by
the application itself — see app/config/ and app/db/base.py. Uses
SQLAlchemy's async engine (matching app/db/session.py) rather than a
separate synchronous connection, so migrations run against the same
driver (asyncpg) the application uses.
"""

import asyncio
from logging.config import fileConfig

# Importing the model registry (rather than app.db.base directly) is
# what populates Base.metadata below with every known table — see
# app/db/model_registry.py for why this is the one place that import
# happens, instead of listing model modules here by hand.
import app.db.model_registry  # noqa: F401
from alembic import context
from app.db.base import Base
from app.db.session import build_database_url
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# Alembic Config object, providing access to values within alembic.ini.
config = context.config

# Interpret the config file for Python logging, if a logging section is
# present (it is — see alembic.ini).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate support — points at the single shared
# Base every ORM model inherits from, now populated via the import above.
target_metadata = Base.metadata

# The connection URL is built from the application's own Settings (via
# the same helper app/db/session.py uses), never duplicated as a static
# value in alembic.ini — there is exactly one place database
# configuration lives.
config.set_main_option("sqlalchemy.url", build_database_url())


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emits SQL without a live DB connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode against an AsyncEngine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
