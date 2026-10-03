"""Centralized RBAC — the one place that identifies a caller's active
Membership + Role in a workspace and evaluates whether it's sufficient
for a required tier. No route or service function checks a role
directly; every workspace-scoped route depends on
`app.modules.workspaces.dependencies`'s tier dependencies, which call
into this module. Reuses the same shared `app.db.redis.redis_client`
S1D already established — no second Redis client is created.

**IMPLEMENTATION CHOICE — role hierarchy.** S1F's own specification
names four ordered tiers routes must be able to require ("Viewer+",
"Member+", "Admin+", "Owner"). No frozen document ranks the four
`RoleName` values numerically (the Technical Design Document isn't a
file in this repository — see docs/architecture/README.md) — this
module assigns `VIEWER < MEMBER < ADMIN < OWNER`, matching the order
S1F itself always lists them in and the natural reading of "the four
MVP roles" from least to most privileged. Since `OWNER` is already the
top rank, "Owner" (no "+") and "Owner+" are mathematically identical —
there's nothing above it to admit — so a single rank comparison
correctly expresses all four tiers with no separate "exact match" case.
"""

import logging
import uuid

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.workspaces.models import (
    Membership,
    MembershipStatus,
    Role,
    RoleName,
    Workspace,
    WorkspaceStatus,
)

logger = logging.getLogger(__name__)

# IMPLEMENTATION CHOICE — see module docstring.
ROLE_RANK: dict[RoleName, int] = {
    RoleName.VIEWER: 1,
    RoleName.MEMBER: 2,
    RoleName.ADMIN: 3,
    RoleName.OWNER: 4,
}

# IMPLEMENTATION CHOICE — no frozen RBAC cache key format/TTL exists to
# follow (same reason as above: no TDD file to inspect). 5 minutes
# bounds staleness for any path that *isn't* one of the two explicitly-
# required immediate-invalidation events (role change, removal — both
# call `invalidate_membership_cache` directly, which is the actual
# correctness guarantee; this TTL is only a safety net for anything
# else, e.g. a crash between a DB write and its invalidation call).
_CACHE_KEY_PREFIX = "rbac:membership:"
_CACHE_TTL_SECONDS = 300


class ActiveMembership:
    """What the RBAC layer resolves a caller down to: which Membership,
    and what Role it carries. Deliberately not the full ORM
    `Membership` object — callers that need more (the membership
    endpoints themselves) re-query explicitly; this is just enough to
    make an authorization decision.
    """

    __slots__ = ("membership_id", "role_name")

    def __init__(self, membership_id: uuid.UUID, role_name: RoleName) -> None:
        self.membership_id = membership_id
        self.role_name = role_name

    @property
    def rank(self) -> int:
        return ROLE_RANK[self.role_name]


def _cache_key(user_id: uuid.UUID, workspace_id: uuid.UUID) -> str:
    return f"{_CACHE_KEY_PREFIX}{user_id}:{workspace_id}"


async def get_active_membership(
    session: AsyncSession, redis: Redis, *, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> ActiveMembership | None:
    """Resolve `user_id`'s active Membership in `workspace_id`, if any.

    Cache-first (Redis), falling back to Postgres on a miss. Only a
    *positive* result (an active membership was found) is ever cached —
    "not a member" is never cached, so there's no negative-cache entry
    that would itself need invalidating the moment someone is added.
    """
    key = _cache_key(user_id, workspace_id)
    cached = await redis.get(key)
    if cached is not None:
        membership_id_str, role_name_str = cached.split(":", 1)
        return ActiveMembership(uuid.UUID(membership_id_str), RoleName(role_name_str))

    row = (
        await session.execute(
            select(Membership.id, Role.name)
            .join(Role, Role.id == Membership.role_id)
            .join(Workspace, Workspace.id == Membership.workspace_id)
            .where(
                Membership.user_id == user_id,
                Membership.workspace_id == workspace_id,
                Membership.status == MembershipStatus.ACTIVE,
                # Frozen invariant: "Do not allow an active Membership
                # for a deleted Workspace." Deletion doesn't bulk-update
                # every Membership row (see service.soft_delete_workspace);
                # this is the single point that actually enforces it —
                # a deleted workspace's memberships stop authorizing
                # anything, without needing a cascading write at delete
                # time. Archived workspaces remain readable (archiving
                # is reversible, not a lockout), so only DELETED is
                # excluded here.
                Workspace.status != WorkspaceStatus.DELETED,
            )
        )
    ).first()

    if row is None:
        return None

    membership_id, role_name = row
    await redis.set(key, f"{membership_id}:{role_name.value}", ex=_CACHE_TTL_SECONDS)
    return ActiveMembership(membership_id, role_name)


async def invalidate_membership_cache(
    redis: Redis, *, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> None:
    """Immediately drop the cached authorization state for one
    (user, workspace) pair — called after every role change and every
    membership removal, per S1F's explicit requirement. Deliberately
    does **not** swallow a Redis error the way `tests/db.py`'s disposal
    helper does: an invalidation that silently failed would leave a
    stale, wrong-privilege cache entry live for up to
    `_CACHE_TTL_SECONDS` — a real authorization-correctness issue, not
    test hygiene.
    """
    await redis.delete(_cache_key(user_id, workspace_id))
