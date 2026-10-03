"""Keyword retrieval over a workspace's document chunks."""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.chunks import Chunk
from app.modules.documents.models import Document, DocumentStatus

_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "to", "of", "in", "on", "for",
    "and", "or", "what", "which", "who", "whom", "how", "why", "when", "where", "does",
    "do", "did", "this", "that", "these", "those", "it", "its", "about", "with", "as",
    "by", "at", "from", "can", "you", "me", "tell", "explain", "please", "i", "my",
}


def _terms(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS and len(t) > 1}


async def search_chunks(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    query: str,
    document_id: uuid.UUID | None = None,
    limit: int = 5,
) -> list[tuple[Chunk, Document]]:
    """Rank chunks by query-term overlap. Falls back to the first chunks when
    nothing matches, so broad questions ("summarize this") still get context."""
    stmt = (
        select(Chunk, Document)
        .join(Document, Chunk.document_id == Document.id)
        .where(Document.workspace_id == workspace_id, Document.status == DocumentStatus.READY)
        .order_by(Document.created_at.desc(), Chunk.id)
    )
    if document_id is not None:
        stmt = stmt.where(Document.id == document_id)

    rows = (await db.execute(stmt)).all()
    if not rows:
        return []

    query_terms = _terms(query)
    scored = []
    for position, (chunk, doc) in enumerate(rows):
        content = chunk.content.lower()
        score = sum(content.count(term) for term in query_terms)
        scored.append((score, -position, chunk, doc))

    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
    if scored[0][0] == 0:
        return [(chunk, doc) for chunk, doc in rows[:limit]]
    return [(chunk, doc) for score, _, chunk, doc in scored[:limit] if score > 0]
