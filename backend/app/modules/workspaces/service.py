"""Workspaces module service layer.

Every function owns its own transaction boundary, exactly the same
convention `app.modules.auth.service` already established —
`app/db/dependencies.py`'s `get_db` never commits. Redis (RBAC cache
invalidation) is only ever touched *after* the Postgres commit it
depends on has succeeded, same ordering rationale as S1D's refresh
rotation: never leave a stale cache entry pointing at state that turned
out not to persist, and never invalidate a cache for a write that never
actually happened.

Invitation creation/acceptance, documents, chat, and RBAC-cache
behavior beyond what S1F itself requires are all out of scope — see
this module's `dependencies.py`/`rbac.py` for the authorization layer
every function here assumes has already run (workspace_id + minimum
role already verified before a service function is ever called).
"""

import base64
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.security import create_refresh_token, hash_refresh_token
from app.core.validation import normalize_email
from app.modules.auth.exceptions import TokenInvalidError
from app.modules.auth.models import User
from app.modules.workspaces import mail, rbac
from app.modules.workspaces.exceptions import (
    AlreadyMemberError,
    CannotRemoveLastOwnerError,
    EmailMismatchError,
    InsufficientPermissionError,
    InvalidRoleError,
    InvitationAlreadyResolvedError,
    InvitationExpiredError,
    InvitationNotFoundError,
    MembershipNotFoundError,
    SlugUnavailableError,
    WorkspaceNotFoundError,
)
from app.modules.workspaces.models import (
    AuditLog,
    Invitation,
    InvitationStatus,
    Membership,
    MembershipStatus,
    Role,
    RoleName,
    Workspace,
    WorkspaceSettings,
    WorkspaceStatus,
)
from app.modules.workspaces.schemas import (
    ALLOWED_FILE_TYPES,
    CreateInvitationRequest,
    CreateWorkspaceRequest,
    MemberEntry,
    MemberUserInfo,
    UpdateWorkspaceSettingsRequest,
)
from app.modules.workspaces.slug import slugify

logger = logging.getLogger(__name__)

# IMPLEMENTATION CHOICE — no frozen cursor-pagination page size exists
# to follow (same missing-document reason as elsewhere in this module).
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# The default WorkspaceSettings values S1F states explicitly.
_DEFAULT_ALLOWED_FILE_TYPES = list(ALLOWED_FILE_TYPES)
_DEFAULT_MAX_DOCUMENT_SIZE_MB = 50

_MAX_SLUG_COLLISION_ATTEMPTS = 50
_MAX_CONCURRENT_SLUG_RETRIES = 3


# ---------------------------------------------------------------------------
# Cursor helpers — IMPLEMENTATION CHOICE: opaque base64 of the last-seen
# row's UUIDv7 id. UUIDv7 is already time-ordered (app/utils/ids.py), so
# ordering by `id` ascending doubles as chronological order for free,
# with no separate composite (created_at, id) cursor needed.
# ---------------------------------------------------------------------------
def _encode_cursor(row_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(str(row_id).encode()).decode()


def _decode_cursor(cursor: str) -> uuid.UUID:
    try:
        return uuid.UUID(base64.urlsafe_b64decode(cursor.encode()).decode())
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid cursor") from exc


def _clamp_limit(limit: int) -> int:
    return max(1, min(limit, MAX_PAGE_SIZE))


# ---------------------------------------------------------------------------
# Workspace creation
# ---------------------------------------------------------------------------
async def _generate_unique_slug(session: AsyncSession, name: str) -> str:
    """Derive a globally-unique slug from `name`. See slug.py's own
    docstring for the base transformation; this loop is the DB-aware
    half — try the bare candidate, then `-2`, `-3`, ... — an
    IMPLEMENTATION CHOICE (see exceptions.SlugUnavailableError)."""
    base = slugify(name)
    candidate = base
    for attempt in range(1, _MAX_SLUG_COLLISION_ATTEMPTS + 1):
        exists = (
            await session.execute(select(Workspace.id).where(Workspace.slug == candidate))
        ).scalar_one_or_none()
        if exists is None:
            return candidate
        candidate = f"{base}-{attempt + 1}"[:100]
    raise SlugUnavailableError()


async def create_workspace(
    session: AsyncSession, redis: Redis, user_id: uuid.UUID, payload: CreateWorkspaceRequest
) -> tuple[Workspace, Membership]:
    """Atomically create a Workspace, its founding (Owner) Membership,
    and its default WorkspaceSettings — the frozen invariant: "The
    workspace must never be observably created without all three."
    One `session.add_all` + one commit; if the commit fails, none of
    the three rows exist. A slug taken by a concurrent request between
    the uniqueness check and the commit is retried with a fresh slug.
    """
    owner_role = (
        await session.execute(select(Role).where(Role.name == RoleName.OWNER))
    ).scalar_one()
    # Rollback expires loaded objects; reading owner_role.id after one would lazy-load (not allowed async).
    owner_role_id = owner_role.id

    for attempt in range(1, _MAX_CONCURRENT_SLUG_RETRIES + 1):
        slug = await _generate_unique_slug(session, payload.name)
        if attempt > 1:
            # Racing requests would all derive the same next candidate; randomize instead.
            slug = f"{slug[:90]}-{secrets.token_hex(3)}"
        workspace = Workspace(name=payload.name, slug=slug)
        membership = Membership(workspace=workspace, user_id=user_id, role_id=owner_role_id)
        settings = WorkspaceSettings(
            workspace=workspace,
            allowed_file_types=list(_DEFAULT_ALLOWED_FILE_TYPES),
            max_document_size_mb=_DEFAULT_MAX_DOCUMENT_SIZE_MB,
        )
        session.add_all([workspace, membership, settings])

        try:
            await session.commit()
            break
        except IntegrityError as exc:
            await session.rollback()
            if "slug" not in str(exc.orig).lower():
                raise
            if attempt == _MAX_CONCURRENT_SLUG_RETRIES:
                raise SlugUnavailableError() from exc

    await session.refresh(workspace)
    await session.refresh(membership)
    await session.refresh(owner_role)
    membership.role = owner_role
    logger.info(f"Workspace created: {workspace.id} (owner={user_id})")
    return workspace, membership


# ---------------------------------------------------------------------------
# Workspace read/list
# ---------------------------------------------------------------------------
async def list_workspaces_for_user(
    session: AsyncSession, user_id: uuid.UUID, *, cursor: str | None, limit: int
) -> tuple[list[Workspace], str | None]:
    """Workspaces where `user_id` has an *active* Membership — never
    another user's, never one they were removed from. Deleted
    workspaces are excluded (see rbac.py's identical exclusion for the
    same invariant); archived ones remain listed (archiving doesn't
    hide a workspace from its own members, only pauses it).
    """
    limit = _clamp_limit(limit)
    conditions = [
        Membership.user_id == user_id,
        Membership.status == MembershipStatus.ACTIVE,
        Workspace.status != WorkspaceStatus.DELETED,
    ]
    if cursor is not None:
        conditions.append(Workspace.id > _decode_cursor(cursor))

    rows = (
        (
            await session.execute(
                select(Workspace)
                .join(Membership, Membership.workspace_id == Workspace.id)
                .where(*conditions)
                .order_by(Workspace.id)
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )

    has_more = len(rows) > limit
    page = list(rows[:limit])
    next_cursor = _encode_cursor(page[-1].id) if has_more else None
    return page, next_cursor


async def get_workspace(session: AsyncSession, workspace_id: uuid.UUID) -> Workspace:
    """Fetch a workspace by ID. Called only *after* the RBAC dependency
    has already confirmed the caller has an active, non-deleted-
    workspace Membership — this never re-checks authorization, only
    existence (which, by that point, is already guaranteed)."""
    workspace = (
        await session.execute(select(Workspace).where(Workspace.id == workspace_id))
    ).scalar_one_or_none()
    if workspace is None:
        raise WorkspaceNotFoundError()
    return workspace


async def update_workspace_name(
    session: AsyncSession, workspace_id: uuid.UUID, name: str
) -> Workspace:
    workspace = await get_workspace(session, workspace_id)
    workspace.name = name
    await session.commit()
    await session.refresh(workspace)
    return workspace


async def archive_workspace(session: AsyncSession, workspace_id: uuid.UUID) -> Workspace:
    """`active → archived`. Archiving an already-archived workspace is a
    no-op success (IMPLEMENTATION CHOICE — idempotent, not an error;
    no frozen guidance on repeat-archive behavior)."""
    workspace = await get_workspace(session, workspace_id)
    if workspace.status == WorkspaceStatus.ACTIVE:
        workspace.status = WorkspaceStatus.ARCHIVED
        workspace.archived_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(workspace)
    return workspace


async def restore_workspace(session: AsyncSession, workspace_id: uuid.UUID) -> Workspace:
    """`archived → active` only — S1F: "Do not restore deleted
    workspaces through this endpoint unless the frozen contract
    explicitly permits that transition" (it doesn't say it does, so
    this doesn't). A deleted workspace never reaches this function at
    all: the Owner's own Membership stops authorizing anything once its
    workspace is deleted (rbac.py), so the RBAC dependency itself
    already returns `workspace_not_found` before the route body runs.
    Restoring an already-active workspace is a no-op success, same
    idempotency reasoning as `archive_workspace`.
    """
    workspace = await get_workspace(session, workspace_id)
    if workspace.status == WorkspaceStatus.ARCHIVED:
        workspace.status = WorkspaceStatus.ACTIVE
        workspace.archived_at = None
        await session.commit()
        await session.refresh(workspace)
    return workspace


async def soft_delete_workspace(
    session: AsyncSession, redis: Redis, workspace_id: uuid.UUID
) -> Workspace:
    """`active|archived → deleted`. Sets `deleted_at`; never touches any
    child row (Membership, WorkspaceSettings, Invitation) — "Do NOT
    physically delete the workspace or its children," and per rbac.py,
    a deleted workspace's Memberships simply stop authorizing anything
    from this moment on, with no bulk write required.

    **Bug found and fixed while testing this milestone:** rbac.py's
    Postgres query correctly excludes a deleted workspace, but that
    alone isn't enough — `get_active_membership` is cache-first, and
    without an explicit invalidation here, every member (not just the
    actor) would keep their *cached* pre-deletion authorization for up
    to `rbac._CACHE_TTL_SECONDS`, letting them keep reading a workspace
    that's supposed to already be gone from their view. Unlike a role
    change or removal (which affects exactly one membership),
    deletion changes the authorization outcome for *every* active
    member at once, so every one of their cache entries is invalidated
    here — after the commit succeeds, same ordering rationale as
    elsewhere in this module.
    """
    workspace = await get_workspace(session, workspace_id)
    if workspace.status != WorkspaceStatus.DELETED:
        member_user_ids = (
            (
                await session.execute(
                    select(Membership.user_id).where(
                        Membership.workspace_id == workspace_id,
                        Membership.status == MembershipStatus.ACTIVE,
                    )
                )
            )
            .scalars()
            .all()
        )

        workspace.status = WorkspaceStatus.DELETED
        workspace.deleted_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(workspace)

        for user_id in member_user_ids:
            await rbac.invalidate_membership_cache(
                redis, user_id=user_id, workspace_id=workspace_id
            )
    return workspace


# ---------------------------------------------------------------------------
# Workspace settings
# ---------------------------------------------------------------------------
async def get_workspace_settings(
    session: AsyncSession, workspace_id: uuid.UUID
) -> WorkspaceSettings:
    settings = (
        await session.execute(
            select(WorkspaceSettings).where(WorkspaceSettings.workspace_id == workspace_id)
        )
    ).scalar_one()  # always exists — created atomically with the workspace
    return settings


async def update_workspace_settings(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    payload: UpdateWorkspaceSettingsRequest,
) -> WorkspaceSettings:
    """Apply only the fields the client actually supplied (distinguished
    via `model_fields_set`, not "is it None" — `document_retention_days`
    legitimately means "no override" when explicitly set to `null`).
    Writes one AuditLog row, in the same transaction as the update, iff
    `document_retention_days` actually changed — "Retention-policy
    changes are Audit-Requirement: Yes"; the other two settings fields
    are not stated as audit-required, so they aren't logged.
    """
    settings = await get_workspace_settings(session, workspace_id)
    fields_set = payload.model_fields_set

    retention_changed = (
        "document_retention_days" in fields_set
        and payload.document_retention_days != settings.document_retention_days
    )
    old_retention_days = settings.document_retention_days

    if "document_retention_days" in fields_set:
        settings.document_retention_days = payload.document_retention_days
    if "allowed_file_types" in fields_set and payload.allowed_file_types is not None:
        settings.allowed_file_types = payload.allowed_file_types
    if "max_document_size_mb" in fields_set and payload.max_document_size_mb is not None:
        settings.max_document_size_mb = payload.max_document_size_mb

    if retention_changed:
        session.add(
            AuditLog(
                actor_user_id=actor_user_id,
                workspace_id=workspace_id,
                action="workspace_settings.retention_changed",
                target_type="workspace_settings",
                target_id=settings.id,
                metadata_={
                    "before_document_retention_days": old_retention_days,
                    "after_document_retention_days": settings.document_retention_days,
                },
            )
        )

    await session.commit()
    await session.refresh(settings)
    return settings


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------
async def list_members(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    caller_rank: int,
    cursor: str | None,
    limit: int,
) -> tuple[list[MemberEntry], str | None]:
    """S1F: "Never expose email to non-Admin viewers. Admins may
    receive email according to the frozen privacy behavior" — `email`
    is populated on each entry only when `caller_rank >= ADMIN`."""
    limit = _clamp_limit(limit)
    conditions = [
        Membership.workspace_id == workspace_id,
        Membership.status == MembershipStatus.ACTIVE,
    ]
    if cursor is not None:
        conditions.append(Membership.id > _decode_cursor(cursor))

    rows = (
        (
            await session.execute(
                select(Membership)
                .where(*conditions)
                .options(selectinload(Membership.user), selectinload(Membership.role))
                .order_by(Membership.id)
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )

    has_more = len(rows) > limit
    page = list(rows[:limit])
    next_cursor = _encode_cursor(page[-1].id) if has_more else None

    include_email = caller_rank >= rbac.ROLE_RANK[RoleName.ADMIN]
    entries = [
        MemberEntry(
            id=m.id,
            user=MemberUserInfo(
                id=m.user.id,
                display_name=m.user.display_name,
                avatar_url=m.user.avatar_url,
                email=m.user.email if include_email else None,
            ),
            role=m.role.name.value,
            status=m.status,
            created_at=m.created_at,
        )
        for m in page
    ]
    return entries, next_cursor


async def _count_active_owners(session: AsyncSession, workspace_id: uuid.UUID) -> int:
    owner_role_id = (
        await session.execute(select(Role.id).where(Role.name == RoleName.OWNER))
    ).scalar_one()
    return (
        await session.execute(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.workspace_id == workspace_id,
                Membership.role_id == owner_role_id,
                Membership.status == MembershipStatus.ACTIVE,
            )
        )
    ).scalar_one()


async def change_member_role(
    session: AsyncSession,
    redis: Redis,
    workspace_id: uuid.UUID,
    membership_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    new_role_id: uuid.UUID,
) -> Membership:
    """Change one Membership's role. Enforces, in order:

    1. the target Membership belongs to `workspace_id` and is active
       (else `MembershipNotFoundError`)
    2. **INFERENCE, flagged as an unresolved contract gap** (S1F asks
       for this explicitly when the frozen documents are silent): a
       caller may not change their *own* role through this endpoint —
       the safest minimal interpretation, since self-promotion/-demotion
       isn't addressed by any frozen document. Raises
       `InsufficientPermissionError`.
    3. `new_role_id` resolves to a real, system-defined Role (else a
       422 — see `_resolve_target_role`'s docstring for why that reuses
       the generic `validation_error` code rather than inventing one)
    4. the owner invariant: demoting the workspace's last Owner raises
       `CannotRemoveLastOwnerError` (409 `cannot_remove_last_owner`)

    On success: role_id + updated_at change, one AuditLog row, and the
    target user's RBAC cache entry for this workspace is invalidated —
    all after one commit succeeds.
    """
    membership = (
        await session.execute(
            select(Membership).where(
                Membership.id == membership_id,
                Membership.workspace_id == workspace_id,
                Membership.status == MembershipStatus.ACTIVE,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise MembershipNotFoundError()

    if membership.user_id == actor_user_id:
        raise InsufficientPermissionError()

    new_role = (
        await session.execute(
            select(Role).where(Role.id == new_role_id, Role.is_system_defined.is_(True))
        )
    ).scalar_one_or_none()
    if new_role is None:
        raise InvalidRoleError()

    old_role = (
        await session.execute(select(Role).where(Role.id == membership.role_id))
    ).scalar_one()

    if old_role.name == RoleName.OWNER and new_role.name != RoleName.OWNER:
        owner_count = await _count_active_owners(session, workspace_id)
        if owner_count <= 1:
            raise CannotRemoveLastOwnerError()

    membership.role_id = new_role.id
    membership.updated_at = datetime.now(UTC)
    session.add(
        AuditLog(
            actor_user_id=actor_user_id,
            workspace_id=workspace_id,
            action="membership.role_changed",
            target_type="membership",
            target_id=membership.id,
            metadata_={
                "target_user_id": str(membership.user_id),
                "before_role": old_role.name.value,
                "after_role": new_role.name.value,
            },
        )
    )

    await session.commit()
    await session.refresh(membership)

    await rbac.invalidate_membership_cache(
        redis, user_id=membership.user_id, workspace_id=workspace_id
    )
    logger.info(f"Membership role changed: {membership.id}")
    return membership


async def remove_member(
    session: AsyncSession,
    redis: Redis,
    workspace_id: uuid.UUID,
    membership_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> None:
    """Soft-remove one Membership. Same self-action guard as
    `change_member_role` (**INFERENCE, flagged** — S1F is silent on
    self-removal through this Admin-scoped endpoint specifically; a
    separate Self-permission "leave workspace" flow, if wanted, is a
    different, unrequested endpoint), and the same owner invariant:
    removing the workspace's last Owner raises `CannotRemoveLastOwnerError`.

    Membership removal is **not** listed among S1F's audit-required
    actions (only role changes and retention changes are) — no
    AuditLog row is written here; that's a deliberate reading of the
    literal scope, not an oversight.
    """
    membership = (
        await session.execute(
            select(Membership).where(
                Membership.id == membership_id,
                Membership.workspace_id == workspace_id,
                Membership.status == MembershipStatus.ACTIVE,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise MembershipNotFoundError()

    if membership.user_id == actor_user_id:
        raise InsufficientPermissionError()

    role = (await session.execute(select(Role).where(Role.id == membership.role_id))).scalar_one()
    if role.name == RoleName.OWNER:
        owner_count = await _count_active_owners(session, workspace_id)
        if owner_count <= 1:
            raise CannotRemoveLastOwnerError()

    now = datetime.now(UTC)
    membership.status = MembershipStatus.REMOVED
    membership.removed_at = now
    membership.updated_at = now
    await session.commit()

    await rbac.invalidate_membership_cache(
        redis, user_id=membership.user_id, workspace_id=workspace_id
    )
    logger.info(f"Membership removed: {membership.id}")


# ---------------------------------------------------------------------------
# S1G — Invitations
#
# No AuditLog is written anywhere in this section. S1F's own frozen
# audit-required list names exactly two actions (Membership role
# changes, WorkspaceSettings retention changes) and is silent on
# invitation creation/resend/revocation/acceptance — per S1G's own
# instruction ("If the frozen audit requirements are silent for an
# invitation action, document that fact instead of inventing a new
# audit contract"), that silence is respected as-is rather than treated
# as an oversight to "fix".
# ---------------------------------------------------------------------------
_MAX_INVITATION_CREATE_ATTEMPTS = 2


async def _find_active_membership_by_email(
    session: AsyncSession, workspace_id: uuid.UUID, normalized_email: str
) -> Membership | None:
    return (
        await session.execute(
            select(Membership)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.workspace_id == workspace_id,
                Membership.status == MembershipStatus.ACTIVE,
                func.lower(User.email) == normalized_email,
            )
        )
    ).scalar_one_or_none()


async def _resolve_system_role(session: AsyncSession, role_id: uuid.UUID) -> Role:
    role = (
        await session.execute(
            select(Role).where(Role.id == role_id, Role.is_system_defined.is_(True))
        )
    ).scalar_one_or_none()
    if role is None:
        raise InvalidRoleError()
    return role


def _invitation_expires_at(now: datetime) -> datetime:
    return now + timedelta(days=settings.INVITATION_TOKEN_EXPIRE_DAYS)


async def create_invitation(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    payload: CreateInvitationRequest,
) -> Invitation:
    """`POST .../invitations` — steps exactly as S1G's own numbered
    behavior list (role validation, already-a-member check, replace any
    existing pending invitation, generate+hash a token, commit, then —
    outside this function's own transaction — send the email).

    **Replace, not duplicate (frozen invariant):** "creating another
    invitation for the same workspace/email while a pending invitation
    exists replaces the existing pending invitation rather than creating
    two simultaneously active invitations." Implemented as: the previous
    pending row (if any) is transitioned to `revoked` in the same
    transaction as the new row's insert — reusing the `pending → revoked`
    lifecycle transition Invitation already has, rather than a new
    "superseded" status this entity doesn't define. History is preserved
    (the old row still exists, just no longer pending), matching the
    same "soft transition, never delete" convention Workspace/Membership
    already established.

    **IMPLEMENTATION CHOICE — retry-once on a genuine create/create
    race:** the replace-then-insert above happens inside one transaction,
    so it cannot conflict with itself; it *can* still lose a race against
    a second, fully concurrent `create_invitation` call for the exact
    same (workspace_id, invited_email) pair (two admins inviting the same
    address at the same instant). On that (rare) `IntegrityError`, this
    retries once — the retry's own "replace" query now sees the other
    transaction's already-committed new pending row and revokes *that*
    one instead, succeeding normally. No frozen document addresses this
    race at all; a bare, unhandled failure on the second attempt is
    accepted as reasonable given how narrow the window is.
    """
    role = await _resolve_system_role(session, payload.role_id)

    if await _find_active_membership_by_email(session, workspace_id, payload.email) is not None:
        raise AlreadyMemberError()

    raw_token = create_refresh_token()
    token_hash = hash_refresh_token(raw_token)

    invitation: Invitation | None = None
    for attempt in range(1, _MAX_INVITATION_CREATE_ATTEMPTS + 1):
        now = datetime.now(UTC)
        previous_pending = (
            await session.execute(
                select(Invitation).where(
                    Invitation.workspace_id == workspace_id,
                    Invitation.invited_email == payload.email,
                    Invitation.status == InvitationStatus.PENDING,
                )
            )
        ).scalar_one_or_none()
        if previous_pending is not None:
            previous_pending.status = InvitationStatus.REVOKED
            previous_pending.resolved_at = now

        invitation = Invitation(
            workspace_id=workspace_id,
            invited_email=payload.email,
            role_id=role.id,
            invited_by_user_id=actor_user_id,
            token_hash=token_hash,
            status=InvitationStatus.PENDING,
            expires_at=_invitation_expires_at(now),
        )
        session.add(invitation)

        try:
            await session.commit()
            break
        except IntegrityError:
            await session.rollback()
            if attempt == _MAX_INVITATION_CREATE_ATTEMPTS:
                raise

    assert invitation is not None  # loop always assigns before break/raise
    await session.refresh(invitation)
    invitation.role = role  # avoid an extra round trip; already held

    logger.info(f"Invitation created: {invitation.id} (workspace={workspace_id})")

    # Delivery happens after the durable write above — a send failure
    # must never lose the already-committed business fact. Same
    # try/except-log-warning pattern as S1E's `_issue_and_send_verification_email`
    # (never the token itself in the log).
    workspace = await get_workspace(session, workspace_id)
    inviter = await session.get(User, actor_user_id)
    try:
        await mail.send_invitation_email(
            to=invitation.invited_email,
            workspace_name=workspace.name,
            inviter_display_name=inviter.display_name if inviter else "A workspace admin",
            role_name=role.name.value,
            raw_token=raw_token,
        )
    except Exception:  # noqa: BLE001 — deliberately broad, see this function's docstring
        logger.warning(f"Failed to send invitation email for invitation: {invitation.id}")

    return invitation


async def list_pending_invitations(
    session: AsyncSession, workspace_id: uuid.UUID, *, cursor: str | None, limit: int
) -> tuple[list[Invitation], str | None]:
    """`GET .../invitations` — pending invitations only, per S1G: "return
    pending invitations for the specified workspace only." A row whose
    `expires_at` has passed but hasn't yet been lazily flipped to
    `expired` by some other read (see `_settle_or_raise`) is excluded
    here too (`expires_at > now()`) rather than shown as misleadingly
    still-pending — an **IMPLEMENTATION CHOICE**: filtering, not a bulk
    write, so this hot list path never itself performs a write.
    """
    limit = _clamp_limit(limit)
    now = datetime.now(UTC)
    conditions = [
        Invitation.workspace_id == workspace_id,
        Invitation.status == InvitationStatus.PENDING,
        Invitation.expires_at > now,
    ]
    if cursor is not None:
        conditions.append(Invitation.id > _decode_cursor(cursor))

    rows = (
        (
            await session.execute(
                select(Invitation)
                .where(*conditions)
                .options(selectinload(Invitation.role))
                .order_by(Invitation.id)
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )

    has_more = len(rows) > limit
    page = list(rows[:limit])
    next_cursor = _encode_cursor(page[-1].id) if has_more else None
    return page, next_cursor


async def _load_invitation_in_workspace(
    session: AsyncSession, workspace_id: uuid.UUID, invitation_id: uuid.UUID
) -> Invitation:
    invitation = (
        await session.execute(
            select(Invitation)
            .where(Invitation.id == invitation_id, Invitation.workspace_id == workspace_id)
            .options(selectinload(Invitation.role))
        )
    ).scalar_one_or_none()
    if invitation is None:
        raise InvitationNotFoundError()
    return invitation


async def _settle_or_raise(session: AsyncSession, invitation: Invitation) -> None:
    """Enforce "an invitation that has passed expires_at must not be
    accepted [or resent, revoked, ...]" while keeping Postgres — not any
    Redis TTL — authoritative for invitation state, per S1G's explicit
    instruction.

    A still-genuinely-pending invitation returns normally. A `pending`
    invitation whose `expires_at` has passed is lazily transitioned to
    `expired` *and committed* right here (its own small transaction —
    this is a passive, idempotent state correction, not part of any
    operation's own atomicity requirement), then `InvitationExpiredError`
    is raised. Any other non-pending status (already `accepted` or
    `revoked`) raises `InvitationAlreadyResolvedError` without touching
    the row — "an already-resolved invitation must not be silently
    mutated."
    """
    if invitation.status == InvitationStatus.PENDING:
        if datetime.now(UTC) >= invitation.expires_at:
            invitation.status = InvitationStatus.EXPIRED
            invitation.resolved_at = datetime.now(UTC)
            await session.commit()
            raise InvitationExpiredError()
        return
    raise InvitationAlreadyResolvedError()


async def resend_invitation(
    session: AsyncSession, workspace_id: uuid.UUID, invitation_id: uuid.UUID
) -> Invitation:
    """`POST .../invitations/{id}/resend` — mutates the *same* row (per
    S1G: "do not create another Invitation row merely to resend"): a
    fresh token replaces `token_hash` outright, so the previous raw token
    can never hash-match again ("the previous token must no longer be
    usable after a successful resend"), and `expires_at` is recomputed
    from now. `workspace_id`/`invited_email`/`role_id`/`created_at`/`id`
    — the invitation's core identity — are untouched.
    """
    invitation = await _load_invitation_in_workspace(session, workspace_id, invitation_id)
    await _settle_or_raise(session, invitation)

    raw_token = create_refresh_token()
    invitation.token_hash = hash_refresh_token(raw_token)
    invitation.expires_at = _invitation_expires_at(datetime.now(UTC))
    await session.commit()
    # No `.refresh()` needed: Invitation has no `onupdate`/server-computed
    # column this mutation touches (unlike Workspace/Membership's
    # `updated_at`), and `expire_on_commit=False` means the in-memory
    # object — including the already eager-loaded `.role` relationship —
    # remains valid as-is after commit.

    workspace = await get_workspace(session, workspace_id)
    inviter = await session.get(User, invitation.invited_by_user_id)
    try:
        await mail.send_invitation_email(
            to=invitation.invited_email,
            workspace_name=workspace.name,
            inviter_display_name=inviter.display_name if inviter else "A workspace admin",
            role_name=invitation.role.name.value,
            raw_token=raw_token,
        )
    except Exception:  # noqa: BLE001 — same delivery-failure policy as create_invitation
        logger.warning(f"Failed to send invitation email for invitation: {invitation.id}")

    logger.info(f"Invitation resent: {invitation.id}")
    return invitation


async def revoke_invitation(
    session: AsyncSession, workspace_id: uuid.UUID, invitation_id: uuid.UUID
) -> None:
    """`DELETE .../invitations/{id}` — `pending → revoked`, `resolved_at`
    set, token immediately unusable (`get_invitation_by_token`/
    `accept_invitation` both reject anything but `pending`). No physical
    deletion — "the historical invitation remains available for
    lifecycle/audit purposes."
    """
    invitation = await _load_invitation_in_workspace(session, workspace_id, invitation_id)
    await _settle_or_raise(session, invitation)

    invitation.status = InvitationStatus.REVOKED
    invitation.resolved_at = datetime.now(UTC)
    await session.commit()
    logger.info(f"Invitation revoked: {invitation.id}")


async def get_invitation_by_token(session: AsyncSession, raw_token: str) -> Invitation:
    """`GET /api/v1/invitations/{token}` — the public, unauthenticated
    lookup. A token that doesn't hash-match any row reuses
    `app.modules.auth.exceptions.TokenInvalidError` (400, `token_invalid`)
    per S1G: "follow the existing authentication/token error
    architecture" — the same generic token-error code S1D/S1E's own
    token flows already share, not a new invitation-specific one. Never
    distinguishes "no such token" from "token belongs to a different
    kind of record" — both collapse to the same not-found lookup here,
    since `token_hash` is drawn from one dedicated column with its own
    unique constraint, not shared with any other token kind.
    """
    token_hash = hash_refresh_token(raw_token)
    invitation = (
        await session.execute(
            select(Invitation)
            .where(Invitation.token_hash == token_hash)
            .options(selectinload(Invitation.role))
        )
    ).scalar_one_or_none()
    if invitation is None:
        raise TokenInvalidError()

    await _settle_or_raise(session, invitation)
    return invitation


async def accept_invitation(
    session: AsyncSession,
    redis: Redis,
    raw_token: str,
    actor_user_id: uuid.UUID,
    actor_email: str,
) -> tuple[Membership, bool]:
    """`POST /api/v1/invitations/{token}/accept` — the frozen atomic
    transaction: Membership creation and Invitation closure (`status =
    accepted`, `resolved_at = now()`) commit together, in that order of
    verification, exactly as S1G's own numbered flow states.

    Returns `(membership, created)` — `created` is `False` in the one
    case S1G leaves unresolved ("if the frozen contract does not define
    the exact race-condition response, document the implementation
    choice"): the accepting user already held an active Membership in
    this workspace. Rather than inventing a new public error code here
    (the same reasoning `AlreadyMemberError` documents for the
    *creation*-time version of this same gap), acceptance still closes
    the Invitation as `accepted` — the offer's purpose ("let this email
    holder become a member") is already satisfied — and returns the
    caller's *existing* Membership unchanged, without creating a
    duplicate.

    **Race handling (frozen requirement):** "if a race occurs and
    another active Membership is created first: do not create duplicate
    Memberships... do not leave the invitation falsely marked accepted."
    If the initial commit raises `IntegrityError` (the partial unique
    index on `(workspace_id, user_id) WHERE status='active'` caught a
    concurrent winner), this rolls back — which, by construction, also
    undoes this attempt's own in-memory `status = accepted` mutation —
    then re-queries for the now-committed winning Membership and closes
    the Invitation out against *that* row instead, in its own follow-up
    transaction. The Invitation is never left `pending` after a
    successful accept response, and never `accepted` without a real,
    persisted Membership backing it.
    """
    invitation = await get_invitation_by_token(session, raw_token)
    # Captured as plain values up front, deliberately never read off
    # `invitation` again after a possible rollback below — SQLAlchemy
    # expires all attributes of every object touched by a transaction on
    # rollback, and re-accessing one on an AsyncSession outside an
    # explicit await would raise (there is no implicit async lazy-load).
    invitation_id = invitation.id
    invitation_workspace_id = invitation.workspace_id
    invitation_role_id = invitation.role_id
    invitation_invited_by_user_id = invitation.invited_by_user_id

    normalized_actor_email = normalize_email(actor_email)
    if normalized_actor_email != invitation.invited_email:
        raise EmailMismatchError()

    workspace = await session.get(Workspace, invitation_workspace_id)
    if workspace is None or workspace.status == WorkspaceStatus.DELETED:
        raise WorkspaceNotFoundError()

    role = await session.get(Role, invitation_role_id)
    if role is None or not role.is_system_defined:
        raise InvalidRoleError()

    existing_membership = (
        await session.execute(
            select(Membership).where(
                Membership.workspace_id == invitation_workspace_id,
                Membership.user_id == actor_user_id,
                Membership.status == MembershipStatus.ACTIVE,
            )
        )
    ).scalar_one_or_none()

    created = existing_membership is None
    membership = existing_membership or Membership(
        workspace_id=invitation_workspace_id,
        user_id=actor_user_id,
        role_id=invitation_role_id,
        invited_by_user_id=invitation_invited_by_user_id,
        status=MembershipStatus.ACTIVE,
    )
    if created:
        session.add(membership)

    invitation.status = InvitationStatus.ACCEPTED
    invitation.resolved_at = datetime.now(UTC)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        winning_membership = (
            await session.execute(
                select(Membership).where(
                    Membership.workspace_id == invitation_workspace_id,
                    Membership.user_id == actor_user_id,
                    Membership.status == MembershipStatus.ACTIVE,
                )
            )
        ).scalar_one_or_none()
        if winning_membership is None:
            # Structurally unreachable: the IntegrityError itself proves
            # a conflicting active-Membership row exists. Not silently
            # swallowed if this ever somehow occurs.
            raise

        fresh_invitation = await session.get(Invitation, invitation_id)
        fresh_invitation.status = InvitationStatus.ACCEPTED
        fresh_invitation.resolved_at = datetime.now(UTC)
        await session.commit()

        membership = winning_membership
        created = False

    await session.refresh(membership)
    # `.role` is a relationship, never eagerly loaded by the queries
    # above (and lazy-loading isn't available on an AsyncSession) — set
    # explicitly, via a fresh lookup by `membership.role_id`, so the
    # route layer can read `membership.role.name` without triggering
    # one. Deliberately not reusing the `role` object loaded earlier in
    # this function: (a) in the pre-existing-Membership branch, the
    # caller's actual role can differ from what this invitation offered,
    # and (b) after the rollback branch above, objects loaded before the
    # rollback are expired and unsafe to read without an explicit
    # refresh anyway — a fresh `session.get` sidesteps both concerns at
    # once.
    membership.role = await session.get(Role, membership.role_id)

    if created:
        await rbac.invalidate_membership_cache(
            redis, user_id=actor_user_id, workspace_id=invitation_workspace_id
        )

    logger.info(f"Invitation accepted: {invitation_id} (membership={membership.id})")
    return membership, created
