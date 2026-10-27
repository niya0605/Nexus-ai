"""Chat service - Q&A over workspace documents with Gemini."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.llm import LLMError, get_llm
from app.modules.chat.retrieval import search_chunks


class LLMUnavailableError(AppException):
    status_code = 502
    error_code = "llm_unavailable"


def _page_label(page_start: int, page_end: int) -> str:
    if page_start <= 0:
        return ""
    return f", page {page_start}" if page_start == page_end else f", pages {page_start}-{page_end}"


async def answer_question(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    question: str,
    document_id: uuid.UUID | None = None,
) -> tuple[str, list[dict]]:
    hits = await search_chunks(db, workspace_id, question, document_id=document_id)
    if not hits:
        return "No processed documents found yet. Upload a document first, then ask again.", []

    context = "\n\n".join(
        f"[Source: {doc.title}{_page_label(chunk.page_start, chunk.page_end)}]\n{chunk.content}"
        for chunk, doc in hits
    )
    try:
        answer = await get_llm().answer_question(question, context)
    except LLMError as exc:
        raise LLMUnavailableError(str(exc)) from exc

    citations = [
        {
            "chunk_id": str(chunk.id),
            "document_id": str(doc.id),
            "document_title": doc.title,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "excerpt": chunk.content[:300],
        }
        for chunk, doc in hits
    ]
    return answer, citations
