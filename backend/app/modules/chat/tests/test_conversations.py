"""Saved conversations: creation, follow-ups, scoping, privacy and failure
behaviour — real Postgres, fake Gemini (tests/fake_llm.py)."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.chat import retrieval, service
from app.modules.chat.models import Conversation, ConversationMessage, MessageRole
from app.modules.chat.service import (
    NO_DOCUMENTS_ANSWER,
    ConversationNotFoundError,
    LLMUnavailableError,
    make_title,
)
from app.modules.chat.tests.test_retrieval import _upload_text
from app.modules.documents.tests.test_document_service import (  # noqa: F401 (fixture)
    _user_and_workspace,
    isolated_storage,
)
from app.modules.workspaces.models import Membership, Role, RoleName
from tests.db import run_db_test
from tests.fake_llm import FakeLLM


async def _ask(session, ws, user, question, **kwargs):
    return await service.answer_question(
        session, workspace_id=ws, user_id=user.id, question=question, **kwargs
    )


async def _add_member(session: AsyncSession, workspace_id, user) -> None:
    role = await session.scalar(select(Role).where(Role.name == RoleName.MEMBER))
    session.add(Membership(workspace_id=workspace_id, user_id=user.id, role_id=role.id))
    await session.flush()


def test_first_question_creates_conversation_with_both_messages(fake_llm: FakeLLM) -> None:
    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        doc = await _upload_text(session, user, ws, "The launch is in August.")

        conversation_id, answer, citations = await _ask(session, ws, user, "When is the launch?")

        conversation = await session.get(Conversation, conversation_id)
        assert conversation.title == "When is the launch?"
        assert conversation.document_id is None
        messages = (
            await session.execute(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == conversation_id)
                .order_by(ConversationMessage.id)
            )
        ).scalars().all()
        assert [(m.role, m.content) for m in messages] == [
            (MessageRole.USER, "When is the launch?"),
            (MessageRole.ASSISTANT, answer),
        ]
        assert messages[1].citations == citations
        assert citations[0]["document_id"] == str(doc.id)
        assert {"page_start", "page_end", "excerpt", "document_title"} <= citations[0].keys()

    run_db_test(body)


def test_follow_up_uses_history_and_previous_question(
    fake_llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    search_queries: list[str] = []
    real_search = retrieval.search_chunks

    async def spy(db, workspace_id, query, **kwargs):
        search_queries.append(query)
        return await real_search(db, workspace_id, query, **kwargs)

    monkeypatch.setattr(service, "search_chunks", spy)

    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        await _upload_text(session, user, ws, "Q3 revenue target is 2.4 million. Q4 target is 3 million.")

        conversation_id, first_answer, _ = await _ask(session, ws, user, "What is the Q3 revenue target?")
        same_id, _, _ = await _ask(
            session, ws, user, "And for Q4?", conversation_id=conversation_id
        )

        assert same_id == conversation_id
        assert fake_llm.answer_calls[0]["history"] == []
        assert fake_llm.answer_calls[1]["history"] == [
            ("user", "What is the Q3 revenue target?"),
            ("assistant", first_answer),
        ]
        assert search_queries[1] == "What is the Q3 revenue target? And for Q4?"
        count = await session.scalar(
            select(func.count()).where(ConversationMessage.conversation_id == conversation_id)
        )
        assert count == 4

    run_db_test(body)


def test_history_is_limited_to_recent_messages(fake_llm: FakeLLM) -> None:
    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        await _upload_text(session, user, ws, "Some content.")
        conversation_id, _, _ = await _ask(session, ws, user, "question 1")
        for n in range(2, 6):
            await _ask(session, ws, user, f"question {n}", conversation_id=conversation_id)

        history = fake_llm.answer_calls[-1]["history"]
        assert len(history) == service.HISTORY_MESSAGES
        assert history[0] == ("user", "question 2")

    run_db_test(body)


def test_document_conversation_keeps_its_scope(fake_llm: FakeLLM) -> None:
    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        doc_a = await _upload_text(session, user, ws, "Alpha facts about pricing.", "a.txt")
        doc_b = await _upload_text(session, user, ws, "Beta facts about pricing.", "b.txt")

        conversation_id, _, _ = await _ask(session, ws, user, "pricing?", document_id=doc_a.id)
        _, _, citations = await _ask(
            session, ws, user, "pricing again?", conversation_id=conversation_id, document_id=doc_b.id
        )

        assert (await session.get(Conversation, conversation_id)).document_id == doc_a.id
        assert {c["document_id"] for c in citations} == {str(doc_a.id)}

    run_db_test(body)


def test_conversations_are_private_to_their_owner(fake_llm: FakeLLM) -> None:
    async def body(session: AsyncSession) -> None:
        owner, ws = await _user_and_workspace(session)
        teammate, _ = await _user_and_workspace(session)
        await _add_member(session, ws, teammate)
        await _upload_text(session, owner, ws, "Shared workspace content.")
        conversation_id, _, _ = await _ask(session, ws, owner, "private question")

        with pytest.raises(ConversationNotFoundError):
            await _ask(session, ws, teammate, "sneaky follow-up", conversation_id=conversation_id)
        with pytest.raises(ConversationNotFoundError):
            await service.get_conversation(
                session, workspace_id=ws, user_id=teammate.id, conversation_id=conversation_id
            )
        with pytest.raises(ConversationNotFoundError):
            await service.delete_conversation(
                session, workspace_id=ws, user_id=teammate.id, conversation_id=conversation_id
            )
        assert await service.list_conversations(session, workspace_id=ws, user_id=teammate.id) == []

    run_db_test(body)


def test_conversation_id_from_another_workspace_is_not_found(fake_llm: FakeLLM) -> None:
    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        _, other_ws = await _user_and_workspace(session)
        await _upload_text(session, user, ws, "Content.")
        conversation_id, _, _ = await _ask(session, ws, user, "question")

        with pytest.raises(ConversationNotFoundError):
            await service.get_conversation(
                session, workspace_id=other_ws, user_id=user.id, conversation_id=conversation_id
            )

    run_db_test(body)


def test_list_is_newest_first_with_counts_and_document_filter(fake_llm: FakeLLM) -> None:
    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        doc = await _upload_text(session, user, ws, "Content about things.")
        older, _, _ = await _ask(session, ws, user, "older")
        newer, _, _ = await _ask(session, ws, user, "newer", document_id=doc.id)
        await _ask(session, ws, user, "follow-up", conversation_id=older)

        rows = await service.list_conversations(session, workspace_id=ws, user_id=user.id)
        assert [(c.id, count) for c, count in rows] == [(older, 4), (newer, 2)]

        doc_rows = await service.list_conversations(
            session, workspace_id=ws, user_id=user.id, document_id=doc.id
        )
        assert [c.id for c, _ in doc_rows] == [newer]

    run_db_test(body)


def test_delete_removes_conversation_and_messages(fake_llm: FakeLLM) -> None:
    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        await _upload_text(session, user, ws, "Content.")
        conversation_id, _, _ = await _ask(session, ws, user, "question")

        await service.delete_conversation(
            session, workspace_id=ws, user_id=user.id, conversation_id=conversation_id
        )

        assert await session.get(Conversation, conversation_id) is None
        remaining = await session.scalar(
            select(func.count()).where(ConversationMessage.conversation_id == conversation_id)
        )
        assert remaining == 0

    run_db_test(body)


def test_failed_answer_saves_nothing(fake_llm: FakeLLM) -> None:
    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        await _upload_text(session, user, ws, "Content.")
        fake_llm.answers_fail = True

        with pytest.raises(LLMUnavailableError):
            await _ask(session, ws, user, "will this be saved?")
        assert await service.list_conversations(session, workspace_id=ws, user_id=user.id) == []

    run_db_test(body)


def test_question_without_documents_is_still_saved(fake_llm: FakeLLM) -> None:
    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        conversation_id, answer, citations = await _ask(session, ws, user, "anything?")
        assert answer == NO_DOCUMENTS_ANSWER and citations == []
        assert fake_llm.answer_calls == []
        assert await session.get(Conversation, conversation_id) is not None

    run_db_test(body)


def test_titles_are_collapsed_and_truncated() -> None:
    assert make_title("  what   is\nthis? ") == "what is this?"
    long_title = make_title("word " * 50)
    assert len(long_title) <= service.TITLE_CHARS and long_title.endswith("…")
