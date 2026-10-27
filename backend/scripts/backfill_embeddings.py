"""Embed every chunk that doesn't have an embedding yet.

Run after enabling semantic search, or after uploads made while the
embedding API was unavailable:

    cd backend
    python -m scripts.backfill_embeddings

Safe to re-run: only chunks with a NULL embedding are touched.
"""

import asyncio

from sqlalchemy import func, select

import app.db.model_registry  # noqa: F401
from app.db.session import AsyncSessionFactory, engine
from app.modules.documents.chunks import Chunk
from app.modules.documents.service import embed_missing_chunks


async def main() -> None:
    total = 0
    async with AsyncSessionFactory() as db:
        while embedded := await embed_missing_chunks(db, wait_on_rate_limit=True):
            total += embedded
            print(f"embedded {total} chunks so far")
        remaining = await db.scalar(select(func.count()).where(Chunk.embedding.is_(None)))
    await engine.dispose()
    print(f"\ndone: embedded {total} chunks, {remaining} still without an embedding")
    if remaining:
        print("(the embedding API failed — check GEMINI_API_KEY / quota and run again)")


if __name__ == "__main__":
    asyncio.run(main())
