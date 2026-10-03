"""Workspace, Membership, WorkspaceSettings, Role, Invitation, and
AuditLog models.

Grouped under the Entity & Domain Model's conceptual "Authentication"
and "Workspace" domains, all code-owned by this module per the
Technical Design Document's Ownership Matrix. `Role` and `Invitation`
were added in Sprint 1A (data shape only, no business logic). S1F adds
the Workspace aggregate itself — `Workspace`, `Membership`,
`WorkspaceSettings` — plus `AuditLog`, and resolves Sprint 1A's
documented `Invitation.workspace_id` deviation now that `workspaces`
exists (see that class's docstring below).

**AuditLog is not a previously-frozen entity.** No Data Dictionary or
Database Design document exists in this repository to inspect (both
are marked "not yet added" in docs/database/README.md) — this model's
shape is built directly from the field list S1F's own specification
gives (`actor_user_id`, `workspace_id`, `action`, `target_type`,
`target_id`, `metadata`, `created_at`), not copied from a frozen
document. Flagged here and in docs/development/README.md as an
UNRESOLVED CONTRACT GAP: the *fields* are given, but no frozen schema
(types, constraints, indexes) exists to match exactly.
"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.utils.db_enum import string_enum
from app.utils.ids import generate_uuid7

if TYPE_CHECKING:
    # Type-checking only — see app/modules/auth/models.py for why this
    # isn't a runtime import.
    from app.modules.auth.models import User


class RoleName(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class InvitationStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"


class WorkspaceStatus(str, enum.Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class MembershipStatus(str, enum.Enum):
    ACTIVE = "active"
    REMOVED = "removed"


class Role(Base):
    """Named, system-defined capability tier. See Data Dictionary — Role."""

    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=generate_uuid7
    )
    name: Mapped[RoleName] = mapped_column(
        string_enum(RoleName, length=20, name="role_name"),
        nullable=False,
        unique=True,
    )
    description: Mapped[str] = mapped_column(String(250), nullable=False)
    capability_set: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    is_system_defined: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    invitations: Mapped[list["Invitation"]] = relationship("Invitation", back_populates="role")


class Invitation(Base):
    """Pending offer for an email address to join a workspace at a role.

    See Data Dictionary — Authentication Domain — Invitation.

    Invitation *creation/sending/acceptance* is explicitly out of S1F's
    scope (a later sprint) — this model gains only the FK constraint
    S1A's docstring always said would follow once `workspaces` existed.
    """

    __tablename__ = "invitations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked', 'expired')",
            name="chk_invitations_status",
        ),
        # Partial unique index: at most one *pending* invitation per
        # (workspace, email) pair — a re-invite replaces rather than
        # duplicates, per the frozen Domain Model invariant. A resolved
        # invitation (accepted/revoked/expired) never blocks a new one.
        Index(
            "uq_invitations_workspace_email_pending",
            "workspace_id",
            "invited_email",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=generate_uuid7
    )

    # S1A's documented deviation, now resolved: `workspaces` exists, so
    # the FK constraint the Data Dictionary always specified is added
    # here. CASCADE — an invitation has no purpose once its workspace is
    # gone, mirroring Session's cascade on User (app/modules/auth/models.py).
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    invited_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False
    )
    # ON DELETE RESTRICT, not SET NULL — see module docstring's
    # "Resolved inconsistency."
    invited_by_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    status: Mapped[InvitationStatus] = mapped_column(
        string_enum(InvitationStatus, length=20, name="invitation_status"),
        nullable=False,
        default=InvitationStatus.PENDING,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    # No default: computed by the service layer from the workspace's
    # invitation-expiry policy, which doesn't exist yet.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    role: Mapped["Role"] = relationship("Role", back_populates="invitations")
    invited_by: Mapped["User"] = relationship("User", back_populates="sent_invitations")


class Workspace(Base):
    """The tenant boundary — everything workspace-scoped ultimately
    belongs to exactly one Workspace. See this module's docstring and
    S1F's own specification for the frozen lifecycle
    (`active → archived → deleted`, archive reversible, delete enters a
    soft-delete grace window) and invariants (must always have at least
    one Owner-role Membership; creation atomically produces a Workspace,
    a founding Membership, and WorkspaceSettings together — see
    `app.modules.workspaces.service.create_workspace`).
    """

    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'archived', 'deleted')", name="chk_workspaces_status"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=generate_uuid7
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Server-derived (see app.modules.workspaces.slug) — never accepted
    # from a client request. Globally unique, not per-owner-user unique.
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    status: Mapped[WorkspaceStatus] = mapped_column(
        string_enum(WorkspaceStatus, length=20, name="workspace_status"),
        nullable=False,
        default=WorkspaceStatus.ACTIVE,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    memberships: Mapped[list["Membership"]] = relationship(
        "Membership", back_populates="workspace", cascade="all, delete-orphan"
    )
    settings: Mapped["WorkspaceSettings"] = relationship(
        "WorkspaceSettings",
        back_populates="workspace",
        cascade="all, delete-orphan",
        uselist=False,
    )


class Membership(Base):
    """The sole source of truth for who belongs to a Workspace and what
    Role they have. A (workspace, user) pair may have at most one
    *active* Membership — enforced by a partial unique index, the same
    technique `Invitation`'s pending-uniqueness already uses above, so a
    removed membership never blocks a fresh one for the same pair.
    """

    __tablename__ = "memberships"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'removed')", name="chk_memberships_status"),
        Index(
            "uq_memberships_workspace_user_active",
            "workspace_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=generate_uuid7
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[MembershipStatus] = mapped_column(
        string_enum(MembershipStatus, length=20, name="membership_status"),
        nullable=False,
        default=MembershipStatus.ACTIVE,
        index=True,
    )
    # Nullable — the founding membership created alongside a new
    # Workspace has no inviter (see service.create_workspace); every
    # other membership will, once Invitation acceptance exists (a later
    # sprint, out of S1F's scope). SET NULL, not RESTRICT: unlike
    # Invitation.invited_by_user_id (which anchors an *offer* that makes
    # no sense without its sender), a Membership's own record of who
    # invited them is informational, not load-bearing.
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    removed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="memberships")
    # `foreign_keys=` required — two columns on this table reference
    # `users.id` (`user_id`, `invited_by_user_id`), so SQLAlchemy can't
    # infer which one this relationship means without disambiguation
    # (confirmed empirically: AmbiguousForeignKeysError otherwise).
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    role: Mapped["Role"] = relationship("Role")


class WorkspaceSettings(Base):
    """Strictly 1:1 with Workspace — created atomically alongside it
    (`service.create_workspace`) and never independently deleted;
    updates happen in place, never a new row.
    """

    __tablename__ = "workspace_settings"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=generate_uuid7
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    document_retention_days: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    # JSONB, not a CHECK-constrained VARCHAR list — the allowed-format
    # list is a small, ordered set of strings with no natural single-
    # column CHECK expression; validated at the schema/service layer
    # against the same frozen four formats instead (pdf/docx/txt/md).
    allowed_file_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    max_document_size_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="settings")


class AuditLog(Base):
    """Append-only record of security-sensitive workspace actions —
    currently written only for Membership role changes and
    WorkspaceSettings retention-policy changes, per S1F's explicit
    audit requirement. See this module's docstring: not a previously-
    frozen entity: this class's shape is built directly from the field
    list S1F's own specification gives, not copied from a frozen
    Data Dictionary entry (none exists to copy from). Flagged as an
    UNRESOLVED CONTRACT GAP.

    Never written for `password_hash`, tokens, or any other Restricted
    value — `metadata_` only ever holds the specific before/after
    business fields each call site names explicitly (e.g. old/new role
    name), never a raw request body.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=generate_uuid7
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    # Mapped attribute named `metadata_` — `metadata` is reserved on
    # every SQLAlchemy declarative model (it's the class-level
    # MetaData/table-registry attribute); the column itself is still
    # named `metadata` in the database, via `name="metadata"` below.
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
