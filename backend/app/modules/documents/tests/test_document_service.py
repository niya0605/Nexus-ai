"""Upload → parse → chunk → search, against real Postgres + Redis.

The Gemini call is not exercised here (it needs network access and quota);
these tests stop at the retrieval results and citation data it is given.
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import hash_password
from app.db.redis import redis_client
from app.modules.auth.models import User, UserStatus
from app.modules.chat.retrieval import search_chunks
from app.modules.documents.chunks import Chunk
from app.modules.documents.models import DocumentStatus
from app.modules.documents.service import (
    create_document,
    get_document_text,
    reprocess_document,
    stored_file_path,
)
from app.modules.documents.tests.test_parsing_chunking import make_pdf
from app.modules.workspaces import service as workspace_service
from app.modules.workspaces.schemas import CreateWorkspaceRequest
from tests.db import run_db_test


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "DOCUMENT_STORAGE_DIR", str(tmp_path / "storage"))
    return tmp_path


async def _user_and_workspace(session: AsyncSession) -> tuple[User, uuid.UUID]:
    user = User(
        email=f"doc-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("a-strong-password"),
        display_name="Doc Tester",
        status=UserStatus.ACTIVE,
        email_verified_at=datetime.now(UTC),
    )
    session.add(user)
    await session.flush()
    workspace, _ = await workspace_service.create_workspace(
        session, redis_client, user.id, CreateWorkspaceRequest(name=f"Docs {uuid.uuid4().hex[:8]}")
    )
    return user, workspace.id


async def _upload_pdf(session, user, workspace_id, tmp_path: Path, pages: list[str], name="plan.pdf"):
    pdf = make_pdf(tmp_path / name, pages)
    return await create_document(
        db=session,
        workspace_id=workspace_id,
        user_id=user.id,
        title=name,
        original_filename=name,
        file_type="pdf",
        file_content=pdf.read_bytes(),
    )


def test_upload_stores_original_and_page_aware_chunks(isolated_storage: Path) -> None:
    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        doc = await _upload_pdf(
            session, user, ws, isolated_storage,
            ["Revenue target is 2.4 million.", "", "Onboarding is owned by Priya."],
        )

        assert doc.status == DocumentStatus.READY
        assert stored_file_path(doc).exists()
        chunks = (await session.execute(select(Chunk).where(Chunk.document_id == doc.id))).scalars().all()
        assert sorted((c.page_start, c.page_end) for c in chunks) == [(1, 1), (3, 3)]

        text = await get_document_text(session, doc)
        assert "--- Page 1 ---" in text and "--- Page 3 ---" in text and "--- Page 2 ---" not in text

    run_db_test(body)


def test_pdf_without_text_is_marked_failed(isolated_storage: Path) -> None:
    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        doc = await _upload_pdf(session, user, ws, isolated_storage, ["", ""], name="scan.pdf")
        assert doc.status == DocumentStatus.FAILED

    run_db_test(body)


def test_reprocess_rebuilds_chunks(isolated_storage: Path) -> None:
    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        doc = await _upload_pdf(session, user, ws, isolated_storage, ["alpha", "beta"])
        session.add(Chunk(document_id=doc.id, page_start=0, page_end=0, content="stale chunk"))
        await session.flush()

        assert await reprocess_document(session, doc) == 2
        contents = (
            await session.execute(select(Chunk.content).where(Chunk.document_id == doc.id))
        ).scalars().all()
        assert "stale chunk" not in contents

    run_db_test(body)


def test_search_returns_page_numbers_and_respects_scope(isolated_storage: Path) -> None:
    async def body(session: AsyncSession) -> None:
        user, ws = await _user_and_workspace(session)
        long_page = "filler words " * 400
        target = await _upload_pdf(
            session, user, ws, isolated_storage,
            [long_page, long_page, "The quarterly revenue target is 2.4 million dollars."],
        )
        other = await _upload_pdf(
            session, user, ws, isolated_storage, ["Revenue appears here too."], name="other.pdf"
        )
        _, other_ws = await _user_and_workspace(session)
        await _upload_pdf(session, user, other_ws, isolated_storage, ["revenue revenue revenue"], name="x.pdf")

        hits = await search_chunks(session, ws, "what is the revenue target?")
        assert hits, "expected matching chunks"
        assert {doc.workspace_id for _, doc in hits} == {ws}
        best_chunk, best_doc = hits[0]
        assert best_doc.id == target.id
        assert best_chunk.page_end == 3

        scoped = await search_chunks(session, ws, "revenue", document_id=other.id)
        assert {doc.id for _, doc in scoped} == {other.id}

    run_db_test(body)
