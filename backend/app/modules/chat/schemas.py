"""Chat request/response schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.chat.models import MessageRole


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    # Start a new conversation scoped to this document (ignored when continuing).
    document_id: uuid.UUID | None = None
    # Continue an existing conversation; omit to start a new one.
    conversation_id: uuid.UUID | None = None


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    message: str
    citations: list[dict] = []


class ConversationSummary(BaseModel):
    id: uuid.UUID
    title: str
    document_id: uuid.UUID | None
    message_count: int
    created_at: datetime
    updated_at: datetime


class MessagePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: MessageRole
    content: str
    citations: list[dict]
    created_at: datetime


class ConversationDetail(BaseModel):
    id: uuid.UUID
    title: str
    document_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    messages: list[MessagePublic]
