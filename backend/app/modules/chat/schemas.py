"""Chat schemas."""
from pydantic import BaseModel, Field
import uuid
from datetime import datetime

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    document_id: uuid.UUID | None = None

class ChatResponse(BaseModel):
    message: str
    citations: list[dict] = []

class MessagePublic(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    created_at: datetime
    class Config:
        from_attributes = True
