"""Service-level tests for the workspaces module — creation atomicity,
the owner invariant, RBAC cache invalidation, audit logging, and every
lifecycle transition. Real Postgres + real Redis (see
app/modules/auth/tests/test_refresh_service.py for the same integration
approach and why `app.db.redis.redis_client` is safe to use directly
inside `run_db_test` bodies — tests/db.py disposes it the same way it
already disposes the SQLAlchemy engine).
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.db import run_db_test

from app.core.security import hash_password
from app.db.redis import redis_client
from app.modules.auth.models import User, UserStatus
from app.modules.workspaces import rbac, service
from app.modules.workspaces.exceptions import (
    CannotRemoveLastOwnerError,
    InsufficientPermissionError,
    InvalidRoleError,
    MembershipNotFoundError,
)
from app.modules.workspaces.models import (
    AuditLog,
    Membership,
    MembershipStatus,
    Role,
    RoleName,
    Workspace,
    WorkspaceStatus,
)
from app.modules.workspaces.schemas import CreateWorkspaceRequest, UpdateWorkspaceSettingsRequest


async def _make_active_user(session: AsyncSession, **overrides: object) -> User:
    defaults: dict[str, object] = {
        "email": f"user-{uuid.uuid4().hex[:8]}@example.com",
        "password_hash": hash_password("a-strong-password"),
        "display_name": "Test User",
        "status": UserStatus.ACTIVE,
        "email_verified_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    user = User(**defaults)  # type: ignore[arg-type]
    session.add(user)
    await session.flush()
    return user


async def _get_role(session: AsyncSession, name: RoleName) -> Role:
    return (await session.execute(select(Role).where(Role.name == name))).scalar_one()


async def _create_workspace(
    session: AsyncSession, owner_id: uuid.UUID, name: str = "Acme Corp"
) -> tuple[Workspace, Membership]:
    return await service.create_workspace(
        session, redis_client, owner_id, CreateWorkspaceRequest(name=name)
    )


async def _add_member(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID, role_name: RoleName
) -> Membership:
    role = await _get_role(session, role_name)
    membership = Membership(workspace_id=workspace_id, user_id=user_id, role_id=role.id)
    session.add(membership)
    await session.commit()
    await session.refresh(membership)
    return membership


# ---------------------------------------------------------------------------
# Workspace creation
# ---------------------------------------------------------------------------


def test_create_workspace_creates_workspace_membership_and_settings_atomically() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)

        workspace, membership = await _create_workspace(session, owner.id)

        assert workspace.status == WorkspaceStatus.ACTIVE
        assert membership.workspace_id == workspace.id
        assert membership.user_id == owner.id
        assert membership.role.name == RoleName.OWNER
        settings = await service.get_workspace_settings(session, workspace.id)
        assert settings.workspace_id == workspace.id
        assert settings.allowed_file_types == ["pdf", "docx", "txt", "md"]
        assert settings.max_document_size_mb == 50

    run_db_test(body)


def test_create_workspace_founding_membership_has_owner_role() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        _, membership = await _create_workspace(session, owner.id)
        assert membership.role.name == RoleName.OWNER
        assert membership.status == MembershipStatus.ACTIVE

    run_db_test(body)


def test_create_workspace_derives_unique_slug_server_side() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id, name="Acme Corp!!")
        assert workspace.slug  # non-empty
        assert workspace.slug == workspace.slug.lower()
        assert not workspace.slug.startswith("-")
        assert not workspace.slug.endswith("-")
        assert "--" not in workspace.slug

    run_db_test(body)


def test_create_workspace_slug_collision_is_resolved_not_rejected() -> None:
    async def body(session: AsyncSession) -> None:
        owner1 = await _make_active_user(session)
        owner2 = await _make_active_user(session)

        first, _ = await _create_workspace(session, owner1.id, name="Duplicate Name")
        second, _ = await _create_workspace(session, owner2.id, name="Duplicate Name")

        assert first.slug != second.slug
        assert first.slug == "duplicate-name"
        assert second.slug.startswith("duplicate-name-")

    run_db_test(body)


def test_create_workspace_name_is_normalized() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id, name="  Acme   Corp  ")
        assert workspace.name == "Acme Corp"

    run_db_test(body)


# ---------------------------------------------------------------------------
# Workspace list / read
# ---------------------------------------------------------------------------


def test_list_workspaces_returns_only_workspaces_with_active_membership() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _make_active_user(session)
        other = await _make_active_user(session)
        mine, _ = await _create_workspace(session, user.id, name="Mine")
        await _create_workspace(session, other.id, name="Not Mine")

        workspaces, _ = await service.list_workspaces_for_user(
            session, user.id, cursor=None, limit=20
        )

        assert [w.id for w in workspaces] == [mine.id]

    run_db_test(body)


def test_list_workspaces_excludes_removed_membership() -> None:
    async def body(session: AsyncSession) -> None:
        user = await _make_active_user(session)
        workspace, membership = await _create_workspace(session, user.id)

        membership.status = MembershipStatus.REMOVED
        membership.removed_at = datetime.now(UTC)
        await session.commit()

        workspaces, _ = await service.list_workspaces_for_user(
            session, user.id, cursor=None, limit=20
        )
        assert workspace.id not in [w.id for w in workspaces]

    run_db_test(body)


def test_get_workspace_returns_details() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)

        fetched = await service.get_workspace(session, workspace.id)
        assert fetched.id == workspace.id
        assert fetched.name == workspace.name

    run_db_test(body)


# ---------------------------------------------------------------------------
# Workspace update / archive / restore / delete
# ---------------------------------------------------------------------------


def test_update_workspace_name() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)

        updated = await service.update_workspace_name(session, workspace.id, "New Name")
        assert updated.name == "New Name"
        assert updated.slug == workspace.slug  # never changes via update

    run_db_test(body)


def test_archive_then_restore_workspace() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)

        archived = await service.archive_workspace(session, workspace.id)
        assert archived.status == WorkspaceStatus.ARCHIVED
        assert archived.archived_at is not None

        restored = await service.restore_workspace(session, workspace.id)
        assert restored.status == WorkspaceStatus.ACTIVE
        assert restored.archived_at is None

    run_db_test(body)


def test_soft_delete_workspace_does_not_physically_remove_it() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)

        deleted = await service.soft_delete_workspace(session, redis_client, workspace.id)
        assert deleted.status == WorkspaceStatus.DELETED
        assert deleted.deleted_at is not None

        # The row itself is still there — a raw, unscoped fetch finds it.
        still_there = (
            await session.execute(select(Workspace).where(Workspace.id == workspace.id))
        ).scalar_one_or_none()
        assert still_there is not None

    run_db_test(body)


def test_deleted_workspace_no_longer_authorizes_its_former_owner() -> None:
    """The frozen invariant "no active Membership for a deleted
    Workspace" — enforced at the RBAC layer (see rbac.py) rather than by
    bulk-updating Membership rows at delete time."""

    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        await service.soft_delete_workspace(session, redis_client, workspace.id)

        membership = await rbac.get_active_membership(
            session, redis_client, user_id=owner.id, workspace_id=workspace.id
        )
        assert membership is None

    run_db_test(body)


# ---------------------------------------------------------------------------
# Workspace settings
# ---------------------------------------------------------------------------


def test_update_workspace_settings_applies_only_provided_fields() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)

        updated = await service.update_workspace_settings(
            session,
            workspace.id,
            owner.id,
            UpdateWorkspaceSettingsRequest(max_document_size_mb=100),
        )
        assert updated.max_document_size_mb == 100
        assert updated.allowed_file_types == ["pdf", "docx", "txt", "md"]  # untouched

    run_db_test(body)


def test_update_workspace_settings_retention_change_writes_audit_log() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)

        await service.update_workspace_settings(
            session,
            workspace.id,
            owner.id,
            UpdateWorkspaceSettingsRequest(document_retention_days=90),
        )

        entries = (
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.workspace_id == workspace.id,
                        AuditLog.action == "workspace_settings.retention_changed",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(entries) == 1
        assert entries[0].actor_user_id == owner.id
        assert entries[0].metadata_["after_document_retention_days"] == 90

    run_db_test(body)


def test_update_workspace_settings_non_retention_change_writes_no_audit_log() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)

        await service.update_workspace_settings(
            session, workspace.id, owner.id, UpdateWorkspaceSettingsRequest(max_document_size_mb=75)
        )

        entries = (
            (await session.execute(select(AuditLog).where(AuditLog.workspace_id == workspace.id)))
            .scalars()
            .all()
        )
        assert entries == []

    run_db_test(body)


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


def test_list_members_hides_email_for_low_rank_caller() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)

        entries, _ = await service.list_members(
            session,
            workspace.id,
            caller_rank=rbac.ROLE_RANK[RoleName.VIEWER],
            cursor=None,
            limit=20,
        )
        assert entries[0].user.email is None

    run_db_test(body)


def test_list_members_shows_email_for_admin_caller() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)

        entries, _ = await service.list_members(
            session, workspace.id, caller_rank=rbac.ROLE_RANK[RoleName.ADMIN], cursor=None, limit=20
        )
        assert entries[0].user.email == owner.email

    run_db_test(body)


def test_list_members_never_returns_removed_memberships() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        other = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        membership = await _add_member(session, workspace.id, other.id, RoleName.MEMBER)

        await service.remove_member(session, redis_client, workspace.id, membership.id, owner.id)

        entries, _ = await service.list_members(
            session, workspace.id, caller_rank=rbac.ROLE_RANK[RoleName.OWNER], cursor=None, limit=20
        )
        assert other.id not in [e.user.id for e in entries]

    run_db_test(body)


# ---------------------------------------------------------------------------
# Role changes
# ---------------------------------------------------------------------------


def test_admin_can_change_member_role() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        target = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        membership = await _add_member(session, workspace.id, target.id, RoleName.MEMBER)
        admin_role = await _get_role(session, RoleName.ADMIN)

        updated = await service.change_member_role(
            session, redis_client, workspace.id, membership.id, owner.id, admin_role.id
        )
        assert updated.role.name == RoleName.ADMIN

    run_db_test(body)


def test_role_change_writes_audit_log_with_before_and_after() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        target = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        membership = await _add_member(session, workspace.id, target.id, RoleName.MEMBER)
        admin_role = await _get_role(session, RoleName.ADMIN)

        await service.change_member_role(
            session, redis_client, workspace.id, membership.id, owner.id, admin_role.id
        )

        entry = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.workspace_id == workspace.id,
                    AuditLog.action == "membership.role_changed",
                )
            )
        ).scalar_one()
        assert entry.metadata_["before_role"] == "member"
        assert entry.metadata_["after_role"] == "admin"
        assert entry.metadata_["target_user_id"] == str(target.id)

    run_db_test(body)


def test_role_change_invalidates_rbac_cache() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        target = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        membership = await _add_member(session, workspace.id, target.id, RoleName.MEMBER)

        # Prime the cache with the *old* role.
        cached_before = await rbac.get_active_membership(
            session, redis_client, user_id=target.id, workspace_id=workspace.id
        )
        assert cached_before is not None
        assert cached_before.role_name == RoleName.MEMBER

        admin_role = await _get_role(session, RoleName.ADMIN)
        await service.change_member_role(
            session, redis_client, workspace.id, membership.id, owner.id, admin_role.id
        )

        cached_after = await rbac.get_active_membership(
            session, redis_client, user_id=target.id, workspace_id=workspace.id
        )
        assert cached_after is not None
        assert cached_after.role_name == RoleName.ADMIN  # not the stale cached MEMBER

    run_db_test(body)


def test_non_admin_cannot_change_role_via_service_precondition() -> None:
    """The service function itself doesn't re-check the caller's rank
    (that's the RBAC dependency's job, already run before this function
    is ever called — see service.py's module docstring) — this test
    instead proves `InvalidRoleError` for a role_id that doesn't
    resolve to a real system role, one of the two validations this
    function *does* own."""

    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        target = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        membership = await _add_member(session, workspace.id, target.id, RoleName.MEMBER)

        with pytest.raises(InvalidRoleError):
            await service.change_member_role(
                session, redis_client, workspace.id, membership.id, owner.id, uuid.uuid4()
            )

    run_db_test(body)


def test_cannot_change_own_role() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, founding_membership = await _create_workspace(session, owner.id)
        member_role = await _get_role(session, RoleName.MEMBER)

        with pytest.raises(InsufficientPermissionError):
            await service.change_member_role(
                session,
                redis_client,
                workspace.id,
                founding_membership.id,
                owner.id,
                member_role.id,
            )

    run_db_test(body)


def test_membership_not_found_for_wrong_workspace() -> None:
    async def body(session: AsyncSession) -> None:
        owner_a = await _make_active_user(session)
        owner_b = await _make_active_user(session)
        workspace_a, _ = await _create_workspace(session, owner_a.id)
        _, membership_b = await _create_workspace(session, owner_b.id)
        member_role = await _get_role(session, RoleName.MEMBER)

        # workspace_a's owner tries to change a membership that belongs
        # to workspace_b.
        with pytest.raises(MembershipNotFoundError):
            await service.change_member_role(
                session, redis_client, workspace_a.id, membership_b.id, owner_a.id, member_role.id
            )

    run_db_test(body)


# ---------------------------------------------------------------------------
# Owner invariant
# ---------------------------------------------------------------------------


def test_workspace_starts_with_exactly_one_owner() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)

        count = await service._count_active_owners(session, workspace.id)
        assert count == 1

    run_db_test(body)


def test_cannot_demote_the_last_owner() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        admin = await _make_active_user(session)
        workspace, founding_membership = await _create_workspace(session, owner.id)
        # `admin` changes `owner`'s role — a second party, so the
        # self-change guard doesn't interfere with testing the owner
        # invariant specifically.
        await _add_member(session, workspace.id, admin.id, RoleName.ADMIN)
        member_role = await _get_role(session, RoleName.MEMBER)

        with pytest.raises(CannotRemoveLastOwnerError):
            await service.change_member_role(
                session,
                redis_client,
                workspace.id,
                founding_membership.id,
                admin.id,
                member_role.id,
            )

    run_db_test(body)


def test_cannot_remove_the_last_owner() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        admin = await _make_active_user(session)
        workspace, founding_membership = await _create_workspace(session, owner.id)
        await _add_member(session, workspace.id, admin.id, RoleName.ADMIN)

        with pytest.raises(CannotRemoveLastOwnerError):
            await service.remove_member(
                session, redis_client, workspace.id, founding_membership.id, admin.id
            )

    run_db_test(body)


def test_one_owner_can_be_demoted_when_another_owner_remains() -> None:
    async def body(session: AsyncSession) -> None:
        owner1 = await _make_active_user(session)
        owner2 = await _make_active_user(session)
        workspace, founding_membership = await _create_workspace(session, owner1.id)
        second_owner_membership = await _add_member(
            session, workspace.id, owner2.id, RoleName.OWNER
        )
        member_role = await _get_role(session, RoleName.MEMBER)

        # owner2 demotes owner1 — two owners exist, so this must succeed.
        updated = await service.change_member_role(
            session,
            redis_client,
            workspace.id,
            founding_membership.id,
            owner2.id,
            member_role.id,
        )
        assert updated.role.name == RoleName.MEMBER

        # And the remaining owner (owner2) is still there.
        remaining_owner_count = await service._count_active_owners(session, workspace.id)
        assert remaining_owner_count == 1
        assert second_owner_membership.role_id == (await _get_role(session, RoleName.OWNER)).id

    run_db_test(body)


def test_removing_non_owner_member_succeeds() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        target = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        membership = await _add_member(session, workspace.id, target.id, RoleName.MEMBER)

        await service.remove_member(session, redis_client, workspace.id, membership.id, owner.id)

        fetched = (
            await session.execute(select(Membership).where(Membership.id == membership.id))
        ).scalar_one()
        assert fetched.status == MembershipStatus.REMOVED
        assert fetched.removed_at is not None

    run_db_test(body)


def test_removed_membership_no_longer_authorizes_access() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        target = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        membership = await _add_member(session, workspace.id, target.id, RoleName.MEMBER)

        await service.remove_member(session, redis_client, workspace.id, membership.id, owner.id)

        active = await rbac.get_active_membership(
            session, redis_client, user_id=target.id, workspace_id=workspace.id
        )
        assert active is None

    run_db_test(body)


def test_cannot_remove_self_via_admin_endpoint() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        admin = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        admin_membership = await _add_member(session, workspace.id, admin.id, RoleName.ADMIN)

        with pytest.raises(InsufficientPermissionError):
            await service.remove_member(
                session, redis_client, workspace.id, admin_membership.id, admin.id
            )

    run_db_test(body)
