"""Model tests for Workspace, Membership, WorkspaceSettings, and
AuditLog (S1F) — table creation, constraints, uniqueness, and cascade
behavior. No service-layer logic here (see test_workspace_service.py
for create_workspace's atomicity, the owner invariant, etc.) — this
file only proves the schema itself behaves as declared.

Requires a real, reachable PostgreSQL — see backend/tests/db.py. Roles
are real seeded data now (see test_models.py's module docstring); every
test below that needs one fetches it rather than inserting a new row.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from tests.db import run_db_test

from app.modules.auth.models import User
from app.modules.workspaces.models import (
    AuditLog,
    Membership,
    MembershipStatus,
    Role,
    RoleName,
    Workspace,
    WorkspaceSettings,
    WorkspaceStatus,
)


async def _get_role(session: AsyncSession, name: RoleName) -> Role:
    return (await session.execute(select(Role).where(Role.name == name))).scalar_one()


def _make_user() -> User:
    return User(
        email=f"user-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="not-a-real-hash",
        display_name="Test User",
    )


def _make_workspace(**overrides: object) -> Workspace:
    unique = uuid.uuid4().hex[:8]
    defaults: dict[str, object] = {"name": f"Workspace {unique}", "slug": f"workspace-{unique}"}
    defaults.update(overrides)
    return Workspace(**defaults)  # type: ignore[arg-type]


def _make_settings(workspace_id: uuid.UUID, **overrides: object) -> WorkspaceSettings:
    defaults: dict[str, object] = {
        "workspace_id": workspace_id,
        "allowed_file_types": ["pdf", "docx", "txt", "md"],
        "max_document_size_mb": 50,
    }
    defaults.update(overrides)
    return WorkspaceSettings(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------


def test_create_and_fetch_workspace() -> None:
    async def body(session: AsyncSession) -> None:
        workspace = _make_workspace(name="Acme Corp", slug="acme-corp")
        session.add(workspace)
        await session.flush()

        fetched = (
            await session.execute(select(Workspace).where(Workspace.id == workspace.id))
        ).scalar_one()
        assert fetched.name == "Acme Corp"
        assert fetched.status == WorkspaceStatus.ACTIVE  # default applied
        assert fetched.archived_at is None
        assert fetched.deleted_at is None

    run_db_test(body)


def test_workspace_slug_uniqueness() -> None:
    async def body(session: AsyncSession) -> None:
        session.add(_make_workspace(slug="taken-slug"))
        await session.flush()

        session.add(_make_workspace(slug="taken-slug"))
        with pytest.raises(IntegrityError):
            await session.flush()

    run_db_test(body)


def test_workspace_status_rejects_unknown_value() -> None:
    async def body(session: AsyncSession) -> None:
        workspace = _make_workspace()
        session.add(workspace)
        await session.flush()

        # Bypass the Python enum entirely — proves the CHECK constraint
        # itself, not just application-level validation.
        with pytest.raises(IntegrityError):
            await session.execute(
                Workspace.__table__.update()
                .where(Workspace.id == workspace.id)
                .values(status="not_a_real_status")
            )

    run_db_test(body)


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------


def test_create_membership_with_relationships() -> None:
    async def body(session: AsyncSession) -> None:
        workspace = _make_workspace()
        user = _make_user()
        session.add_all([workspace, user])
        await session.flush()
        role = await _get_role(session, RoleName.OWNER)

        membership = Membership(workspace_id=workspace.id, user_id=user.id, role_id=role.id)
        session.add(membership)
        await session.flush()
        await session.refresh(membership, attribute_names=["workspace", "user", "role"])

        assert membership.status == MembershipStatus.ACTIVE  # default applied
        assert membership.workspace.id == workspace.id
        assert membership.user.id == user.id
        assert membership.role.name == RoleName.OWNER
        assert membership.invited_by_user_id is None  # founding-style membership

    run_db_test(body)


def test_membership_active_uniqueness_per_workspace_and_user() -> None:
    async def body(session: AsyncSession) -> None:
        workspace = _make_workspace()
        user = _make_user()
        session.add_all([workspace, user])
        await session.flush()
        role = await _get_role(session, RoleName.MEMBER)

        session.add(Membership(workspace_id=workspace.id, user_id=user.id, role_id=role.id))
        await session.flush()

        # A second *active* membership for the same (workspace, user) —
        # must collide with the partial unique index.
        session.add(Membership(workspace_id=workspace.id, user_id=user.id, role_id=role.id))
        with pytest.raises(IntegrityError):
            await session.flush()

    run_db_test(body)


def test_removed_membership_does_not_block_a_new_active_one() -> None:
    async def body(session: AsyncSession) -> None:
        workspace = _make_workspace()
        user = _make_user()
        session.add_all([workspace, user])
        await session.flush()
        role = await _get_role(session, RoleName.MEMBER)

        removed = Membership(
            workspace_id=workspace.id,
            user_id=user.id,
            role_id=role.id,
            status=MembershipStatus.REMOVED,
            removed_at=datetime.now(UTC),
        )
        session.add(removed)
        await session.flush()

        # A fresh *active* membership for the same pair is allowed —
        # the partial unique index only applies to status='active'.
        rejoined = Membership(workspace_id=workspace.id, user_id=user.id, role_id=role.id)
        session.add(rejoined)
        await session.flush()  # should NOT raise

    run_db_test(body)


def test_membership_role_cannot_be_deleted_while_referenced() -> None:
    async def body(session: AsyncSession) -> None:
        workspace = _make_workspace()
        user = _make_user()
        session.add_all([workspace, user])
        await session.flush()
        role = await _get_role(session, RoleName.ADMIN)

        session.add(Membership(workspace_id=workspace.id, user_id=user.id, role_id=role.id))
        await session.flush()

        await session.delete(role)
        with pytest.raises(IntegrityError):
            await session.flush()

    run_db_test(body)


def test_deleting_workspace_cascades_to_memberships() -> None:
    async def body(session: AsyncSession) -> None:
        workspace = _make_workspace()
        user = _make_user()
        session.add_all([workspace, user])
        await session.flush()
        role = await _get_role(session, RoleName.OWNER)

        membership = Membership(workspace_id=workspace.id, user_id=user.id, role_id=role.id)
        session.add(membership)
        await session.flush()
        membership_id = membership.id

        await session.delete(workspace)
        await session.flush()

        remaining = (
            await session.execute(select(Membership).where(Membership.id == membership_id))
        ).scalar_one_or_none()
        assert remaining is None

    run_db_test(body)


# ---------------------------------------------------------------------------
# WorkspaceSettings
# ---------------------------------------------------------------------------


def test_create_workspace_settings() -> None:
    async def body(session: AsyncSession) -> None:
        workspace = _make_workspace()
        session.add(workspace)
        await session.flush()

        settings = _make_settings(workspace.id)
        session.add(settings)
        await session.flush()
        await session.refresh(settings)

        assert settings.max_document_size_mb == 50
        assert settings.allowed_file_types == ["pdf", "docx", "txt", "md"]
        assert settings.document_retention_days is None

    run_db_test(body)


def test_workspace_settings_workspace_id_uniqueness() -> None:
    async def body(session: AsyncSession) -> None:
        workspace = _make_workspace()
        session.add(workspace)
        await session.flush()

        session.add(_make_settings(workspace.id))
        await session.flush()

        # A second settings row for the same workspace — strictly 1:1.
        session.add(_make_settings(workspace.id))
        with pytest.raises(IntegrityError):
            await session.flush()

    run_db_test(body)


def test_deleting_workspace_cascades_to_settings() -> None:
    async def body(session: AsyncSession) -> None:
        workspace = _make_workspace()
        session.add(workspace)
        await session.flush()

        settings = _make_settings(workspace.id)
        session.add(settings)
        await session.flush()
        settings_id = settings.id

        await session.delete(workspace)
        await session.flush()

        remaining = (
            await session.execute(
                select(WorkspaceSettings).where(WorkspaceSettings.id == settings_id)
            )
        ).scalar_one_or_none()
        assert remaining is None

    run_db_test(body)


# ---------------------------------------------------------------------------
# AuditLog
# ---------------------------------------------------------------------------


def test_create_and_fetch_audit_log() -> None:
    async def body(session: AsyncSession) -> None:
        workspace = _make_workspace()
        actor = _make_user()
        session.add_all([workspace, actor])
        await session.flush()

        entry = AuditLog(
            actor_user_id=actor.id,
            workspace_id=workspace.id,
            action="membership.role_changed",
            target_type="membership",
            target_id=uuid.uuid4(),
            metadata_={"before_role": "member", "after_role": "admin"},
        )
        session.add(entry)
        await session.flush()

        fetched = (
            await session.execute(select(AuditLog).where(AuditLog.id == entry.id))
        ).scalar_one()
        assert fetched.action == "membership.role_changed"
        assert fetched.metadata_ == {"before_role": "member", "after_role": "admin"}
        assert fetched.created_at is not None

    run_db_test(body)


def test_audit_log_actor_cannot_be_deleted_while_referenced() -> None:
    async def body(session: AsyncSession) -> None:
        workspace = _make_workspace()
        actor = _make_user()
        session.add_all([workspace, actor])
        await session.flush()

        session.add(
            AuditLog(
                actor_user_id=actor.id,
                workspace_id=workspace.id,
                action="workspace_settings.retention_changed",
                target_type="workspace_settings",
                target_id=uuid.uuid4(),
                metadata_={},
            )
        )
        await session.flush()

        await session.delete(actor)
        with pytest.raises(IntegrityError):
            await session.flush()

    run_db_test(body)


def test_deleting_workspace_cascades_to_audit_logs() -> None:
    async def body(session: AsyncSession) -> None:
        workspace = _make_workspace()
        actor = _make_user()
        session.add_all([workspace, actor])
        await session.flush()

        entry = AuditLog(
            actor_user_id=actor.id,
            workspace_id=workspace.id,
            action="membership.role_changed",
            target_type="membership",
            target_id=uuid.uuid4(),
            metadata_={},
        )
        session.add(entry)
        await session.flush()
        entry_id = entry.id

        await session.delete(workspace)
        await session.flush()

        remaining = (
            await session.execute(select(AuditLog).where(AuditLog.id == entry_id))
        ).scalar_one_or_none()
        assert remaining is None

    run_db_test(body)
