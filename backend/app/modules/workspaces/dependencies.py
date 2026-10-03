"""FastAPI dependencies enforcing workspace RBAC tiers — the only place
a route expresses "Viewer+", "Member+", "Admin+", or "Owner"; no route
or service checks a role directly, per S1F's explicit instruction not
to write ad hoc per-route authorization logic.
"""

import uuid

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.dependencies import get_db
from app.db.redis import get_redis
from app.modules.auth.dependencies import get_current_user_id
from app.modules.workspaces import rbac
from app.modules.workspaces.exceptions import InsufficientPermissionError, WorkspaceNotFoundError
from app.modules.workspaces.models import RoleName


class RequireRole:
    """A FastAPI dependency requiring the caller to have at least the
    given Role rank in the workspace named by the route's own
    `workspace_id` path parameter (bound automatically — FastAPI
    resolves a sub-dependency's parameters against the same path/query/
    body sources as the route function's own, matched by name).

    Returns the resolved `rbac.ActiveMembership` — routes/services that
    need to know exactly *which* membership authorized the request (or
    its exact role) get it as this dependency's return value, rather
    than re-resolving it themselves.
    """

    def __init__(self, minimum: RoleName) -> None:
        self.minimum = minimum

    async def __call__(
        self,
        workspace_id: uuid.UUID,
        current_user_id: uuid.UUID = Depends(get_current_user_id),
        db: AsyncSession = Depends(get_db),
        redis: Redis = Depends(get_redis),
    ) -> rbac.ActiveMembership:
        membership = await rbac.get_active_membership(
            db, redis, user_id=current_user_id, workspace_id=workspace_id
        )
        if membership is None:
            # See WorkspaceNotFoundError's docstring: a missing
            # Membership and a nonexistent workspace are deliberately
            # indistinguishable to the caller.
            raise WorkspaceNotFoundError()

        if membership.rank < rbac.ROLE_RANK[self.minimum]:
            raise InsufficientPermissionError()

        return membership


require_viewer = RequireRole(RoleName.VIEWER)
require_member = RequireRole(RoleName.MEMBER)
require_admin = RequireRole(RoleName.ADMIN)
require_owner = RequireRole(RoleName.OWNER)
