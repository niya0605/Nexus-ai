"""Document service - upload, parsing, chunking."""

import asyncio
import hashlib
import logging
import uuid
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import AsyncSessionFactory
from app.modules.documents.chunking import split_pages_into_chunks
from app.modules.documents.models import Document, DocumentStatus, DocumentVersion
from app.modules.documents.chunks import Chunk
from app.modules.documents.parsers import pages_to_display_text, parse_document_pages
from app.core.exceptions import AppException
from app.core.llm import LLMError, get_llm

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
        pages = await asyncio.to_thread(parse_document_pages, str(path), document.file_type)
        return pages_to_display_text(pages)

    chunks = (
        await db.execute(
            # uuid7 ids preserve insertion order; created_at is per-transaction
            select(Chunk.content).where(Chunk.document_id == document.id).order_by(Chunk.id)
        )
    ).scalars().all()
    return "\n\n".join(chunks)


async def _store_chunks(
    db: AsyncSession, document_id: uuid.UUID, path: Path, file_type: str
) -> int:
    pages = await asyncio.to_thread(parse_document_pages, str(path), file_type)
    chunks = [
        Chunk(
            document_id=document_id,
            page_start=spec.page_start,
            page_end=spec.page_end,
            content=spec.content,
        )
        for spec in split_pages_into_chunks(pages)
    ]
    db.add_all(chunks)
    await _embed_chunks(chunks)
    await db.flush()
    return len(chunks)


async def _embed_chunks(chunks: list[Chunk], *, wait_on_rate_limit: bool = False) -> bool:
    """Best effort: on failure the chunks stay searchable by keyword and are
    embedded later (background catch-up or scripts/backfill_embeddings.py)."""
    if not chunks:
        return True
    try:
        vectors = await get_llm().embed_documents(
            [c.content for c in chunks], wait_on_rate_limit=wait_on_rate_limit
        )
    except LLMError as exc:
        logger.warning("Embedding skipped for %d chunks: %s", len(chunks), exc)
        return False
    for chunk, vector in zip(chunks, vectors, strict=True):
        chunk.embedding = vector
    return True


async def embed_missing_chunks(
    db: AsyncSession,
    *,
    document_id: uuid.UUID | None = None,
    batch_size: int = 100,
    wait_on_rate_limit: bool = False,
) -> int:
    """Embed up to `batch_size` chunks that have no embedding yet; commits.
    Returns how many were embedded (0 when none are left or the API failed)."""
    stmt = select(Chunk).where(Chunk.embedding.is_(None)).order_by(Chunk.id).limit(batch_size)
    if document_id is not None:
        stmt = stmt.where(Chunk.document_id == document_id)
    chunks = list((await db.execute(stmt)).scalars().all())
    if not await _embed_chunks(chunks, wait_on_rate_limit=wait_on_rate_limit):
        return 0
    await db.commit()
    return len(chunks)


async def has_unembedded_chunks(db: AsyncSession, document_id: uuid.UUID) -> bool:
    return bool(
        await db.scalar(
            select(Chunk.id)
            .where(Chunk.document_id == document_id, Chunk.embedding.is_(None))
            .limit(1)
        )
    )


async def reprocess_document(db: AsyncSession, document: Document) -> int:
    """Rebuild a document's chunks (and embeddings) from its stored original,
    e.g. after the chunking logic changes. Returns the new chunk count; commits."""
    path = stored_file_path(document)
    if not path.exists():
        raise FileNotFoundError(f"No stored original for document {document.id}")

    await db.execute(delete(Chunk).where(Chunk.document_id == document.id))
    try:
        chunk_count = await _store_chunks(db, document.id, path, document.file_type)
        document.status = DocumentStatus.READY if chunk_count else DocumentStatus.FAILED
    except Exception:
        logger.exception("Document %s failed to parse", document.id)
        chunk_count = 0
        document.status = DocumentStatus.FAILED
    await db.commit()
    return chunk_count


async def embed_document_in_background(document_id: uuid.UUID) -> None:
    """Runs after the upload response: finishes embedding a document whose
    inline embedding hit the free-tier quota, waiting out rate limits."""
    try:
        async with AsyncSessionFactory() as db:
            while await embed_missing_chunks(db, document_id=document_id, wait_on_rate_limit=True):
                pass
    except Exception:
        logger.exception("Background embedding failed for document %s", document_id)


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

