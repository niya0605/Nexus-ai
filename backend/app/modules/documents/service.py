"""Document service - upload, parsing, chunking."""

import asyncio
import hashlib
import logging
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.modules.documents.chunking import split_text_into_chunks
from app.modules.documents.models import Document, DocumentStatus, DocumentVersion
from app.modules.documents.chunks import Chunk
from app.modules.documents.parsers import parse_document
from app.core.exceptions import AppException

logger = logging.getLogger(__name__)


class DocumentNotFoundError(AppException):
    """Document not found."""
    status_code = 404
    error_code = "document_not_found"


async def create_document(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    title: str,
    original_filename: str,
    file_type: str,
    file_content: bytes,
) -> Document:
    """Store the document and synchronously parse + chunk it (no worker yet)."""
    file_size_bytes = len(file_content)
    storage_key = f"documents/{workspace_id}/{uuid.uuid4()}"

    document = Document(
        workspace_id=workspace_id,
        title=title,
        original_filename=original_filename,
        file_type=file_type,
        file_size_bytes=file_size_bytes,
        storage_key=storage_key,
        status=DocumentStatus.PROCESSING,
        uploaded_by_user_id=user_id,
    )
    db.add(document)
    await db.flush()

    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        storage_key=storage_key,
        file_size_bytes=file_size_bytes,
        checksum=hashlib.sha256(file_content).hexdigest(),
        created_by_user_id=user_id,
    )
    db.add(version)
    await db.flush()
    document.current_version_id = version.id

    path = stored_file_path(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_bytes, file_content)

    try:
        chunk_count = await _store_chunks(db, document.id, path, file_type)
        document.status = DocumentStatus.READY if chunk_count else DocumentStatus.FAILED
    except Exception:
        logger.exception("Document %s failed to parse", document.id)
        document.status = DocumentStatus.FAILED

    await db.commit()
    await db.refresh(document)
    return document


def stored_file_path(document: Document) -> Path:
    return Path(settings.DOCUMENT_STORAGE_DIR).resolve() / f"{document.storage_key}.{document.file_type}"


async def get_document_text(db: AsyncSession, document: Document) -> str:
    """Full extracted text: re-parsed from the stored original, or rebuilt
    from chunks for documents uploaded before originals were kept."""
    path = stored_file_path(document)
    if path.exists():
        return await asyncio.to_thread(parse_document, str(path), document.file_type)

    chunks = (
        await db.execute(
            select(Chunk.content).where(Chunk.document_id == document.id).order_by(Chunk.id)  # uuid7 ids preserve insertion order; created_at is per-transaction
        )
    ).scalars().all()
    return "\n\n".join(chunks)


async def _store_chunks(
    db: AsyncSession, document_id: uuid.UUID, path: Path, file_type: str
) -> int:
    text = await asyncio.to_thread(parse_document, str(path), file_type)
    chunks = split_text_into_chunks(text)
    for spec in chunks:
        db.add(
            Chunk(
                document_id=document_id,
                page_start=spec.page_start,
                page_end=spec.page_end,
                content=spec.content,
            )
        )
    await db.flush()
    return len(chunks)


async def get_document(
    db: AsyncSession,
    document_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> Document:
    """Get a document (with workspace check)."""
    stmt = select(Document).where(
        (Document.id == document_id) & (Document.workspace_id == workspace_id)
    )
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()

    if not doc:
        raise DocumentNotFoundError("Document not found")

    return doc


async def list_documents(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[Document]:
    """List documents in a workspace, newest first."""
    stmt = (
        select(Document)
        .where(Document.workspace_id == workspace_id)
        .order_by(Document.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    result = await db.execute(stmt)
    return result.scalars().all()

