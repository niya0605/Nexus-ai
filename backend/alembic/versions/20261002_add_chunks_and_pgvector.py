"""Add chunks table for document embeddings (pgvector deferred for managed DB).

For local development without pgvector, embeddings are stored as JSON arrays.
When deployed to a managed PostgreSQL with pgvector, a future migration will
add vector(1536) type and HNSW indexing.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20261002_add_chunks_pgvector'
down_revision = '3d7a92f1c8e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create chunks table (embeddings as JSON for local dev)
    op.execute("""
    CREATE TABLE chunks (
        id UUID PRIMARY KEY,
        document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        page_start INTEGER NOT NULL,
        page_end INTEGER NOT NULL,
        content TEXT NOT NULL,
        tsv TSVECTOR,
        embedding_json JSONB,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
    )
    """)

    # Create indexes
    op.execute('CREATE INDEX ix_chunks_document_id ON chunks (document_id)')
    op.execute('CREATE INDEX ix_chunks_document_pages ON chunks (document_id, page_start, page_end)')
    # Full-text search on content
    op.execute('CREATE INDEX ix_chunks_tsv ON chunks USING gin (tsv)')

    # Create a trigger to auto-generate tsvector from content
    op.execute("""
    CREATE TRIGGER tsvector_update BEFORE INSERT OR UPDATE ON chunks
    FOR EACH ROW EXECUTE FUNCTION
    tsvector_update_trigger(tsv, 'pg_catalog.english', content)
    """)


def downgrade() -> None:
    # Drop trigger
    op.execute('DROP TRIGGER IF EXISTS tsvector_update ON chunks')

    # Drop table
    op.execute('DROP TABLE IF EXISTS chunks')

