"""Rebuild chunks for every document that has a stored original file.

Run after changing parsing/chunking (e.g. the move to page-aware chunks):

    cd backend
    python -m scripts.reprocess_documents

Documents uploaded before originals were kept on disk are skipped and keep
their existing chunks.
"""

import asyncio

from sqlalchemy import select

import app.db.model_registry  # noqa: F401
from app.db.session import AsyncSessionFactory, engine
from app.modules.documents.models import Document
from app.modules.documents.service import reprocess_document, stored_file_path


async def main() -> None:
    processed = skipped = failed = 0
    async with AsyncSessionFactory() as db:
        documents = (await db.execute(select(Document).order_by(Document.created_at))).scalars().all()
        for document in documents:
            if not stored_file_path(document).exists():
                skipped += 1
                continue
            chunk_count = await reprocess_document(db, document)
            if chunk_count:
                processed += 1
            else:
                failed += 1
            print(f"{document.id}  {document.title[:50]:50}  {chunk_count} chunks  {document.status.value}")
    await engine.dispose()
    print(f"\nreprocessed: {processed}  failed (no text): {failed}  skipped (no original): {skipped}")


if __name__ == "__main__":
    asyncio.run(main())
