"""Shared SQLAlchemy declarative base.

Every future ORM model inherits from `Base` — and nothing else lives in
this module. No metadata customization (naming conventions, schema
defaults) is applied here; that is deliberately deferred to when actual
models are introduced, at which point it should follow the constraint-
naming standards already frozen in the PostgreSQL Database Design
(Section 15). This module defines only the foundation Alembic's
`target_metadata` points to (see alembic/env.py).
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base class for all future ORM models."""
