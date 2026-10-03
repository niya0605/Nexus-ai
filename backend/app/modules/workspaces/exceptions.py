"""Workspace/Membership/Invitation domain exceptions.

Every error code from S1F is quoted directly from its own frozen error
catalog ("Frozen workspace errors include: workspace_not_found → 404,
slug_unavailable → 409, insufficient_permission → 403"; "Frozen
membership errors include: cannot_remove_last_owner → 409,
membership_not_found → 404, insufficient_permission → 403") — no new
code is invented here. Where *which* of two existing codes applies to
a given situation isn't itself specified, that choice is documented on
the exception (or its raise site) as an inference, not a contract quote.

S1G adds the three invitation-specific codes its own error catalog
names explicitly (`invitation_expired` → 410, `invitation_already_resolved`
→ 409, `email_mismatch` → 403), plus two gap-fills for situations S1G's
text raises but doesn't name a code for (`InvitationNotFoundError`,
`AlreadyMemberError`) — each documented at its own definition below,
following the exact same "reuse an existing generic code, don't invent
a new one" precedent `InvalidRoleError` already set in S1F.
"""

from fastapi import status

from app.core.exceptions import AppException


class WorkspaceNotFoundError(AppException):
    """Raised whenever a workspace_id doesn't resolve to a workspace the
    caller may know about — whether it never existed, is soft-deleted,
    or (see `INFERENCE` below) exists but the caller has no active
    Membership in it.

    **INFERENCE, not a contract quote:** S1F explicitly requires "a user
    without an active Membership must not gain access by knowing the
    workspace UUID" and frames this as an anti-enumeration concern the
    same way S1D's `SessionNotFoundError` was. Distinguishing "doesn't
    exist" (404) from "exists but you're not in it" (403) would itself
    leak existence to a non-member — so both collapse to this same 404
    here. `InsufficientPermissionError` is reserved for the case where
    the caller *does* have a confirmed active Membership (existence and
    their own access are already known to them) but their Role's rank
    is too low for the specific action.
    """

    status_code = status.HTTP_404_NOT_FOUND
    error_code = "workspace_not_found"

    def __init__(self) -> None:
        super().__init__("Workspace not found.")


class SlugUnavailableError(AppException):
    """Raised only if server-side slug collision resolution
    (`app.modules.workspaces.service._generate_unique_slug`) is
    exhausted — collisions are auto-resolved transparently (the client
    never supplies a slug at all, per S1F: "resolve according to the
    frozen slug strategy rather than asking the client to provide a
    slug"), so this should be unreachable in practice; kept as the
    last-resort fallback so the frozen code exists and means something
    if it ever is reached, rather than being dead code.
    """

    status_code = status.HTTP_409_CONFLICT
    error_code = "slug_unavailable"

    def __init__(self) -> None:
        super().__init__("Could not generate a unique workspace slug.")


class InsufficientPermissionError(AppException):
    """Raised when the caller has a confirmed active Membership in the
    target workspace, but their Role's rank is below what the action
    requires. See `WorkspaceNotFoundError` for why a *missing*
    Membership is a 404 instead of reaching this exception at all.
    """

    status_code = status.HTTP_403_FORBIDDEN
    error_code = "insufficient_permission"

    def __init__(self) -> None:
        super().__init__("You do not have permission to perform this action.")


class CannotRemoveLastOwnerError(AppException):
    """Raised by both the role-change and membership-removal flows when
    the operation would leave a workspace with zero active Owner-role
    Memberships — the frozen invariant "a Workspace must ALWAYS have at
    least one Owner-role Membership" is unconditional, so this applies
    identically whether the last Owner is being demoted or removed.
    """

    status_code = status.HTTP_409_CONFLICT
    error_code = "cannot_remove_last_owner"

    def __init__(self) -> None:
        super().__init__("Cannot remove or demote the workspace's last owner.")


class MembershipNotFoundError(AppException):
    """Raised when a membership_id doesn't resolve to an (active)
    Membership of the target workspace — including one that belongs to
    a *different* workspace than the URL's workspace_id, which must
    never be distinguished from "doesn't exist at all" (same
    non-enumeration reasoning as `WorkspaceNotFoundError`)."""

    status_code = status.HTTP_404_NOT_FOUND
    error_code = "membership_not_found"

    def __init__(self) -> None:
        super().__init__("Membership not found.")


class InvalidRoleError(AppException):
    """Raised by `change_member_role` when `role_id` doesn't resolve to
    a real, system-defined Role.

    Not in S1F's given error-code list at all (only `workspace_not_found`,
    `slug_unavailable`, `insufficient_permission`, `cannot_remove_last_owner`,
    `membership_not_found` are named) — "do not invent alternate error-
    code names" is honored by reusing `validation_error`, the *existing*
    generic code every Pydantic-driven 422 in this codebase already uses
    (`app/core/exceptions.py`'s `_STATUS_CODES`), rather than adding a
    new workspace-specific one. The response envelope shape still
    differs slightly from a genuine Pydantic 422 (no `details` array,
    since this is a DB-existence check, not a shape/format check) —
    flagged as an implementation-choice inconsistency, not hidden.
    """

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "validation_error"

    def __init__(self) -> None:
        super().__init__("The specified role does not exist or is not a valid system role.")


# ---------------------------------------------------------------------------
# S1G — Invitations
# ---------------------------------------------------------------------------


class InvitationNotFoundError(AppException):
    """Raised when an invitation_id doesn't resolve to an Invitation of
    the target workspace — including one that belongs to a *different*
    workspace than the URL's workspace_id.

    **Gap-fill, not a contract quote:** S1G's error catalog names
    `invitation_expired`, `invitation_already_resolved`, and
    `email_mismatch` explicitly, and separately says to reuse
    `workspace_not_found`/`membership_not_found`/`insufficient_permission`
    "where applicable" — none of those five actually fits "this
    invitation_id simply doesn't exist in this workspace." Reuses the
    generic `not_found` code already established in
    `app/core/exceptions.py`'s `_STATUS_CODES` table, the exact same
    precedent `SessionNotFoundError` (S1D) set for an identical gap, not
    a new invented code.
    """

    status_code = status.HTTP_404_NOT_FOUND
    error_code = "not_found"

    def __init__(self) -> None:
        super().__init__("Invitation not found.")


class InvitationExpiredError(AppException):
    """Raised whenever a pending Invitation's `expires_at` has passed —
    whether discovered via the public token-lookup endpoint or any other
    endpoint that touches a specific invitation (resend, revoke, accept).
    The underlying row is lazily transitioned to `expired` at the moment
    this is raised (see `service._settle_expiry`), so the database
    remains the authoritative record of an expired invitation rather
    than relying on any Redis TTL.

    Frozen: S1G's error catalog states this exactly — 410,
    `invitation_expired`.
    """

    status_code = status.HTTP_410_GONE
    error_code = "invitation_expired"

    def __init__(self) -> None:
        super().__init__("This invitation has expired.")


class InvitationAlreadyResolvedError(AppException):
    """Raised whenever an operation targets an Invitation whose status is
    already `accepted` or `revoked` (a terminal state reached by an
    explicit action, as opposed to `InvitationExpiredError`'s passive
    time-based transition) — "an already-resolved invitation must not be
    silently mutated."

    Frozen: S1G's error catalog states this exactly — 409,
    `invitation_already_resolved`.
    """

    status_code = status.HTTP_409_CONFLICT
    error_code = "invitation_already_resolved"

    def __init__(self) -> None:
        super().__init__("This invitation has already been resolved.")


class EmailMismatchError(AppException):
    """Raised by `accept_invitation` when the authenticated caller's
    normalized email doesn't match the invitation's `invited_email` —
    "do not allow User A to accept User B's invitation."

    Frozen: S1G states this exactly — 403, `email_mismatch`.
    """

    status_code = status.HTTP_403_FORBIDDEN
    error_code = "email_mismatch"

    def __init__(self) -> None:
        super().__init__("This invitation was sent to a different email address.")


class AlreadyMemberError(AppException):
    """Raised by `create_invitation` when the target email already
    belongs to an active Member of the workspace.

    **Gap-fill, not a contract quote:** S1G explicitly anticipates this
    case ("Check whether the target user is already an active member of
    the workspace... follow the frozen contract behavior. Do not invent
    a new public error code if one is not specified") but no frozen
    document defines what that behavior is. Blocking the invitation
    outright (rather than silently creating a redundant one, or silently
    no-op-succeeding) is the safer minimal interpretation — an
    invitation that could never be meaningfully accepted (the target
    already has membership; accepting it would just leave the existing
    Membership untouched, see `accept_invitation`) is more useful to the
    admin as an explicit signal than as a silently accepted no-op.
    Reuses the existing generic `conflict` code (`_STATUS_CODES`, 409)
    rather than inventing an invitation-specific one.
    """

    status_code = status.HTTP_409_CONFLICT
    error_code = "conflict"

    def __init__(self) -> None:
        super().__init__("This user is already an active member of the workspace.")
