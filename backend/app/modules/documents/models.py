"""Document, DocumentVersion, and ProcessingJob models (S2A).

`Document`/`DocumentVersion` field lists, statuses, and constraints are
taken directly from S2A's own specification (quoted verbatim in each
class's docstring below) — the frozen Data Dictionary/PostgreSQL
Database Design themselves are not files in this repository (same
situation every prior sprint has documented: docs/database/README.md
marks `DATABASE_DESIGN.md` "not yet added"), so S2A's own prompt text is
the closest available authoritative source, exactly as S1F/S1G treated
their own specs.

`ProcessingJob` is explicitly **not** given a field list by S2A ("only
implement enough ProcessingJob infrastructure to satisfy the frozen
document upload/version-restore contract... create the ProcessingJob
model... only if required") — its shape here is this sprint's own
minimal design, flagged as an UNRESOLVED CONTRACT GAP in the same way
S1F's `AuditLog` was: the *requirement* (a durable job record tied to a
Document/DocumentVersion) is frozen; the exact columns are not.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.utils.db_enum import string_enum
from app.utils.ids import generate_uuid7


class DocumentStatus(str, enum.Enum):
    """Frozen lifecycle: "Uploading → Processing → Ready / Failed →
    Archived / Deleted." `ARCHIVED`/`DELETED` are reachable from
    `READY` or `FAILED` (an upload that never finished processing can
    still be archived/deleted — nothing in S2A's text restricts those
    two transitions to `READY` only)."""

    UPLOADING = "uploading"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    ARCHIVED = "archived"
    DELETED = "deleted"


class DocumentVersionStatus(str, enum.Enum):
    """Frozen: "status ∈ current, superseded" — exactly two values, no
    third "failed"/"error" state (see `Document.status` for how a
    storage failure is represented instead — at the Document level, not
    here)."""

    CURRENT = "current"
    SUPERSEDED = "superseded"


class ProcessingJobStatus(str, enum.Enum):
    """**Not a frozen enum** — S2A gives no field list for ProcessingJob
    at all. `QUEUED` is the only value any code in this sprint actually
    sets (every job created here has no worker yet to advance it);
    `PROCESSING`/`COMPLETED` are defined now so the column's shape
    doesn't need a migration change the moment a future sprint's worker
    exists to use them. `FAILED` *is* set by this sprint — the one case
    where a job can be known, synchronously, to never be runnable: the
    object-storage write it depends on failed (see
    `app.modules.documents.service`'s upload-failure compensation path).
    """

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Document(Base):
    """A workspace's uploaded file, tracked independently of its
    content history (see `DocumentVersion`). See this module's own
    docstring for why the exact field list below is quoted from S2A's
    own prompt rather than a frozen Data Dictionary entry.

    Frozen fields (S2A): id, workspace_id, title, original_filename,
    file_type, file_size_bytes, storage_key, status, current_version_id,
    summary, uploaded_by_user_id, created_at, updated_at, archived_at,
    deleted_at.

    `current_version_id` is nullable **by frozen design, not an
    oversight** — S2A: "A Document may initially have current_version_id
    = NULL. It becomes populated once the first version completes the
    relevant processing lifecycle... do not 'fix' this by making the
    column NOT NULL." See `app.modules.documents.service.upload_document`
    for exactly when this sprint populates it (its own documented
    IMPLEMENTATION CHOICE, since no real processing pipeline exists yet
    to define "completes the relevant processing lifecycle" more
    precisely).

    Soft-delete only: `deleted_at` records the transition; the row
    itself, and every `DocumentVersion` under it, are never physically
    removed by anything in this sprint — "historical integrity must be
    preserved."
    """

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('uploading', 'processing', 'ready', 'failed', 'archived', 'deleted')",
            name="chk_documents_status",
        ),
        CheckConstraint("file_size_bytes > 0", name="chk_documents_file_size_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=generate_uuid7
    )
    # CASCADE — a Document has no purpose once its Workspace is gone,
    # the identical reasoning already applied to Membership/Invitation/
    # WorkspaceSettings (S1F/S1G) for the same FK target.
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # IMPLEMENTATION CHOICE — column widths: no frozen Data Dictionary
    # length exists for either string field; 255 is a conventional
    # "single display line" ceiling, matching
    # `app.core.validation.MAX_DOCUMENT_TITLE_LENGTH`.
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # Short vocabulary token (pdf/docx/txt/md — see
    # app.modules.documents.validation.SUPPORTED_FILE_TYPES), not a MIME
    # type string.
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # BigInteger, not Integer — a plain 32-bit int overflows at 2 GiB,
    # a plausible document size even under a configured
    # max_document_size_mb ceiling in the hundreds/thousands.
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    status: Mapped[DocumentStatus] = mapped_column(
        string_enum(DocumentStatus, length=20, name="document_status"),
        nullable=False,
        default=DocumentStatus.UPLOADING,
        index=True,
    )
    # Nullable — see this class's own docstring. SET NULL, not RESTRICT:
    # a Document's own record of "which version is current" is
    # informational/derived, not load-bearing the way e.g.
    # Invitation.invited_by_user_id is for its own row's meaning.
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
        default=None,
    )
    # AI-generated summary — frozen *field*, not frozen *content*. No AI
    # pipeline exists yet (explicitly out of S2A's scope); always NULL
    # until a future sprint's pipeline populates it. Never fabricated.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # RESTRICT, not SET NULL — same reasoning already applied to
    # Invitation.invited_by_user_id (S1A) and AuditLog.actor_user_id
    # (S1F): who uploaded a document is never allowed to become an
    # orphaned/unknown reference. IMPLEMENTATION CHOICE — S2A's own
    # field list names the column but not its ON DELETE behavior.
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    versions: Mapped[list["DocumentVersion"]] = relationship(
        "DocumentVersion",
        back_populates="document",
        cascade="all, delete-orphan",
        foreign_keys="DocumentVersion.document_id",
    )
    # `viewonly=True` — this application always sets `current_version_id`
    # directly as a plain column assignment (never via this relationship
    # object), so there is no ORM flush-ordering concern to manage here,
    # unlike a relationship the ORM itself is responsible for persisting.
    current_version: Mapped["DocumentVersion | None"] = relationship(
        "DocumentVersion", foreign_keys=[current_version_id], viewonly=True
    )
    chunks: Mapped[list["Chunk"]] = relationship(
        "Chunk", back_populates="document", cascade="all, delete-orphan"
    )


class DocumentVersion(Base):
    """Immutable content history for one `Document`. See this module's
    own docstring for why the field list below is quoted from S2A's own
    prompt.

    Frozen fields (S2A): id, document_id, version_number, storage_key,
    file_size_bytes, checksum, status, created_by_user_id, created_at,
    updated_at.

    "A DocumentVersion is immutable content history. Do not edit a
    superseded version in place." Nothing in this codebase ever
    `UPDATE`s a version's `storage_key`/`checksum`/`file_size_bytes`
    after creation — the only column this application ever writes to an
    existing row is `status` (current → superseded, or back, on
    restore).
    """

    __tablename__ = "document_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('current', 'superseded')", name="chk_document_versions_status"
        ),
        CheckConstraint("version_number >= 1", name="chk_document_versions_version_number"),
        CheckConstraint("file_size_bytes > 0", name="chk_document_versions_file_size_positive"),
        UniqueConstraint(
            "document_id", "version_number", name="uq_document_versions_document_version_number"
        ),
        # Partial unique index — "exactly one current version must exist
        # once the document has a processed version" — the same
        # technique already established for Invitation's pending-
        # uniqueness and Membership's active-uniqueness (S1A/S1F): a
        # superseded version never blocks a new current one, and the
        # database — not application code — is the final invariant.
        Index(
            "uq_document_versions_document_current",
            "document_id",
            unique=True,
            postgresql_where=text("status = 'current'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=generate_uuid7
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # SHA-256 hex digest — see app.modules.documents.checksum's own
    # docstring for the algorithm choice. 64 chars, fixed width.
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[DocumentVersionStatus] = mapped_column(
        string_enum(DocumentVersionStatus, length=20, name="document_version_status"),
        nullable=False,
        default=DocumentVersionStatus.CURRENT,
        index=True,
    )
    # RESTRICT — same reasoning as Document.uploaded_by_user_id.
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    document: Mapped["Document"] = relationship(
        "Document", back_populates="versions", foreign_keys=[document_id]
    )
    jobs: Mapped[list["ProcessingJob"]] = relationship(
        "ProcessingJob", back_populates="document_version", cascade="all, delete-orphan"
    )


class ProcessingJob(Base):
    """Durable reference to "this Document/DocumentVersion needs (re-)
    processing" — the foundation S2A's upload and version-restore flows
    create, with no worker yet to consume it. See this module's own
    docstring: **not a frozen entity**; every field below is this
    sprint's own minimal design, flagged as an UNRESOLVED CONTRACT GAP
    (the requirement that a durable job record must exist is frozen; its
    exact shape is not).

    Created exactly three times in this sprint's own code: initial
    upload, new-version upload, and version restore — always `QUEUED`,
    always naming both the `Document` and the specific `DocumentVersion`
    it's meant to process. Never transitioned to `PROCESSING`/`COMPLETED`
    by anything in S2A (no worker exists); *is* transitioned to `FAILED`
    when the version's own content never made it into object storage in
    the first place (see `service.py`'s upload-failure compensation).
    """

    __tablename__ = "processing_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed')",
            name="chk_processing_jobs_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=generate_uuid7
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Distinguishes "why was this job created" for a future dispatcher —
    # this sprint's own design, not a frozen vocabulary.
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[ProcessingJobStatus] = mapped_column(
        string_enum(ProcessingJobStatus, length=20, name="processing_job_status"),
        nullable=False,
        default=ProcessingJobStatus.QUEUED,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    document: Mapped["Document"] = relationship("Document")
    document_version: Mapped["DocumentVersion"] = relationship(
        "DocumentVersion", back_populates="jobs"
    )
