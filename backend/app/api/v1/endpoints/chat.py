"""Chat endpoints."""

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import SuccessEnvelope, envelope
from app.db.dependencies import get_db
from app.modules.chat.schemas import ChatRequest, ChatResponse
from app.modules.chat.service import answer_question
from app.modules.documents.service import get_document
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
    db: AsyncSession = Depends(get_db),
) -> SuccessEnvelope[ChatResponse]:
    if req.document_id is not None:
        await get_document(db, req.document_id, workspace_id)
    answer, citations = await answer_question(
        db, workspace_id, req.message, document_id=req.document_id
    )
    return envelope(ChatResponse(message=answer, citations=citations), request)
