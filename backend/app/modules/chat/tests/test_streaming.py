"""Streaming answers and cited-only sources — real Postgres, fake Gemini
(tests/fake_llm.py)."""

import json
import uuid
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.chat import service
from app.modules.chat.models import Conversation, ConversationMessage
from app.modules.chat.service import NO_DOCUMENTS_ANSWER, build_citations, build_context
from app.modules.chat.tests.test_retrieval import _upload_text
from app.modules.documents.tests.test_document_service import (  # noqa: F401 (fixture)
    _user_and_workspace,
    isolated_storage,
)
from app.modules.workspaces.tests.test_workspace_api import _create_workspace, _register_and_login
from tests.db import run_db_test, run_http_test
from tests.fake_llm import FakeLLM


def _hit(page: int, content: str = "text"):
    chunk = SimpleNamespace(id=uuid.uuid4(), page_start=page, page_end=page, content=content)
    doc = SimpleNamespace(id=uuid.uuid4(), title="handbook.pdf")
    return chunk, doc


def test_context_numbers_each_source() -> None:
    context = build_context([_hit(1, "intro"), _hit(3, "revenue")])
    assert context == "[1] handbook.pdf, page 1\nintro\n\n[2] handbook.pdf, page 3\nrevenue"


def test_citations_keep_only_sources_the_answer_cites() -> None:
    hits = [_hit(1), _hit(2), _hit(3), _hit(4)]
    citations = build_citations(hits, "The target is $2M [3]. It launches in August [1, 3].")
    assert [(c["number"], c["page_start"]) for c in citations] == [(1, 1), (3, 3)]


def test_answer_without_markers_cites_nothing() -> None:
    assert build_citations([_hit(1)], "I don't have that information in your documents.") == []


def test_markers_beyond_the_sources_are_ignored() -> None:
    assert [c["number"] for c in build_citations([_hit(1)], "Yes [1] [7].")] == [1]


async def _stream(session, ws, user, question, **kwargs) -> list[dict]:
    prepared = await service.prepare_question(
        session, workspace_id=ws, user_id=user.id, question=question, **kwargs
    )
    return [
        event
        async for event in service.stream_answer(
            session, prepared, workspace_id=ws, user_id=user.id, question=question
        )
    ]


async def _conversation_count(session: AsyncSession, user) -> int:
    return await session.scalar(
        select(func.count()).select_from(Conversation).where(Conversation.user_id == user.id)
    )


def test_stream_sends_tokens_then_saves_and_finishes(fake_llm: FakeLLM) -> None:
    fake_llm.cite = [2]

    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        await _upload_text(session, user, ws, "The launch is in August.", "launch.txt")
        await _upload_text(session, user, ws, "The cafeteria serves soup.", "food.txt")

        events = await _stream(session, ws, user, "When is the launch?")

        tokens = [e["text"] for e in events if e["event"] == "token"]
        done = events[-1]
        assert len(tokens) > 1
        assert done["event"] == "done"
        assert "".join(tokens) == done["message"] == "fake answer to: When is the launch? [2]"
        assert [c["number"] for c in done["citations"]] == [2]

        conversation = await session.get(Conversation, uuid.UUID(done["conversation_id"]))
        messages = (
            await session.execute(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == conversation.id)
                .order_by(ConversationMessage.id)
            )
        ).scalars().all()
        assert [m.content for m in messages] == ["When is the launch?", done["message"]]
        assert messages[1].citations == done["citations"]

    run_db_test(body)


def test_stream_continues_a_conversation(fake_llm: FakeLLM) -> None:
    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        await _upload_text(session, user, ws, "The launch is in August.")
        first = (await _stream(session, ws, user, "When is the launch?"))[-1]
        conversation_id = uuid.UUID(first["conversation_id"])

        second = (await _stream(session, ws, user, "And where?", conversation_id=conversation_id))[-1]

        assert second["conversation_id"] == first["conversation_id"]
        assert fake_llm.answer_calls[-1]["history"][0] == ("user", "When is the launch?")
        assert await _conversation_count(session, user) == 1

    run_db_test(body)


def test_stream_failure_before_text_sends_error_and_saves_nothing(fake_llm: FakeLLM) -> None:
    fake_llm.answers_fail = True

    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        await _upload_text(session, user, ws, "The launch is in August.")

        events = await _stream(session, ws, user, "When is the launch?")

        assert [e["event"] for e in events] == ["error"]
        assert events[0]["code"] == "llm_unavailable"
        assert await _conversation_count(session, user) == 0

    run_db_test(body)


def test_stream_failure_mid_answer_sends_error_and_saves_nothing(fake_llm: FakeLLM) -> None:
    fake_llm.stream_breaks = True

    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        await _upload_text(session, user, ws, "The launch is in August.")

        events = await _stream(session, ws, user, "When is the launch?")

        assert [e["event"] for e in events] == ["token", "error"]
        assert await _conversation_count(session, user) == 0

    run_db_test(body)


def test_stream_without_documents_answers_and_saves(fake_llm: FakeLLM) -> None:
    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)

        events = await _stream(session, ws, user, "Anything?")

        assert events[0] == {"event": "token", "text": NO_DOCUMENTS_ANSWER}
        assert events[-1]["citations"] == []
        assert fake_llm.answer_calls == []
        assert await _conversation_count(session, user) == 1

    run_db_test(body)


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_stream_endpoint_speaks_server_sent_events(fake_llm: FakeLLM) -> None:
    def body(client) -> None:
        cookies = _register_and_login(client)
        ws = _create_workspace(client, cookies)["id"]

        response = client.post(f"/api/v1/chat/{ws}/ask/stream", json={"message": "Anything?"})

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(response.text)
        assert events[0] == ("token", {"text": NO_DOCUMENTS_ANSWER})
        name, done = events[-1]
        assert name == "done" and done["message"] == NO_DOCUMENTS_ANSWER

        saved = client.get(f"/api/v1/chat/{ws}/conversations/{done['conversation_id']}")
        assert saved.status_code == 200
        assert [m["content"] for m in saved.json()["data"]["messages"]] == ["Anything?", NO_DOCUMENTS_ANSWER]

    run_http_test(body)


def test_stream_endpoint_rejects_unknown_conversation_before_streaming(fake_llm: FakeLLM) -> None:
    def body(client) -> None:
        cookies = _register_and_login(client)
        ws = _create_workspace(client, cookies)["id"]

        response = client.post(
            f"/api/v1/chat/{ws}/ask/stream",
            json={"message": "Hi", "conversation_id": str(uuid.uuid4())},
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "conversation_not_found"

    run_http_test(body)
