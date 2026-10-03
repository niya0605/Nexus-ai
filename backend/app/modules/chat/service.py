"""Chat service - Q&A over workspace documents with Gemini."""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.llm import get_llm
from app.modules.chat.retrieval import search_chunks

logger = logging.getLogger(__name__)


class LLMUnavailableError(AppException):
    status_code = 502
    error_code = "llm_unavailable"


async def answer_question(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    question: str,
    document_id: uuid.UUID | None = None,
) -> tuple[str, list[dict]]:
    hits = await search_chunks(db, workspace_id, question, document_id=document_id)
    if not hits:
        return "No processed documents found yet. Upload a document first, then ask again.", []

    context = "\n\n".join(f"[Source: {doc.title}]\n{chunk.content}" for chunk, doc in hits)
    try:
        answer = await get_llm().answer_question(question, context)
    except Exception as exc:
        logger.exception("Gemini request failed")
        raise LLMUnavailableError(f"The AI model request failed: {exc}") from exc

    citations = [
        {
            "chunk_id": str(chunk.id),
            "document_id": str(doc.id),
            "document_title": doc.title,
            "excerpt": chunk.content[:300],
        }
        for chunk, doc in hits
    ]
    return answer, citations
