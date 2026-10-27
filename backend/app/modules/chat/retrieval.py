"""Hybrid retrieval: pgvector semantic search + Postgres full-text search,
merged with Reciprocal Rank Fusion (RRF)."""

import logging
import re
import uuid

from sqlalchemy import Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.core.llm import LLMError, get_llm
from app.modules.documents.chunks import Chunk
from app.modules.documents.models import Document, DocumentStatus

logger = logging.getLogger(__name__)

# How many candidates each search contributes before fusion.
CANDIDATES_PER_SEARCH = 20
# Standard RRF damping constant: higher values flatten the advantage of rank 1.
RRF_K = 60

_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "to", "of", "in", "on", "for",
    "and", "or", "what", "which", "who", "whom", "how", "why", "when", "where", "does",
    "do", "did", "this", "that", "these", "those", "it", "its", "about", "with", "as",
    "by", "at", "from", "can", "you", "me", "tell", "explain", "please", "i", "my",
}

Hit = tuple[Chunk, Document]


def query_terms(query: str) -> list[str]:
    """Lowercase alphanumeric terms minus stop-words — safe to put in a tsquery."""
    seen: dict[str, None] = {}
    for term in re.findall(r"[a-z0-9]+", query.lower()):
        if term not in _STOPWORDS and len(term) > 1:
            seen[term] = None
    return list(seen)


def _scoped(workspace_id: uuid.UUID, document_id: uuid.UUID | None) -> Select:
    stmt = (
        select(Chunk, Document)
        # Ranking happens in SQL; don't ship 768 floats per row back to Python.
        .options(defer(Chunk.embedding), defer(Chunk.tsv))
        .join(Document, Chunk.document_id == Document.id)
        .where(Document.workspace_id == workspace_id, Document.status == DocumentStatus.READY)
    )
    if document_id is not None:
        stmt = stmt.where(Document.id == document_id)
    return stmt


async def _vector_search(
    db: AsyncSession, base: Select, query: str
) -> list[Hit]:
    try:
        query_vector = await get_llm().embed_query(query)
    except LLMError as exc:
        logger.warning("Semantic search skipped, using keywords only: %s", exc)
        return []
    # Keep scanning the HNSW index until enough rows survive the workspace filter.
    await db.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
    rows = await db.execute(
        base.where(Chunk.embedding.is_not(None))
        .order_by(Chunk.embedding.cosine_distance(query_vector))
        .limit(CANDIDATES_PER_SEARCH)
    )
    return [(chunk, doc) for chunk, doc in rows.all()]


async def _keyword_search(db: AsyncSession, base: Select, query: str) -> list[Hit]:
    terms = query_terms(query)
    if not terms:
        return []
    # OR the terms: plainto/websearch_to_tsquery would AND them, which almost
    # never matches a natural-language question.
    ts_query = func.to_tsquery("english", " | ".join(terms))
    rows = await db.execute(
        base.where(Chunk.tsv.op("@@")(ts_query))
        .order_by(func.ts_rank_cd(Chunk.tsv, ts_query).desc(), Chunk.id)
        .limit(CANDIDATES_PER_SEARCH)
    )
    return [(chunk, doc) for chunk, doc in rows.all()]


def reciprocal_rank_fusion(*ranked_lists: list[Hit], limit: int) -> list[Hit]:
    scores: dict[uuid.UUID, float] = {}
    hits: dict[uuid.UUID, Hit] = {}
    for ranked in ranked_lists:
        for rank, hit in enumerate(ranked, start=1):
            chunk_id = hit[0].id
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
            hits[chunk_id] = hit
    best = sorted(scores, key=lambda chunk_id: scores[chunk_id], reverse=True)[:limit]
    return [hits[chunk_id] for chunk_id in best]


async def search_chunks(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    query: str,
    document_id: uuid.UUID | None = None,
    limit: int = 5,
) -> list[Hit]:
    base = _scoped(workspace_id, document_id)
    semantic = await _vector_search(db, base, query)
    keyword = await _keyword_search(db, base, query)

    if semantic or keyword:
        return reciprocal_rank_fusion(semantic, keyword, limit=limit)

    # Nothing embedded and no keyword overlap (e.g. "summarize this"): give the
    # model the opening chunks so broad questions still get an answer.
    rows = await db.execute(base.order_by(Document.created_at.desc(), Chunk.id).limit(limit))
    return [(chunk, doc) for chunk, doc in rows.all()]
