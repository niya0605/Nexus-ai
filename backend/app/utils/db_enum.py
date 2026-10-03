"""Shared helper for enum-shaped database columns.

Every `status`-like column in the frozen Database Design is a `VARCHAR`
with a `CHECK` constraint enumerating lowercase, snake_case values (e.g.
`'pending_verification'`) — not a native PostgreSQL `ENUM` type (see the
Database Design Section 1's normalization strategy). SQLAlchemy's
`Enum(SomePythonEnum, native_enum=False)` produces exactly that shape,
but by default stores the Python enum member's *name*
(`PENDING_VERIFICATION`) rather than its *value*
(`pending_verification`) — which would violate the very CHECK
constraint it creates. `values_callable` is what makes it store the
value instead; every model defines this the same way, so it lives here
once rather than being repeated — and risking being gotten wrong — at
every call site.
"""

import enum

from sqlalchemy import Enum as SAEnum


def string_enum(python_enum: type[enum.Enum], *, length: int, name: str) -> SAEnum:
    """A VARCHAR(length) + CHECK column type backed by a Python str-enum's values."""
    return SAEnum(
        python_enum,
        native_enum=False,
        length=length,
        name=name,
        values_callable=lambda enum_cls: [member.value for member in enum_cls],
    )
