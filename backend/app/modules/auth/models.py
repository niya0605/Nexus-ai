"""Authentication domain models: User and Session.

Implements exactly the fields, constraints, indexes, and relationships
already frozen in the Data Dictionary (Authentication Domain) and the
PostgreSQL Database Design — nothing invented, nothing added. No
business logic, no password hashing, no JWT: this module is data shape
only (Sprint 1A).

`Role` and `Invitation` — grouped with `User` and `Session` under the
Entity & Domain Model's conceptual "Authentication Domain" — are
implemented in `app/modules/workspaces/models.py` instead, matching the
code-ownership already frozen in the Technical Design Document's
Ownership Matrix (Role/Invitation belong to the `workspaces` module),
not the Domain Model's conceptual grouping. See that module's
`models.py` docstring for the same note from its side.

Enum-shaped columns (`status`) use SQLAlchemy's `Enum(..., native_enum=False)`
— a `VARCHAR` with an application-defined `CHECK` constraint — matching
the frozen Database Design exactly, which specifies `String` columns
with `CHECK (status IN (...))`, not a native PostgreSQL `ENUM` type.
"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.utils.db_enum import string_enum
from app.utils.ids import generate_uuid7

if TYPE_CHECKING:
    # Type-checking only — never imported at runtime, so this creates no
    # circular dependency on app.modules.workspaces. The relationship()
    # calls below reference "Invitation" by name via the shared
    # declarative registry instead (see app/db/model_registry.py).
    from app.modules.workspaces.models import Invitation


class UserStatus(str, enum.Enum):
    PENDING_VERIFICATION = "pending_verification"
    ACTIVE = "active"
    DEACTIVATED = "deactivated"


class SessionStatus(str, enum.Enum):
    ACTIVE = "active"
    REVOKED = "revoked"


class User(Base):
    """Authenticatable identity. See Data Dictionary — Authentication Domain — User."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("failed_login_count >= 0", name="chk_users_failed_login_count"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=generate_uuid7
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    status: Mapped[UserStatus] = mapped_column(
        string_enum(UserStatus, length=30, name="user_status"),
        nullable=False,
        default=UserStatus.PENDING_VERIFICATION,
        index=True,
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    failed_login_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    sessions: Mapped[list["Session"]] = relationship(
        "Session", back_populates="user", cascade="all, delete-orphan"
    )
    # Forward reference resolved via the shared declarative registry, not
    # a direct import — see app/db/model_registry.py.
    sent_invitations: Mapped[list["Invitation"]] = relationship(
        "Invitation", back_populates="invited_by"
    )


# Functional unique index — case-insensitive email uniqueness, matching
# the frozen Database Design exactly (Section 6: "unique functional
# index on lower(email)"). Declared at module level, after the class
# body, because it references User.email as a real column expression.
Index("uq_users_email_lower", func.lower(User.email), unique=True)


class Session(Base):
    """Per-device authenticated state. See Data Dictionary — Authentication Domain — Session."""

    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'revoked')", name="chk_sessions_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=generate_uuid7
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    refresh_token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    device_label: Mapped[str | None] = mapped_column(String(150), nullable=True, default=None)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    status: Mapped[SessionStatus] = mapped_column(
        string_enum(SessionStatus, length=20, name="session_status"),
        nullable=False,
        default=SessionStatus.ACTIVE,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    # No default: computed by the service layer at creation time from the
    # configured session TTL (Settings.ACCESS/REFRESH_TOKEN_EXPIRE_*),
    # which doesn't exist yet — see Sprint 1B.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    user: Mapped["User"] = relationship("User", back_populates="sessions")
