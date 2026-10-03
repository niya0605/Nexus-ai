"""Public and self-scoped invitation endpoints (S1G).

`GET /api/v1/invitations/{token}` (public, no auth) and
`POST /api/v1/invitations/{token}/accept` (auth required, Self-scoped —
the authenticated caller's own email must match the invitation) are
top-level resources, not nested under `/workspaces/{workspace_id}`,
exactly matching the two route shapes S1G's own specification gives.
The four workspace-scoped invitation-management endpoints (create,
list, resend, revoke) live in `app/api/v1/endpoints/workspaces.py`
instead, alongside the rest of that resource's routes.
"""

import uuid

from fastapi import APIRouter, Depends, Header, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import idempotency
from app.core.responses import SuccessEnvelope, envelope
from app.db.dependencies import get_db
from app.db.redis import get_redis
from app.modules.auth.dependencies import get_current_user_id
from app.modules.auth.models import User
from app.modules.workspaces import service
from app.modules.workspaces.schemas import MembershipPublic, PublicInvitationDetails

router = APIRouter(prefix="/invitations", tags=["invitations"])

_ACCEPT_IDEMPOTENCY_SCOPE = "invitation_accept"


@router.get(
    "/{token}",
    response_model=SuccessEnvelope[PublicInvitationDetails],
    status_code=status.HTTP_200_OK,
)
async def get_invitation_details_route(
    token: str, request: Request, db: AsyncSession = Depends(get_db)
) -> SuccessEnvelope[PublicInvitationDetails]:
    """Public — no `Auth` dependency at all, per S1G: "Auth: No,
    Permission: Public". The raw token is the only credential; anyone
    holding it (i.e. anyone the invitation email was sent to) may view
    these details before ever logging in or creating an account.
    """
    invitation = await service.get_invitation_by_token(db, token)
    workspace = await service.get_workspace(db, invitation.workspace_id)
    details = PublicInvitationDetails(
        id=invitation.id,
        workspace_id=invitation.workspace_id,
        workspace_name=workspace.name,
        invited_email=invitation.invited_email,
        role=invitation.role.name.value,
        status=invitation.status,
        expires_at=invitation.expires_at,
    )
    return envelope(details, request)


@router.post(
    "/{token}/accept",
    response_model=SuccessEnvelope[MembershipPublic],
    status_code=status.HTTP_200_OK,
)
async def accept_invitation_route(
    token: str,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> SuccessEnvelope[MembershipPublic]:
    """`Auth: Yes`, `Permission: Self` — the caller must be authenticated
    (`get_current_user_id`), and the service layer enforces that their
    own normalized email matches the invitation's `invited_email`
    (`email_mismatch`, 403, if not — "do not allow User A to accept User
    B's invitation").

    `Idempotency-Key` is required, same reasoning and same shared
    mechanism as invitation creation (`app.core.idempotency`) — accept is
    also a retry-plausible, resource-creating (Membership) operation.
    """
    actor = str(current_user_id)
    cached = await idempotency.get_cached_response(
        redis, scope=_ACCEPT_IDEMPOTENCY_SCOPE, actor=actor, idempotency_key=idempotency_key
    )
    if cached is not None:
        from fastapi.responses import JSONResponse

        cached_status_code, cached_body = cached
        return JSONResponse(status_code=cached_status_code, content=cached_body)

    user = await db.get(User, current_user_id)
    membership, _created = await service.accept_invitation(
        db, redis, token, current_user_id, user.email
    )
    membership_public = MembershipPublic(
        id=membership.id,
        workspace_id=membership.workspace_id,
        user_id=membership.user_id,
        role=membership.role.name.value,
        status=membership.status,
        created_at=membership.created_at,
    )
    response_envelope = envelope(membership_public, request)

    await idempotency.store_response(
        redis,
        scope=_ACCEPT_IDEMPOTENCY_SCOPE,
        actor=actor,
        idempotency_key=idempotency_key,
        status_code=status.HTTP_200_OK,
        body=response_envelope.model_dump(mode="json"),
    )
    return response_envelope
