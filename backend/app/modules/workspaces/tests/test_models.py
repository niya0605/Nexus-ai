"""Model tests for Role and Invitation.

Covers table creation, uniqueness, nullable constraints, and
relationship integrity — nothing else. No invitation-sending, no
acceptance flow: this sprint is data shape only.

**S1F note:** `roles` is no longer an empty table tests can freely
insert throwaway rows into — the migration (alembic/versions/
20260814_create_workspace_tables.py) seeds the four real system-defined
roles, and `Role.name`'s CHECK constraint only allows those same four
values. Every test below that needs "a role" now fetches one of the
real seeded rows (`_get_role`) instead of inserting a new one; the two
tests that specifically exercise Role's own insert-time constraints
(seed-data shape, uniqueness) were rewritten to match, not deleted.

Requires a real, reachable PostgreSQL matching the backend's `.env`
configuration — see backend/tests/db.py.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from tests.db import run_db_test

from app.modules.auth.models import User
from app.modules.workspaces.models import Invitation, InvitationStatus, Role, RoleName, Workspace


async def _get_role(session: AsyncSession, name: RoleName) -> Role:
    """Fetch one of the four seeded system roles by name — see this
    module's docstring for why tests no longer insert their own."""
    return (await session.execute(select(Role).where(Role.name == name))).scalar_one()


def _make_user() -> User:
    return User(
        email=f"user-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="not-a-real-hash",
        display_name="Test User",
    )


def _make_workspace(**overrides: object) -> Workspace:
    """S1F resolved Sprint 1A's documented `Invitation.workspace_id`
    deviation into a real FK — every Invitation fixture below now needs
    an actual Workspace row to reference, which this codebase's Sprint
    1A tests never needed before that FK existed."""
    unique = uuid.uuid4().hex[:8]
    defaults: dict[str, object] = {"name": f"Workspace {unique}", "slug": f"workspace-{unique}"}
    defaults.update(overrides)
    return Workspace(**defaults)  # type: ignore[arg-type]


def _make_invitation(
    role_id: uuid.UUID, inviter_id: uuid.UUID, workspace_id: uuid.UUID, **overrides: object
) -> Invitation:
    defaults: dict[str, object] = {
        "workspace_id": workspace_id,
        "invited_email": f"invitee-{uuid.uuid4().hex[:8]}@example.com",
        "role_id": role_id,
        "invited_by_user_id": inviter_id,
        "token_hash": f"token-{uuid.uuid4().hex}",
        "expires_at": datetime.now(UTC) + timedelta(days=7),
    }
    defaults.update(overrides)
    return Invitation(**defaults)  # type: ignore[arg-type]


def test_seeded_roles_have_correct_shape() -> None:
    """S1F: the migration seeds exactly the four system-defined MVP
    roles. Replaces the old "insert a throwaway role and fetch it"
    test — that's no longer possible (see module docstring) — with a
    genuine check of the real seed data every environment this
    migration runs in actually gets."""

    async def body(session: AsyncSession) -> None:
        member = await _get_role(session, RoleName.MEMBER)
        assert member.is_system_defined is True
        assert member.capability_set  # non-empty
        assert isinstance(member.capability_set, list)

        all_roles = (await session.execute(select(Role.name))).scalars().all()
        assert set(all_roles) == {
            RoleName.OWNER,
            RoleName.ADMIN,
            RoleName.MEMBER,
            RoleName.VIEWER,
        }

    run_db_test(body)


def test_role_name_uniqueness() -> None:
    """The unique constraint on `Role.name` — proven against a name
    that's already taken by seed data, rather than inserting two rows
    ourselves (the CHECK constraint only allows the same four values
    seed data already occupies, so a second insert of *any* valid name
    is definitionally a duplicate now)."""

    async def body(session: AsyncSession) -> None:
        session.add(
            Role(name=RoleName.ADMIN, description="A second admin role", capability_set=["x"])
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    run_db_test(body)


def test_create_invitation_with_relationships() -> None:
    async def body(session: AsyncSession) -> None:
        role = await _get_role(session, RoleName.VIEWER)
        inviter = _make_user()
        workspace = _make_workspace()
        session.add_all([inviter, workspace])
        await session.flush()

        invitation = _make_invitation(role.id, inviter.id, workspace.id)
        session.add(invitation)
        await session.flush()
        await session.refresh(invitation, attribute_names=["role", "invited_by"])

        assert invitation.status == InvitationStatus.PENDING  # default applied
        assert invitation.role_id == role.id
        assert invitation.role.name == RoleName.VIEWER
        assert invitation.invited_by.id == inviter.id

    run_db_test(body)


def test_pending_invitation_uniqueness_per_workspace_and_email() -> None:
    async def body(session: AsyncSession) -> None:
        role = await _get_role(session, RoleName.MEMBER)
        inviter = _make_user()
        workspace = _make_workspace()
        session.add_all([inviter, workspace])
        await session.flush()

        workspace_id = workspace.id
        session.add(
            _make_invitation(
                role.id, inviter.id, workspace_id=workspace_id, invited_email="dup@example.com"
            )
        )
        await session.flush()

        # Second *pending* invitation for the same (workspace, email) —
        # must collide with the partial unique index.
        session.add(
            _make_invitation(
                role.id, inviter.id, workspace_id=workspace_id, invited_email="dup@example.com"
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    run_db_test(body)


def test_resolved_invitation_does_not_block_a_new_pending_one() -> None:
    async def body(session: AsyncSession) -> None:
        role = await _get_role(session, RoleName.MEMBER)
        inviter = _make_user()
        workspace = _make_workspace()
        session.add_all([inviter, workspace])
        await session.flush()

        workspace_id = workspace.id
        resolved = _make_invitation(
            role.id,
            inviter.id,
            workspace_id=workspace_id,
            invited_email="resolved@example.com",
            status=InvitationStatus.ACCEPTED,
        )
        session.add(resolved)
        await session.flush()

        # A *pending* invitation for the same pair is allowed, since the
        # partial unique index only applies to status = 'pending'.
        new_pending = _make_invitation(
            role.id, inviter.id, workspace_id=workspace_id, invited_email="resolved@example.com"
        )
        session.add(new_pending)
        await session.flush()  # should NOT raise

    run_db_test(body)


def test_role_cannot_be_deleted_while_referenced_by_invitation() -> None:
    async def body(session: AsyncSession) -> None:
        role = await _get_role(session, RoleName.OWNER)
        inviter = _make_user()
        workspace = _make_workspace()
        session.add_all([inviter, workspace])
        await session.flush()

        session.add(_make_invitation(role.id, inviter.id, workspace.id))
        await session.flush()

        await session.delete(role)
        with pytest.raises(IntegrityError):
            await session.flush()

    run_db_test(body)
