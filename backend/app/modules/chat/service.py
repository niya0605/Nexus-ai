"""Chat service — Q&A over workspace documents with Gemini, saved as conversations."""

import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import NamedTuple

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppException
from app.core.llm import LLMError, get_llm
from app.modules.chat.models import Conversation, ConversationMessage, MessageRole
from app.modules.chat.retrieval import Hit, search_chunks
from app.modules.documents.service import get_document

# Earlier messages sent with a follow-up question (3 question/answer pairs).
HISTORY_MESSAGES = 6
TITLE_CHARS = 80
NO_DOCUMENTS_ANSWER = "No processed documents found yet. Upload a document first, then ask again."


class LLMUnavailableError(AppException):
    status_code = 502
    error_code = "llm_unavailable"


class ConversationNotFoundError(AppException):
    status_code = 404
    error_code = "conversation_not_found"

    def __init__(self) -> None:
        super().__init__("Conversation not found.")


class PreparedQuestion(NamedTuple):
    conversation: Conversation | None
    document_id: uuid.UUID | None
    history: list[tuple[str, str]]
    hits: list[Hit]


def _page_label(page_start: int, page_end: int) -> str:
    if page_start <= 0:
        return ""
    return f", page {page_start}" if page_start == page_end else f", pages {page_start}-{page_end}"


def build_context(hits: list[Hit]) -> str:
    """Number each source ([1], [2], …) so the model can cite the ones it uses."""
    return "\n\n".join(
        f"[{number}] {doc.title}{_page_label(chunk.page_start, chunk.page_end)}\n{chunk.content}"
        for number, (chunk, doc) in enumerate(hits, start=1)
    )


# Citation markers in an answer: "[2]" or "[1, 3]".
_CITATION_MARKER = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def cited_numbers(answer: str) -> set[int]:
    return {
        int(n) for group in _CITATION_MARKER.findall(answer) for n in group.split(",")
    }


def build_citations(hits: list[Hit], answer: str) -> list[dict]:
    """The sources the answer actually cites, keeping their [n] numbers so the
    markers in the text match. Retrieved-but-unused passages are left out."""
    used = cited_numbers(answer)
    return [
        {
            "number": number,
            "chunk_id": str(chunk.id),
            "document_id": str(doc.id),
            "document_title": doc.title,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "excerpt": chunk.content[:300],
        }
        for number, (chunk, doc) in enumerate(hits, start=1)
        if number in used
    ]


def make_title(question: str) -> str:
    title = " ".join(question.split())
    return title if len(title) <= TITLE_CHARS else title[: TITLE_CHARS - 1].rstrip() + "…"


def _owned_by(workspace_id: uuid.UUID, user_id: uuid.UUID, conversation_id: uuid.UUID):
    return (
        Conversation.id == conversation_id,
        Conversation.workspace_id == workspace_id,
        Conversation.user_id == user_id,
    )


async def prepare_question(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    question: str,
    document_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
) -> PreparedQuestion:
    """Resolve the conversation (a continued one keeps its own document scope),
    load recent history and retrieve context for the question."""
    conversation = None
    history: list[tuple[str, str]] = []
    if conversation_id is not None:
        conversation = await db.scalar(
            select(Conversation).where(*_owned_by(workspace_id, user_id, conversation_id))
        )
        if conversation is None:
            raise ConversationNotFoundError()
        document_id = conversation.document_id
        recent = (
            await db.execute(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == conversation.id)
                .order_by(ConversationMessage.id.desc())
                .limit(HISTORY_MESSAGES)
            )
        ).scalars().all()
        history = [(m.role.value, m.content) for m in reversed(recent)]
    elif document_id is not None:
        await get_document(db, document_id, workspace_id)

    # A follow-up like "what about Q4?" retrieves poorly on its own; the
    # previous question supplies the topic.
    previous_questions = [text for role, text in history if role == MessageRole.USER.value]
    search_query = f"{previous_questions[-1]} {question}" if previous_questions else question
    hits = await search_chunks(db, workspace_id, search_query, document_id=document_id)
    return PreparedQuestion(conversation, document_id, history, hits)


async def save_exchange(
    db: AsyncSession,
    prepared: PreparedQuestion,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    question: str,
    answer: str,
    citations: list[dict],
) -> Conversation:
    """Persist one question/answer pair (creating the conversation on its first
    question) in a single commit — nothing is saved if answering failed.

    `db` may be a different session from the one that prepared the question
    (streaming saves after the request's session is done), so the conversation
    is looked up again by id."""
    conversation = (
        await db.get(Conversation, prepared.conversation.id) if prepared.conversation else None
    )
    if conversation is None:
        conversation = Conversation(
            workspace_id=workspace_id,
            user_id=user_id,
            document_id=prepared.document_id,
            title=make_title(question),
        )
        db.add(conversation)
        await db.flush()
    db.add_all(
        [
            ConversationMessage(
                conversation_id=conversation.id, role=MessageRole.USER, content=question
            ),
            ConversationMessage(
                conversation_id=conversation.id,
                role=MessageRole.ASSISTANT,
                content=answer,
                citations=citations,
            ),
        ]
    )
    conversation.updated_at = datetime.now(UTC)
    await db.commit()
    return conversation


async def answer_question(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    question: str,
    document_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, str, list[dict]]:
    prepared = await prepare_question(
        db,
        workspace_id=workspace_id,
        user_id=user_id,
        question=question,
        document_id=document_id,
        conversation_id=conversation_id,
    )
    if prepared.hits:
        try:
            answer = await get_llm().answer_question(
                question, build_context(prepared.hits), prepared.history
            )
        except LLMError as exc:
            raise LLMUnavailableError(str(exc)) from exc
    else:
        answer = NO_DOCUMENTS_ANSWER
    citations = build_citations(prepared.hits, answer)
    conversation = await save_exchange(
        db,
        prepared,
        workspace_id=workspace_id,
        user_id=user_id,
        question=question,
        answer=answer,
        citations=citations,
    )
    return conversation.id, answer, citations


async def stream_answer(
    db: AsyncSession,
    prepared: PreparedQuestion,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    question: str,
) -> AsyncIterator[dict]:
    """Answer a prepared question as events: {"event": "token", "text"} while the
    model writes, then {"event": "done", conversation_id, message, citations}
    once saved — or {"event": "error", code, message}, with nothing saved."""
    if prepared.hits:
        parts: list[str] = []
        try:
            async for text in get_llm().stream_answer(
                question, build_context(prepared.hits), prepared.history
            ):
                parts.append(text)
                yield {"event": "token", "text": text}
        except LLMError as exc:
            yield {"event": "error", "code": LLMUnavailableError.error_code, "message": str(exc)}
            return
        answer = "".join(parts)
    else:
        answer = NO_DOCUMENTS_ANSWER
        yield {"event": "token", "text": answer}
    citations = build_citations(prepared.hits, answer)
    conversation = await save_exchange(
        db,
        prepared,
        workspace_id=workspace_id,
        user_id=user_id,
        question=question,
        answer=answer,
        citations=citations,
    )
    yield {
        "event": "done",
        "conversation_id": str(conversation.id),
        "message": answer,
        "citations": citations,
    }


async def list_conversations(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    document_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[tuple[Conversation, int]]:
    """The caller's conversations, most recently active first, with message counts."""
    message_count = (
        select(func.count())
        .where(ConversationMessage.conversation_id == Conversation.id)
        .correlate(Conversation)
        .scalar_subquery()
    )
    stmt = (
        select(Conversation, message_count)
        .where(Conversation.workspace_id == workspace_id, Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
    )
    if document_id is not None:
        stmt = stmt.where(Conversation.document_id == document_id)
    return [(conversation, count) for conversation, count in (await db.execute(stmt)).all()]


async def get_conversation(
    db: AsyncSession, *, workspace_id: uuid.UUID, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation:
    conversation = await db.scalar(
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(*_owned_by(workspace_id, user_id, conversation_id))
    )
    if conversation is None:
        raise ConversationNotFoundError()
    return conversation


async def delete_conversation(
    db: AsyncSession, *, workspace_id: uuid.UUID, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> None:
    result = await db.execute(
        delete(Conversation).where(*_owned_by(workspace_id, user_id, conversation_id))
    )
    if result.rowcount == 0:
        raise ConversationNotFoundError()
    await db.commit()
