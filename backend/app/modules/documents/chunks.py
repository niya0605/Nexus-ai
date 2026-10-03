"""Chunk model for document content (embeddings, retrieval)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID, TSVECTOR, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.utils.ids import generate_uuid7


class Chunk(Base):
    """A piece of document content, embedded for vector search and indexed
    for full-text search. One document is split into many chunks with
    overlapping context preserved.

    Embeddings are stored as JSON arrays of floats.
    When deployed to a managed PostgreSQL with pgvector, they'll be converted
    to pgvector type for better performance.
    """

    __tablename__ = "chunks"
    __table_args__ = (
        # Full-text search index
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
        # Document + page lookup for context retrieval
        Index("ix_chunks_document_pages", "document_id", "page_start", "page_end"),
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
    # Page range for this chunk (inclusive)
    page_start: Mapped[int] = mapped_column(nullable=False)
    page_end: Mapped[int] = mapped_column(nullable=False)
    # Plain text content of this chunk
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Full-text search vector (automatically generated from content via trigger)
    tsv: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)
    # Vector embedding stored as JSON (for local dev; pgvector in production)
    # Format: [0.123, 0.456, ..., 0.789] (1536 dimensions)
    embedding_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped["Document"] = relationship("Document", back_populates="chunks")

