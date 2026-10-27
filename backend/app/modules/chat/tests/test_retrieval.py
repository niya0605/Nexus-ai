"""Hybrid retrieval (pgvector + full-text + RRF) against real Postgres, with the
fake embedder from tests/fake_llm.py."""

import uuid
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.chat.retrieval import query_terms, reciprocal_rank_fusion, search_chunks
from app.modules.chat.service import answer_question
from app.modules.documents.chunks import Chunk
from app.modules.documents.models import DocumentStatus
from app.modules.documents.service import create_document, embed_missing_chunks
from app.modules.documents.tests.test_document_service import (  # noqa: F401 (fixture)
    _user_and_workspace,
    isolated_storage,
)
from tests.db import run_db_test
from tests.fake_llm import FakeLLM


async def _upload_text(session: AsyncSession, user, workspace_id, text: str, name: str = "notes.txt"):
    return await create_document(
        db=session,
        workspace_id=workspace_id,
        user_id=user.id,
        title=name,
        original_filename=name,
        file_type="txt",
        file_content=text.encode(),
    )


def test_semantic_match_without_shared_words(fake_llm: FakeLLM) -> None:
    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        await _upload_text(session, user, ws, "The quarterly income goal is 2.4 million.", "finance.txt")
        await _upload_text(session, user, ws, "Soup and salad are served on Mondays.", "food.txt")

        hits = await search_chunks(session, ws, "How much money will we earn?")
        assert hits[0][1].title == "finance.txt"

    run_db_test(body)


def test_uploaded_chunks_are_embedded(fake_llm: FakeLLM) -> None:
    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        doc = await _upload_text(session, user, ws, "Embedded text.")
        embedded = await session.scalar(
            select(func.count()).where(Chunk.document_id == doc.id, Chunk.embedding.is_not(None))
        )
        assert embedded == 1

    run_db_test(body)


def test_embedding_outage_at_upload_keeps_document_searchable(fake_llm: FakeLLM) -> None:
    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        fake_llm.embedding_available = False
        doc = await _upload_text(session, user, ws, "Priya Sharma owns the onboarding redesign.")

        assert doc.status == DocumentStatus.READY
        chunk = await session.scalar(select(Chunk).where(Chunk.document_id == doc.id))
        assert chunk.embedding is None

        hits = await search_chunks(session, ws, "who owns onboarding?")
        assert [h[1].id for h in hits] == [doc.id]

    run_db_test(body)


def test_embedding_outage_at_question_time_falls_back_to_keywords(fake_llm: FakeLLM) -> None:
    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        await _upload_text(session, user, ws, "Pricing stays flat at 4.50 per cup.", "pricing.txt")
        await _upload_text(session, user, ws, "The office closes at 6pm.", "office.txt")
        fake_llm.embedding_available = False

        hits = await search_chunks(session, ws, "what about pricing?")
        assert [h[1].title for h in hits] == ["pricing.txt"]

    run_db_test(body)


def test_backfill_embeds_missing_chunks(fake_llm: FakeLLM) -> None:
    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        fake_llm.embedding_available = False
        doc = await _upload_text(session, user, ws, "Needs an embedding later.")
        fake_llm.embedding_available = True

        while await embed_missing_chunks(session):
            pass
        chunk = await session.scalar(select(Chunk).where(Chunk.document_id == doc.id))
        assert chunk.embedding is not None

    run_db_test(body)


def test_search_never_crosses_workspaces(fake_llm: FakeLLM) -> None:
    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        _, other_ws = await _user_and_workspace(session)
        await _upload_text(session, user, other_ws, "Secret revenue numbers for another team.")

        assert await search_chunks(session, ws, "revenue") == []

    run_db_test(body)


def test_broad_question_falls_back_to_opening_chunks(fake_llm: FakeLLM) -> None:
    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        fake_llm.embedding_available = False
        doc = await _upload_text(session, user, ws, "Alpha beta gamma.")

        hits = await search_chunks(session, ws, "summarize this")
        assert [h[1].id for h in hits] == [doc.id]

    run_db_test(body)


def test_answer_includes_page_aware_citations(fake_llm: FakeLLM) -> None:
    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        doc = await _upload_text(session, user, ws, "The launch is in August.")

        answer, citations = await answer_question(session, ws, "When is the launch?")
        assert answer.startswith("fake answer")
        assert citations[0]["document_id"] == str(doc.id)
        assert {"page_start", "page_end", "excerpt", "document_title"} <= citations[0].keys()

    run_db_test(body)


def test_rrf_prefers_chunks_found_by_both_searches() -> None:
    def hit(name: str):
        return (SimpleNamespace(id=uuid.uuid5(uuid.NAMESPACE_OID, name)), name)

    a, b, c, d = hit("a"), hit("b"), hit("c"), hit("d")
    fused = reciprocal_rank_fusion([a, b, c], [d, c], limit=4)
    assert fused[0] == c  # 2nd/3rd in each list beats 1st in only one
    assert {h[1] for h in fused} == {"a", "b", "c", "d"}
    assert len(reciprocal_rank_fusion([a, b, c], [d], limit=2)) == 2


def test_query_terms_are_safe_for_tsquery() -> None:
    assert query_terms("What's the revenue & | !target: (Q3)?") == ["revenue", "target", "q3"]
    assert query_terms("the a of") == []
