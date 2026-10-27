"""Document upload and management endpoints."""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import SuccessEnvelope, envelope
from app.db.dependencies import get_db
from app.modules.auth.dependencies import get_current_user_id
from app.modules.documents.schemas import DocumentPublic, DocumentText
from app.modules.documents.service import (
    create_document,
    embed_document_in_background,
    get_document,
    get_document_text,
    has_unembedded_chunks,
    list_documents,
    stored_file_path,
)
from app.modules.documents.models import DocumentStatus
from app.modules.workspaces.dependencies import require_member, require_viewer

router = APIRouter(prefix="/documents", tags=["documents"])

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "txt": "text/plain; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
SUPPORTED_TYPES = set(MEDIA_TYPES)
MAX_FILE_SIZE = 100 * 1024 * 1024


@router.post(
    "/{workspace_id}/upload",
    response_model=SuccessEnvelope[DocumentPublic],
    status_code=201,
    dependencies=[Depends(require_member)],
)
async def upload_document(
    workspace_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> SuccessEnvelope[DocumentPublic]:
    file_ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
    if file_ext not in SUPPORTED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"File type not supported. Supported: {', '.join(sorted(SUPPORTED_TYPES))}",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="File is empty")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large")

    doc = await create_document(
        db=db,
        workspace_id=workspace_id,
        user_id=user_id,
        title=file.filename or "Untitled",
        original_filename=file.filename or "file",
        file_type=file_ext,
        file_content=content,
    )
    if doc.status == DocumentStatus.READY and await has_unembedded_chunks(db, doc.id):
        background_tasks.add_task(embed_document_in_background, doc.id)
    return envelope(DocumentPublic.model_validate(doc), request)


@router.get(
    "/{workspace_id}",
    response_model=SuccessEnvelope[list[DocumentPublic]],
    dependencies=[Depends(require_viewer)],
)
async def list_workspace_documents(
    workspace_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SuccessEnvelope[list[DocumentPublic]]:
    docs = await list_documents(db, workspace_id)
    return envelope([DocumentPublic.model_validate(d) for d in docs], request)


@router.get(
    "/{workspace_id}/{document_id}",
    response_model=SuccessEnvelope[DocumentPublic],
    dependencies=[Depends(require_viewer)],
)
async def get_document_detail(
    workspace_id: uuid.UUID,
    document_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SuccessEnvelope[DocumentPublic]:
    doc = await get_document(db, document_id, workspace_id)
    return envelope(DocumentPublic.model_validate(doc), request)


@router.get(
    "/{workspace_id}/{document_id}/text",
    response_model=SuccessEnvelope[DocumentText],
    dependencies=[Depends(require_viewer)],
)
async def get_document_text_route(
    workspace_id: uuid.UUID,
    document_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SuccessEnvelope[DocumentText]:
    doc = await get_document(db, document_id, workspace_id)
    text = await get_document_text(db, doc)
    return envelope(DocumentText(text=text, has_original=stored_file_path(doc).exists()), request)


@router.get("/{workspace_id}/{document_id}/file", dependencies=[Depends(require_viewer)])
async def get_document_file(
    workspace_id: uuid.UUID,
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    doc = await get_document(db, document_id, workspace_id)
    path = stored_file_path(doc)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Original file is not stored for this document.")
    return FileResponse(
        path,
        media_type=MEDIA_TYPES.get(doc.file_type, "application/octet-stream"),
        filename=doc.original_filename,
        content_disposition_type="inline",
    )
