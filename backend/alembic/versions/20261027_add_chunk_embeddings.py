"""Add pgvector embeddings to chunks.

Replaces the never-populated `embedding_json` column with a real
`vector(768)` column and an HNSW index for cosine-distance search.

The `vector` extension must be installable by the migrating role. It is not a
"trusted" extension, so a superuser has to create it once per database:

    CREATE EXTENSION IF NOT EXISTS vector;

Revision ID: 20261027_chunk_embeddings
Revises: 20261002_add_chunks_pgvector
"""

from alembic import op

revision = "20261027_chunk_embeddings"
down_revision = "20261002_add_chunks_pgvector"
branch_labels = None
depends_on = None

# Must match app.modules.documents.chunks.EMBEDDING_DIMENSIONS.
EMBEDDING_DIMENSIONS = 768


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS embedding_json")
    op.execute(f"ALTER TABLE chunks ADD COLUMN embedding vector({EMBEDDING_DIMENSIONS})")
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE chunks ADD COLUMN embedding_json JSONB")
