"""Chat endpoints: ask questions and manage saved conversations.

Conversations are private: every route is scoped to the caller's own
conversations inside a workspace they belong to. Another user's conversation
is indistinguishable from a missing one (404).
"""

import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import SuccessEnvelope, envelope
from app.db.dependencies import get_db
from app.db.session import AsyncSessionFactory
from app.modules.auth.dependencies import get_current_user_id
from app.modules.chat import service
from app.modules.chat.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationDetail,
    ConversationSummary,
    MessagePublic,
)
from app.modules.workspaces.dependencies import require_viewer

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post(
    "/{workspace_id}/ask",
    response_model=SuccessEnvelope[ChatResponse],
    dependencies=[Depends(require_viewer)],
)
async def ask_workspace(
    workspace_id: uuid.UUID,
    req: ChatRequest,
    request: Request,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> SuccessEnvelope[ChatResponse]:
    conversation_id, answer, citations = await service.answer_question(
        db,
        workspace_id=workspace_id,
        user_id=user_id,
        question=req.message,
        document_id=req.document_id,
        conversation_id=req.conversation_id,
    )
    return envelope(
        ChatResponse(conversation_id=conversation_id, message=answer, citations=citations), request
    )


@router.post("/{workspace_id}/ask/stream", dependencies=[Depends(require_viewer)])
async def ask_workspace_stream(
    workspace_id: uuid.UUID,
    req: ChatRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Server-sent events: `token` events carry answer text as it is written,
    then one `done` (conversation_id, message, citations) or `error` event.

    Lookups that can fail (unknown conversation or document) run before the
    stream starts, so those still return a normal JSON error with its status.
    """
    prepared = await service.prepare_question(
        db,
        workspace_id=workspace_id,
        user_id=user_id,
        question=req.message,
        document_id=req.document_id,
        conversation_id=req.conversation_id,
    )

    async def events() -> AsyncIterator[str]:
        # The request's session isn't guaranteed to outlive the response, so
        # the answer is saved through a session owned by the stream itself.
        async with AsyncSessionFactory() as stream_db:
            async for event in service.stream_answer(
                stream_db,
                prepared,
                workspace_id=workspace_id,
                user_id=user_id,
                question=req.message,
            ):
                name = event.pop("event")
                yield f"event: {name}\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/{workspace_id}/conversations",
    response_model=SuccessEnvelope[list[ConversationSummary]],
    dependencies=[Depends(require_viewer)],
)
async def list_conversations(
    workspace_id: uuid.UUID,
    request: Request,
    document_id: uuid.UUID | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> SuccessEnvelope[list[ConversationSummary]]:
    rows = await service.list_conversations(
        db, workspace_id=workspace_id, user_id=user_id, document_id=document_id
    )
    return envelope(
        [
            ConversationSummary(
                id=c.id,
                title=c.title,
                document_id=c.document_id,
                message_count=count,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
            for c, count in rows
        ],
        request,
    )


@router.get(
    "/{workspace_id}/conversations/{conversation_id}",
    response_model=SuccessEnvelope[ConversationDetail],
    dependencies=[Depends(require_viewer)],
)
async def get_conversation(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    request: Request,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> SuccessEnvelope[ConversationDetail]:
    c = await service.get_conversation(
        db, workspace_id=workspace_id, user_id=user_id, conversation_id=conversation_id
    )
    return envelope(
        ConversationDetail(
            id=c.id,
            title=c.title,
            document_id=c.document_id,
            created_at=c.created_at,
            updated_at=c.updated_at,
            messages=[MessagePublic.model_validate(m) for m in c.messages],
        ),
        request,
    )


@router.delete(
    "/{workspace_id}/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_viewer)],
)
async def delete_conversation(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.delete_conversation(
        db, workspace_id=workspace_id, user_id=user_id, conversation_id=conversation_id
    )
