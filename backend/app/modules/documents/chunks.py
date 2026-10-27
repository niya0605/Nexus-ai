"""Chunk model for document content (semantic + full-text retrieval)."""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.llm import EMBEDDING_DIMENSIONS
from app.db.base import Base
from app.utils.ids import generate_uuid7


class Chunk(Base):
    """A piece of document content (always within one page), embedded for
    semantic search and indexed for full-text search."""

    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
        Index("ix_chunks_document_pages", "document_id", "page_start", "page_end"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
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
    # 1-based PDF page; 0 for formats without pages (DOCX, TXT, MD).
    page_start: Mapped[int] = mapped_column(nullable=False)
    page_end: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Filled by the tsvector_update trigger from `content`.
    tsv: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)
    # NULL until embedded (e.g. the embedding API was unavailable at upload).
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped["Document"] = relationship("Document", back_populates="chunks")  # noqa: F821
