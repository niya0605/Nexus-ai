"""Workspace, WorkspaceSettings, and Membership endpoints (S1F).

Every route below delegates its authorization entirely to
`app.modules.workspaces.dependencies` (`require_viewer`/`require_member`/
`require_admin`/`require_owner`) — no route function contains a role
check of its own, per S1F's explicit instruction. Route functions are
named `..._route` specifically because most have an identically-named
service function they call (`create_workspace_route` →
`service.create_workspace`, etc.) — distinct names avoid any ambiguity
about which one a stack trace or import refers to.
"""

import uuid

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import idempotency
from app.core.responses import CursorPage, SuccessEnvelope, cursor_page, envelope
from app.db.dependencies import get_db
from app.db.redis import get_redis
from app.modules.auth.dependencies import get_current_user_id
from app.modules.workspaces import rbac, service
from app.modules.workspaces.dependencies import require_admin, require_owner, require_viewer
from app.modules.workspaces.models import Invitation, Membership
from app.modules.workspaces.schemas import (
    CreateInvitationRequest,
    CreateWorkspaceRequest,
    InvitationPublic,
    MemberEntry,
    MembershipPublic,
    UpdateMembershipRoleRequest,
    UpdateWorkspaceRequest,
    UpdateWorkspaceSettingsRequest,
    WorkspaceCreateData,
    WorkspacePublic,
    WorkspaceSettingsPublic,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

# S1G — idempotency scope name for POST .../invitations (see
# app.core.idempotency's own docstring for why this lives in app.core,
# not this module).
_INVITATION_CREATE_IDEMPOTENCY_SCOPE = "workspace_invitation_create"


def _membership_public(membership: Membership) -> MembershipPublic:
    return MembershipPublic(
        id=membership.id,
        workspace_id=membership.workspace_id,
        user_id=membership.user_id,
        role=membership.role.name.value,
        status=membership.status,
        created_at=membership.created_at,
    )


def _invitation_public(invitation: Invitation) -> InvitationPublic:
    return InvitationPublic(
        id=invitation.id,
        workspace_id=invitation.workspace_id,
        invited_email=invitation.invited_email,
        role=invitation.role.name.value,
        status=invitation.status,
        invited_by_user_id=invitation.invited_by_user_id,
        created_at=invitation.created_at,
        expires_at=invitation.expires_at,
        resolved_at=invitation.resolved_at,
    )


@router.post(
    "",
    response_model=SuccessEnvelope[WorkspaceCreateData],
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_route(
    payload: CreateWorkspaceRequest,
    request: Request,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> SuccessEnvelope[WorkspaceCreateData]:
    """Any authenticated user may create a workspace — no RBAC
    dependency here (there's no workspace to be a member of yet)."""
    workspace, membership = await service.create_workspace(db, redis, current_user_id, payload)
    data = WorkspaceCreateData(
        workspace=WorkspacePublic.model_validate(workspace),
        membership=_membership_public(membership),
    )
    return envelope(data, request)


@router.get("", response_model=CursorPage[WorkspacePublic], status_code=status.HTTP_200_OK)
async def list_workspaces_route(
    request: Request,
    cursor: str | None = None,
    limit: int = service.DEFAULT_PAGE_SIZE,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> CursorPage[WorkspacePublic]:
    workspaces, next_cursor = await service.list_workspaces_for_user(
        db, current_user_id, cursor=cursor, limit=limit
    )
    return cursor_page(
        [WorkspacePublic.model_validate(w) for w in workspaces], next_cursor, request
    )


@router.get(
    "/{workspace_id}",
    response_model=SuccessEnvelope[WorkspacePublic],
    status_code=status.HTTP_200_OK,
)
async def get_workspace_route(
    workspace_id: uuid.UUID,
    request: Request,
    _membership: rbac.ActiveMembership = Depends(require_viewer),
    db: AsyncSession = Depends(get_db),
) -> SuccessEnvelope[WorkspacePublic]:
    workspace = await service.get_workspace(db, workspace_id)
    return envelope(WorkspacePublic.model_validate(workspace), request)


@router.patch(
    "/{workspace_id}",
    response_model=SuccessEnvelope[WorkspacePublic],
    status_code=status.HTTP_200_OK,
)
async def update_workspace_route(
    workspace_id: uuid.UUID,
    payload: UpdateWorkspaceRequest,
    request: Request,
    _membership: rbac.ActiveMembership = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SuccessEnvelope[WorkspacePublic]:
    workspace = await service.update_workspace_name(db, workspace_id, payload.name)
    return envelope(WorkspacePublic.model_validate(workspace), request)


@router.post(
    "/{workspace_id}/archive",
    response_model=SuccessEnvelope[WorkspacePublic],
    status_code=status.HTTP_200_OK,
)
async def archive_workspace_route(
    workspace_id: uuid.UUID,
    request: Request,
    _membership: rbac.ActiveMembership = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> SuccessEnvelope[WorkspacePublic]:
    workspace = await service.archive_workspace(db, workspace_id)
    return envelope(WorkspacePublic.model_validate(workspace), request)


@router.post(
    "/{workspace_id}/restore",
    response_model=SuccessEnvelope[WorkspacePublic],
    status_code=status.HTTP_200_OK,
)
async def restore_workspace_route(
    workspace_id: uuid.UUID,
    request: Request,
    _membership: rbac.ActiveMembership = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> SuccessEnvelope[WorkspacePublic]:
    workspace = await service.restore_workspace(db, workspace_id)
    return envelope(WorkspacePublic.model_validate(workspace), request)


@router.delete(
    "/{workspace_id}",
    response_model=SuccessEnvelope[WorkspacePublic],
    status_code=status.HTTP_202_ACCEPTED,
)
async def delete_workspace_route(
    workspace_id: uuid.UUID,
    request: Request,
    _membership: rbac.ActiveMembership = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> SuccessEnvelope[WorkspacePublic]:
    """A soft-delete request — 202 Accepted, per the frozen contract's
    grace-window semantics (this is not synchronous physical deletion)."""
    workspace = await service.soft_delete_workspace(db, redis, workspace_id)
    return envelope(WorkspacePublic.model_validate(workspace), request)


@router.get(
    "/{workspace_id}/settings",
    response_model=SuccessEnvelope[WorkspaceSettingsPublic],
    status_code=status.HTTP_200_OK,
)
async def get_workspace_settings_route(
    workspace_id: uuid.UUID,
    request: Request,
    _membership: rbac.ActiveMembership = Depends(require_viewer),
    db: AsyncSession = Depends(get_db),
) -> SuccessEnvelope[WorkspaceSettingsPublic]:
    settings = await service.get_workspace_settings(db, workspace_id)
    return envelope(WorkspaceSettingsPublic.model_validate(settings), request)


@router.patch(
    "/{workspace_id}/settings",
    response_model=SuccessEnvelope[WorkspaceSettingsPublic],
    status_code=status.HTTP_200_OK,
)
async def update_workspace_settings_route(
    workspace_id: uuid.UUID,
    payload: UpdateWorkspaceSettingsRequest,
    request: Request,
    _membership: rbac.ActiveMembership = Depends(require_admin),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> SuccessEnvelope[WorkspaceSettingsPublic]:
    settings = await service.update_workspace_settings(db, workspace_id, current_user_id, payload)
    return envelope(WorkspaceSettingsPublic.model_validate(settings), request)


@router.get(
    "/{workspace_id}/members",
    response_model=CursorPage[MemberEntry],
    status_code=status.HTTP_200_OK,
)
async def list_members_route(
    workspace_id: uuid.UUID,
    request: Request,
    cursor: str | None = None,
    limit: int = service.DEFAULT_PAGE_SIZE,
    membership: rbac.ActiveMembership = Depends(require_viewer),
    db: AsyncSession = Depends(get_db),
) -> CursorPage[MemberEntry]:
    entries, next_cursor = await service.list_members(
        db, workspace_id, caller_rank=membership.rank, cursor=cursor, limit=limit
    )
    return cursor_page(entries, next_cursor, request)


@router.patch(
    "/{workspace_id}/members/{membership_id}",
    response_model=SuccessEnvelope[MembershipPublic],
    status_code=status.HTTP_200_OK,
)
async def change_member_role_route(
    workspace_id: uuid.UUID,
    membership_id: uuid.UUID,
    payload: UpdateMembershipRoleRequest,
    request: Request,
    _membership: rbac.ActiveMembership = Depends(require_admin),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> SuccessEnvelope[MembershipPublic]:
    updated = await service.change_member_role(
        db, redis, workspace_id, membership_id, current_user_id, payload.role_id
    )
    return envelope(_membership_public(updated), request)


@router.delete("/{workspace_id}/members/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member_route(
    workspace_id: uuid.UUID,
    membership_id: uuid.UUID,
    _membership: rbac.ActiveMembership = Depends(require_admin),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> None:
    await service.remove_member(db, redis, workspace_id, membership_id, current_user_id)


# ---------------------------------------------------------------------------
# S1G — Invitations (workspace-scoped: create/list/resend/revoke). The
# public token-based endpoints (`GET /api/v1/invitations/{token}`,
# `POST /api/v1/invitations/{token}/accept`) live in
# app/api/v1/endpoints/invitations.py — a separate top-level resource,
# not nested under `/workspaces/{workspace_id}`, matching the frozen
# route shapes S1G itself specifies.
# ---------------------------------------------------------------------------


@router.post(
    "/{workspace_id}/invitations",
    response_model=SuccessEnvelope[InvitationPublic],
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation_route(
    workspace_id: uuid.UUID,
    payload: CreateInvitationRequest,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    _membership: rbac.ActiveMembership = Depends(require_admin),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> SuccessEnvelope[InvitationPublic]:
    """`Idempotency-Key` is a required header (S1G: "sending an
    invitation is a retry-plausible resource-creating operation") — a
    retried request with the same key, from the same admin, in the same
    workspace, replays the exact response the first attempt produced
    rather than creating (and re-emailing) a second invitation. See
    `app.core.idempotency` for the cache this uses and its documented
    limits.
    """
    actor = f"{current_user_id}:{workspace_id}"
    cached = await idempotency.get_cached_response(
        redis,
        scope=_INVITATION_CREATE_IDEMPOTENCY_SCOPE,
        actor=actor,
        idempotency_key=idempotency_key,
    )
    if cached is not None:
        cached_status_code, cached_body = cached
        return JSONResponse(status_code=cached_status_code, content=cached_body)

    invitation = await service.create_invitation(db, workspace_id, current_user_id, payload)
    response_envelope = envelope(_invitation_public(invitation), request)

    await idempotency.store_response(
        redis,
        scope=_INVITATION_CREATE_IDEMPOTENCY_SCOPE,
        actor=actor,
        idempotency_key=idempotency_key,
        status_code=status.HTTP_201_CREATED,
        body=response_envelope.model_dump(mode="json"),
    )
    return response_envelope


@router.get(
    "/{workspace_id}/invitations",
    response_model=CursorPage[InvitationPublic],
    status_code=status.HTTP_200_OK,
)
async def list_invitations_route(
    workspace_id: uuid.UUID,
    request: Request,
    cursor: str | None = None,
    limit: int = service.DEFAULT_PAGE_SIZE,
    _membership: rbac.ActiveMembership = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CursorPage[InvitationPublic]:
    invitations, next_cursor = await service.list_pending_invitations(
        db, workspace_id, cursor=cursor, limit=limit
    )
    return cursor_page([_invitation_public(i) for i in invitations], next_cursor, request)


@router.post(
    "/{workspace_id}/invitations/{invitation_id}/resend",
    response_model=SuccessEnvelope[InvitationPublic],
    status_code=status.HTTP_202_ACCEPTED,
)
async def resend_invitation_route(
    workspace_id: uuid.UUID,
    invitation_id: uuid.UUID,
    request: Request,
    _membership: rbac.ActiveMembership = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SuccessEnvelope[InvitationPublic]:
    invitation = await service.resend_invitation(db, workspace_id, invitation_id)
    return envelope(_invitation_public(invitation), request)


@router.delete(
    "/{workspace_id}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def revoke_invitation_route(
    workspace_id: uuid.UUID,
    invitation_id: uuid.UUID,
    _membership: rbac.ActiveMembership = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.revoke_invitation(db, workspace_id, invitation_id)
