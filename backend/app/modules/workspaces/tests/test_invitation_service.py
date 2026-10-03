"""Service-level tests for S1G's invitation lifecycle — creation
(including the replace-pending and role-validation behavior), listing,
resend, revoke, the public token lookup, and the atomic accept
transaction (including its two documented gap-fill paths: an already-
active member, and the true concurrent-race path this synchronous test
suite approximates via a pre-existing competing row rather than real
threads).

Real Postgres + real Redis, same `run_db_test` approach as
test_workspace_service.py. RBAC permission tiers (Admin+ required to
create/list/resend/revoke) are enforced by
`app.modules.workspaces.dependencies.RequireRole`, a FastAPI dependency
— not by these service functions themselves — so "Member cannot
invite"-style checks belong in test_invitation_api.py, not here, exactly
the same division test_workspace_service.py already established for
S1F's own RBAC tiers.
"""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.db import run_db_test

from app.core.security import hash_password, hash_refresh_token
from app.db.redis import redis_client
from app.modules.auth.exceptions import TokenInvalidError
from app.modules.auth.models import User, UserStatus
from app.modules.workspaces import service
from app.modules.workspaces.exceptions import (
    AlreadyMemberError,
    EmailMismatchError,
    InvalidRoleError,
    InvitationAlreadyResolvedError,
    InvitationExpiredError,
    InvitationNotFoundError,
    WorkspaceNotFoundError,
)
from app.modules.workspaces.models import (
    Invitation,
    InvitationStatus,
    Membership,
    MembershipStatus,
    Role,
    RoleName,
    Workspace,
)
from app.modules.workspaces.schemas import CreateInvitationRequest, CreateWorkspaceRequest


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


async def _invite(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    actor_id: uuid.UUID,
    role: RoleName,
    email: str | None = None,
) -> Invitation:
    role_row = await _get_role(session, role)
    payload = CreateInvitationRequest(
        email=email or f"invitee-{uuid.uuid4().hex[:8]}@example.com", role_id=role_row.id
    )
    return await service.create_invitation(session, workspace_id, actor_id, payload)


def _mailpit_available() -> bool:
    try:
        httpx.get("http://localhost:8025/api/v1/messages", timeout=1).raise_for_status()
        return True
    except Exception:  # noqa: BLE001 — any failure means "treat as unavailable, skip"
        return False


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_invitation_is_pending_with_hashed_token() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)

        invitation = await _invite(session, workspace.id, owner.id, RoleName.MEMBER)

        assert invitation.status == InvitationStatus.PENDING
        assert invitation.workspace_id == workspace.id
        assert invitation.resolved_at is None
        assert invitation.expires_at > datetime.now(UTC)
        # Hashed, not raw: a SHA-256 hex digest is 64 lowercase-hex
        # characters — structurally impossible for `secrets.token_urlsafe`
        # output (base64-urlsafe alphabet, ~43 chars, `-`/`_` allowed) to
        # equal, so this also proves the raw token itself was never
        # persisted into `token_hash`.
        assert len(invitation.token_hash) == 64
        assert all(c in "0123456789abcdef" for c in invitation.token_hash)

    run_db_test(body)


def test_create_invitation_rejects_non_system_role() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)

        payload = CreateInvitationRequest(email="someone@example.com", role_id=uuid.uuid4())
        with pytest.raises(InvalidRoleError):
            await service.create_invitation(session, workspace.id, owner.id, payload)

    run_db_test(body)


def test_create_invitation_rejects_already_active_member() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)

        with pytest.raises(AlreadyMemberError):
            await _invite(session, workspace.id, owner.id, RoleName.MEMBER, email=owner.email)

    run_db_test(body)


def test_create_invitation_normalizes_email() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        role = await _get_role(session, RoleName.MEMBER)

        payload = CreateInvitationRequest(email="  MixedCase@Example.COM  ", role_id=role.id)
        invitation = await service.create_invitation(session, workspace.id, owner.id, payload)

        assert invitation.invited_email == "mixedcase@example.com"

    run_db_test(body)


def test_create_invitation_replaces_existing_pending_invitation() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        email = f"repeat-{uuid.uuid4().hex[:8]}@example.com"

        first = await _invite(session, workspace.id, owner.id, RoleName.VIEWER, email=email)
        second = await _invite(session, workspace.id, owner.id, RoleName.ADMIN, email=email)

        assert first.id != second.id
        assert second.status == InvitationStatus.PENDING
        assert second.role.name == RoleName.ADMIN

        await session.refresh(first)
        assert first.status == InvitationStatus.REVOKED
        assert first.resolved_at is not None

        # Only one *pending* invitation exists for this (workspace, email).
        pending_rows = (
            (
                await session.execute(
                    select(Invitation).where(
                        Invitation.workspace_id == workspace.id,
                        Invitation.invited_email == email,
                        Invitation.status == InvitationStatus.PENDING,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(pending_rows) == 1

    run_db_test(body)


@pytest.mark.skipif(
    not _mailpit_available(), reason="Mailpit not reachable at localhost:8025 — skipping"
)
def test_create_invitation_sends_email_via_mailpit() -> None:
    async def body(session: AsyncSession) -> None:
        async with httpx.AsyncClient() as http:
            await http.delete("http://localhost:8025/api/v1/messages", timeout=2)

            owner = await _make_active_user(session, display_name="Inviting Owner")
            workspace, _ = await _create_workspace(session, owner.id, name="Mailpit Test Workspace")
            email = f"invitee-{uuid.uuid4().hex[:8]}@example.com"

            await _invite(session, workspace.id, owner.id, RoleName.MEMBER, email=email)

            response = await http.get(
                "http://localhost:8025/api/v1/messages", params={"query": f"to:{email}"}, timeout=3
            )
            data = response.json()
            assert data["total"] >= 1
            assert "Mailpit Test Workspace" in data["messages"][0]["Subject"]

            await http.delete("http://localhost:8025/api/v1/messages", timeout=2)

    run_db_test(body)


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def test_list_pending_invitations_scoped_to_workspace_and_pending_only() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace_a, _ = await _create_workspace(session, owner.id, name="Workspace A")
        workspace_b, _ = await _create_workspace(session, owner.id, name="Workspace B")

        in_a = await _invite(session, workspace_a.id, owner.id, RoleName.MEMBER)
        await _invite(session, workspace_b.id, owner.id, RoleName.MEMBER)

        revoked = await _invite(session, workspace_a.id, owner.id, RoleName.VIEWER)
        await service.revoke_invitation(session, workspace_a.id, revoked.id)

        page, _ = await service.list_pending_invitations(
            session, workspace_a.id, cursor=None, limit=20
        )

        ids = {i.id for i in page}
        assert ids == {in_a.id}

    run_db_test(body)


# ---------------------------------------------------------------------------
# Resend
# ---------------------------------------------------------------------------


def test_resend_invitation_replaces_token_and_extends_expiry() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        invitation = await _invite(session, workspace.id, owner.id, RoleName.MEMBER)

        old_token_hash = invitation.token_hash
        old_expires_at = invitation.expires_at

        resent = await service.resend_invitation(session, workspace.id, invitation.id)

        assert resent.id == invitation.id  # same row, not a new invitation
        assert resent.token_hash != old_token_hash
        assert resent.expires_at >= old_expires_at
        assert resent.status == InvitationStatus.PENDING

    run_db_test(body)


def test_resend_invitation_old_token_no_longer_resolves() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        invitation = await _invite(session, workspace.id, owner.id, RoleName.MEMBER)
        old_token_hash = invitation.token_hash

        await service.resend_invitation(session, workspace.id, invitation.id)

        # No stored row has the *old* hash anymore.
        still_present = (
            await session.execute(select(Invitation).where(Invitation.token_hash == old_token_hash))
        ).scalar_one_or_none()
        assert still_present is None

    run_db_test(body)


def test_resend_invitation_rejects_already_resolved() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        invitation = await _invite(session, workspace.id, owner.id, RoleName.MEMBER)
        await service.revoke_invitation(session, workspace.id, invitation.id)

        with pytest.raises(InvitationAlreadyResolvedError):
            await service.resend_invitation(session, workspace.id, invitation.id)

    run_db_test(body)


def test_resend_invitation_wrong_workspace_not_found() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace_a, _ = await _create_workspace(session, owner.id, name="Workspace A")
        workspace_b, _ = await _create_workspace(session, owner.id, name="Workspace B")
        invitation = await _invite(session, workspace_a.id, owner.id, RoleName.MEMBER)

        with pytest.raises(InvitationNotFoundError):
            await service.resend_invitation(session, workspace_b.id, invitation.id)

    run_db_test(body)


# ---------------------------------------------------------------------------
# Revoke
# ---------------------------------------------------------------------------


def test_revoke_invitation_transitions_and_sets_resolved_at() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        invitation = await _invite(session, workspace.id, owner.id, RoleName.MEMBER)

        await service.revoke_invitation(session, workspace.id, invitation.id)
        await session.refresh(invitation)

        assert invitation.status == InvitationStatus.REVOKED
        assert invitation.resolved_at is not None

    run_db_test(body)


def test_revoke_invitation_token_becomes_unusable() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        invitation = await _invite(session, workspace.id, owner.id, RoleName.MEMBER)
        token_hash = invitation.token_hash

        await service.revoke_invitation(session, workspace.id, invitation.id)

        # `get_invitation_by_token` requires a *raw* token, which this
        # test never had (create_invitation doesn't return it — see its
        # own docstring). Simulating "the token is presented" directly
        # against the stored hash instead: the row is found, but no
        # longer pending.
        found = (
            await session.execute(select(Invitation).where(Invitation.token_hash == token_hash))
        ).scalar_one()
        assert found.status == InvitationStatus.REVOKED

    run_db_test(body)


def test_revoke_invitation_already_resolved_not_mutated_again() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        invitation = await _invite(session, workspace.id, owner.id, RoleName.MEMBER)
        await service.revoke_invitation(session, workspace.id, invitation.id)
        await session.refresh(invitation)
        first_resolved_at = invitation.resolved_at

        with pytest.raises(InvitationAlreadyResolvedError):
            await service.revoke_invitation(session, workspace.id, invitation.id)

        await session.refresh(invitation)
        assert invitation.resolved_at == first_resolved_at  # untouched by the second call

    run_db_test(body)


# ---------------------------------------------------------------------------
# Public token lookup
# ---------------------------------------------------------------------------


def test_get_invitation_by_token_invalid_token_raises() -> None:
    async def body(session: AsyncSession) -> None:
        with pytest.raises(TokenInvalidError):
            await service.get_invitation_by_token(session, "not-a-real-token")

    run_db_test(body)


def test_get_invitation_by_token_expired_lazily_transitions_and_raises() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        invitation = await _invite(session, workspace.id, owner.id, RoleName.MEMBER)

        raw_token = "test-raw-token-value"
        invitation.token_hash = hash_refresh_token(raw_token)
        invitation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

        with pytest.raises(InvitationExpiredError):
            await service.get_invitation_by_token(session, raw_token)

        await session.refresh(invitation)
        assert invitation.status == InvitationStatus.EXPIRED
        assert invitation.resolved_at is not None

    run_db_test(body)


def test_get_invitation_by_token_already_resolved_raises() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        invitation = await _invite(session, workspace.id, owner.id, RoleName.MEMBER)

        raw_token = "test-raw-token-value-2"
        invitation.token_hash = hash_refresh_token(raw_token)
        await session.commit()
        await service.revoke_invitation(session, workspace.id, invitation.id)

        with pytest.raises(InvitationAlreadyResolvedError):
            await service.get_invitation_by_token(session, raw_token)

    run_db_test(body)


# ---------------------------------------------------------------------------
# Accept — atomicity, Membership creation, owner invariant
# ---------------------------------------------------------------------------


async def _invite_with_known_token(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    actor_id: uuid.UUID,
    role: RoleName,
    email: str,
    raw_token: str = "known-raw-token",
) -> Invitation:
    invitation = await _invite(session, workspace_id, actor_id, role, email=email)
    invitation.token_hash = hash_refresh_token(raw_token)
    await session.commit()
    await session.refresh(invitation)
    return invitation


def test_accept_invitation_creates_membership_with_invitation_role() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        invitee = await _make_active_user(session)
        raw_token = "accept-test-token-1"
        await _invite_with_known_token(
            session, workspace.id, owner.id, RoleName.ADMIN, invitee.email, raw_token
        )

        membership, created = await service.accept_invitation(
            session, redis_client, raw_token, invitee.id, invitee.email
        )

        assert created is True
        assert membership.workspace_id == workspace.id
        assert membership.user_id == invitee.id
        assert membership.status == MembershipStatus.ACTIVE
        assert membership.role.name == RoleName.ADMIN

    run_db_test(body)


def test_accept_invitation_closes_out_invitation() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        invitee = await _make_active_user(session)
        raw_token = "accept-test-token-2"
        invitation = await _invite_with_known_token(
            session, workspace.id, owner.id, RoleName.MEMBER, invitee.email, raw_token
        )

        await service.accept_invitation(session, redis_client, raw_token, invitee.id, invitee.email)
        await session.refresh(invitation)

        assert invitation.status == InvitationStatus.ACCEPTED
        assert invitation.resolved_at is not None

    run_db_test(body)


def test_accept_invitation_token_unusable_after_accept() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        invitee = await _make_active_user(session)
        raw_token = "accept-test-token-3"
        await _invite_with_known_token(
            session, workspace.id, owner.id, RoleName.MEMBER, invitee.email, raw_token
        )

        await service.accept_invitation(session, redis_client, raw_token, invitee.id, invitee.email)

        with pytest.raises(InvitationAlreadyResolvedError):
            await service.accept_invitation(
                session, redis_client, raw_token, invitee.id, invitee.email
            )

    run_db_test(body)


def test_accept_invitation_email_mismatch_rejected() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        invitee = await _make_active_user(session)
        impostor = await _make_active_user(session)
        raw_token = "accept-test-token-4"
        await _invite_with_known_token(
            session, workspace.id, owner.id, RoleName.MEMBER, invitee.email, raw_token
        )

        with pytest.raises(EmailMismatchError):
            await service.accept_invitation(
                session, redis_client, raw_token, impostor.id, impostor.email
            )

    run_db_test(body)


def test_accept_invitation_deleted_workspace_not_found() -> None:
    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        invitee = await _make_active_user(session)
        raw_token = "accept-test-token-5"
        await _invite_with_known_token(
            session, workspace.id, owner.id, RoleName.MEMBER, invitee.email, raw_token
        )

        await service.soft_delete_workspace(session, redis_client, workspace.id)

        with pytest.raises(WorkspaceNotFoundError):
            await service.accept_invitation(
                session, redis_client, raw_token, invitee.id, invitee.email
            )

    run_db_test(body)


def test_accept_invitation_owner_role_creates_additional_owner_no_cap() -> None:
    """S1F's owner invariant is a *minimum* (>= 1), never a maximum — S1G:
    "if the frozen documents do not impose a maximum Owner count, do not
    invent one." Accepting an Owner-role invitation must simply succeed.
    """

    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        invitee = await _make_active_user(session)
        raw_token = "accept-test-token-6"
        await _invite_with_known_token(
            session, workspace.id, owner.id, RoleName.OWNER, invitee.email, raw_token
        )

        membership, _created = await service.accept_invitation(
            session, redis_client, raw_token, invitee.id, invitee.email
        )
        assert membership.role.name == RoleName.OWNER

        owner_count = (
            (
                await session.execute(
                    select(Membership)
                    .join(Role, Role.id == Membership.role_id)
                    .where(
                        Membership.workspace_id == workspace.id,
                        Role.name == RoleName.OWNER,
                        Membership.status == MembershipStatus.ACTIVE,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(owner_count) == 2  # founding owner + the new one

    run_db_test(body)


def test_accept_invitation_when_already_active_member_does_not_duplicate() -> None:
    """Deterministic reproduction of S1G's race-condition requirement
    ("if a race occurs and another active Membership is created first: do
    not create duplicate Memberships... do not leave the invitation
    falsely marked accepted") via a pre-existing competing row rather
    than real concurrent threads — the practically-testable equivalent of
    the same guarantee; see `accept_invitation`'s own docstring for the
    (structurally identical, but not independently exercised here)
    `IntegrityError`-catch branch this approximates.
    """

    async def body(session: AsyncSession) -> None:
        owner = await _make_active_user(session)
        workspace, _ = await _create_workspace(session, owner.id)
        invitee = await _make_active_user(session)
        raw_token = "accept-test-token-7"
        await _invite_with_known_token(
            session, workspace.id, owner.id, RoleName.ADMIN, invitee.email, raw_token
        )

        # The "someone else already created it first" state.
        viewer_role = await _get_role(session, RoleName.VIEWER)
        pre_existing = Membership(
            workspace_id=workspace.id, user_id=invitee.id, role_id=viewer_role.id
        )
        session.add(pre_existing)
        await session.commit()
        await session.refresh(pre_existing)

        membership, created = await service.accept_invitation(
            session, redis_client, raw_token, invitee.id, invitee.email
        )

        assert created is False
        assert membership.id == pre_existing.id
        assert membership.role.name == RoleName.VIEWER  # unchanged — not silently promoted

        all_active = (
            (
                await session.execute(
                    select(Membership).where(
                        Membership.workspace_id == workspace.id,
                        Membership.user_id == invitee.id,
                        Membership.status == MembershipStatus.ACTIVE,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(all_active) == 1  # no duplicate

        invitation = (
            await session.execute(
                select(Invitation).where(Invitation.token_hash == hash_refresh_token(raw_token))
            )
        ).scalar_one()
        assert invitation.status == InvitationStatus.ACCEPTED  # not left falsely pending

    run_db_test(body)
