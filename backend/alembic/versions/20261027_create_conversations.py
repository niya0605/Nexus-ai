"""Create conversations and conversation_messages.

A conversation belongs to one user inside one workspace (private to that
user) and can optionally be scoped to a single document. Messages store the
question/answer text and, for answers, the citations shown to the user.

Revision ID: 20261027_conversations
Revises: 20261027_chunk_embeddings
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261027_conversations"
down_revision = "20261027_chunk_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE", name="fk_conversations_workspace_id"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_conversations_user_id"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE", name="fk_conversations_document_id"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "idx_conversations_workspace_user_updated",
        "conversations",
        ["workspace_id", "user_id", sa.text("updated_at DESC")],
    )
    op.create_index("idx_conversations_document_id", "conversations", ["document_id"])

    op.create_table(
        "conversation_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "conversations.id", ondelete="CASCADE", name="fk_conversation_messages_conversation_id"
            ),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "citations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="chk_conversation_messages_role"),
    )
    op.create_index(
        "idx_conversation_messages_conversation_id", "conversation_messages", ["conversation_id"]
    )


def downgrade() -> None:
    op.drop_table("conversation_messages")
    op.drop_table("conversations")
