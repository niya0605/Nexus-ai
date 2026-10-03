"""Pydantic schemas for documents."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.documents.models import DocumentStatus


class DocumentCreate(BaseModel):
    """Request to create/upload a document."""
    title: str = Field(..., min_length=1, max_length=255)
    file_type: str = Field(..., pattern="^(pdf|docx|txt|md)$")


class DocumentPublic(BaseModel):
    """Public view of a document."""
    id: uuid.UUID
    workspace_id: uuid.UUID
    title: str
    original_filename: str
    file_type: str
    file_size_bytes: int
    status: DocumentStatus
    summary: str | None = None
    uploaded_by_user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    deleted_at: datetime | None = None

    class Config:
        from_attributes = True


class DocumentText(BaseModel):
    text: str
    has_original: bool


class ChunkPublic(BaseModel):
    """A searchable chunk of a document."""
    id: uuid.UUID
    document_id: uuid.UUID
    page_start: int
    page_end: int
    content: str
    created_at: datetime

    class Config:
        from_attributes = True

