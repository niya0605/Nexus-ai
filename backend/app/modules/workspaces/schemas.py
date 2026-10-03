"""Request/response schemas for the workspaces module.

Field-level validation reuses the centralized normalizer in
app/core/validation.py (`normalize_workspace_name`), same convention as
the auth module's schemas.

**IMPLEMENTATION CHOICE — several response shapes below aren't given by
a frozen document** (the REST API Contract isn't a file in this
repository — docs/api/README.md). Specifically: `WorkspaceCreateData`'s
`{workspace, membership}` pairing, `MemberEntry`'s flat `role: str`
(vs. a nested role object), and `email` being present-but-nullable on
`MemberUserInfo` rather than the field being omitted outright for non-
admins. Each is flagged again at its definition.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from app.core.validation import normalize_email, normalize_workspace_name
from app.modules.workspaces.models import InvitationStatus, MembershipStatus, WorkspaceStatus

# Frozen — S1F: "the supported upload formats already frozen by the
# Data Dictionary: pdf, docx, txt, md".
ALLOWED_FILE_TYPES = ("pdf", "docx", "txt", "md")
MIN_MAX_DOCUMENT_SIZE_MB = 1
# IMPLEMENTATION CHOICE: S1F requires max_document_size_mb to be "a
# valid positive configured size" without an upper bound — 1024 (1 GB)
# is a reasonable sanity ceiling against an obviously-wrong value (e.g.
# a typo of several extra zeros), not a frozen limit.
MAX_MAX_DOCUMENT_SIZE_MB = 1024


class CreateWorkspaceRequest(BaseModel):
    """POST /api/v1/workspaces request body."""

    name: str

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        return normalize_workspace_name(value)


class UpdateWorkspaceRequest(BaseModel):
    """PATCH /api/v1/workspaces/{workspace_id} request body — name only.
    `slug`/`status`/`created_at`/`archived_at`/`deleted_at` are
    deliberately absent from this schema, not merely ignored if sent:
    the frozen contract says the server derives the slug, and none of
    the others are documented as client-mutable through this endpoint.
    """

    name: str

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        return normalize_workspace_name(value)


class WorkspacePublic(BaseModel):
    """The public projection of a Workspace — every frozen field."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    status: WorkspaceStatus
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    deleted_at: datetime | None


class MembershipPublic(BaseModel):
    """A caller's own membership — returned as part of workspace
    creation's response (the founding membership). No privacy concern
    here (it's always the caller's own row), unlike `MemberEntry` below.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    status: MembershipStatus
    created_at: datetime


class WorkspaceCreateData(BaseModel):
    """**IMPLEMENTATION CHOICE:** POST /api/v1/workspaces's `data`
    payload. S1F says to "return the workspace representation and
    founding membership as required by the frozen response contract"
    without giving that shape — this pairs both under named keys rather
    than inventing a merged/flattened object.
    """

    workspace: WorkspacePublic
    membership: MembershipPublic


class WorkspaceSettingsPublic(BaseModel):
    """Every WorkspaceSettings field — "return the existing
    WorkspaceSettings fields only", so nothing beyond what the model
    itself defines."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    document_retention_days: int | None
    allowed_file_types: list[str]
    max_document_size_mb: int
    created_at: datetime
    updated_at: datetime


class UpdateWorkspaceSettingsRequest(BaseModel):
    """PATCH .../settings request body — every field optional (a PATCH
    updates only what's supplied); `None` is a real, valid value for
    `document_retention_days` (its own "nullable override" semantics —
    S1F), so this schema distinguishes "field omitted" from "field
    explicitly set to null" via `model_fields_set` at the service layer,
    not by treating `None` as "don't touch this field".
    """

    document_retention_days: int | None = None
    allowed_file_types: list[str] | None = None
    max_document_size_mb: int | None = None

    @field_validator("allowed_file_types")
    @classmethod
    def _validate_allowed_file_types(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("allowed_file_types cannot be empty")
        unknown = set(value) - set(ALLOWED_FILE_TYPES)
        if unknown:
            raise ValueError(
                f"Unsupported file type(s): {sorted(unknown)}. "
                f"Allowed: {sorted(ALLOWED_FILE_TYPES)}"
            )
        return value

    @field_validator("max_document_size_mb")
    @classmethod
    def _validate_max_document_size_mb(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if not (MIN_MAX_DOCUMENT_SIZE_MB <= value <= MAX_MAX_DOCUMENT_SIZE_MB):
            raise ValueError(
                f"max_document_size_mb must be between {MIN_MAX_DOCUMENT_SIZE_MB} "
                f"and {MAX_MAX_DOCUMENT_SIZE_MB}"
            )
        return value

    @field_validator("document_retention_days")
    @classmethod
    def _validate_document_retention_days(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("document_retention_days must be a positive integer, or null")
        return value


class MemberUserInfo(BaseModel):
    """The nested `user` object in a membership-list entry.

    **IMPLEMENTATION CHOICE:** `email` is always present on this schema
    but `None` unless the caller's own role is Admin+ (populated by the
    service layer, per S1F: "never expose email to non-Admin viewers;
    Admins may receive email according to the frozen privacy
    behavior") — chosen over omitting the field entirely so the
    response shape doesn't change per caller, which keeps client-side
    parsing uniform. Never `password_hash` or any other Restricted
    field — this schema doesn't define one to leak in the first place.
    """

    id: uuid.UUID
    display_name: str
    avatar_url: str | None
    email: str | None = None


class MemberEntry(BaseModel):
    """One row of GET .../members's list.

    **IMPLEMENTATION CHOICE:** `role` is the role's plain name string
    (e.g. `"owner"`), not a nested `{id, name}` object — S1F's field
    list just says `role` alongside `status`/`created_at`, which reads
    as another simple scalar, not a structured value.
    """

    id: uuid.UUID
    user: MemberUserInfo
    role: str
    status: MembershipStatus
    created_at: datetime


class UpdateMembershipRoleRequest(BaseModel):
    """PATCH .../members/{membership_id} request body."""

    role_id: uuid.UUID


# ---------------------------------------------------------------------------
# S1G — Invitations
# ---------------------------------------------------------------------------
class CreateInvitationRequest(BaseModel):
    """POST .../invitations request body — S1G gives this shape exactly:
    `{"email": "...", "role_id": "..."}`."""

    email: str
    role_id: uuid.UUID

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return normalize_email(value)


class InvitationPublic(BaseModel):
    """**IMPLEMENTATION CHOICE:** the projection returned by invitation
    create/list/resend — no frozen response shape exists for any of the
    three (the REST API Contract isn't a file in this repository). Every
    Invitation field *except* `token_hash` (never returned — S1G: "never
    expose the raw token" and "do not return token_hash"). `role` is a
    plain name string, matching `MemberEntry.role`'s existing precedent
    rather than a nested object.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    invited_email: str
    role: str
    status: InvitationStatus
    invited_by_user_id: uuid.UUID
    created_at: datetime
    expires_at: datetime
    resolved_at: datetime | None


class PublicInvitationDetails(BaseModel):
    """**IMPLEMENTATION CHOICE:** `GET /api/v1/invitations/{token}`'s
    response — no frozen shape exists. Deliberately narrower than
    `InvitationPublic`: this is a *public, unauthenticated* endpoint, so
    only what the invitee needs to decide whether to accept is included.
    `invited_by_user_id` is left out on purpose (an internal actor ID
    with no use to an unauthenticated caller — see S1G: "do not expose
    unrelated ... internal IDs beyond the frozen response shape"). Never
    `token_hash`/the raw token/any other invitation belonging to a
    different token — see `service.get_invitation_by_token`.
    """

    id: uuid.UUID
    workspace_id: uuid.UUID
    workspace_name: str
    invited_email: str
    role: str
    status: InvitationStatus
    expires_at: datetime
