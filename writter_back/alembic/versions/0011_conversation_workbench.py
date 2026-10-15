"""Add scoped conversations, assets and rebuildable textual retrieval indexes."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0011_conversation_workbench"
down_revision = "0010_workflow_recovery"
branch_labels = None
depends_on = None

TABLES = (
    "workbench_conversations", "workbench_messages", "workbench_jobs",
    "workbench_assets", "workbench_asset_versions", "workbench_source_chunks",
)


def scoped_columns():
    return [sa.Column("tenant_id", UUID(), nullable=False), sa.Column("novel_id", UUID(), nullable=False)]


def novel_scope():
    return sa.ForeignKeyConstraint(["tenant_id", "novel_id"], ["novels.tenant_id", "novels.id"], ondelete="CASCADE")


def timestamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False)]


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        TABLES[0], sa.Column("id", UUID(), primary_key=True), *scoped_columns(),
        sa.Column("title", sa.String(240), nullable=False), *timestamps(), novel_scope(),
        sa.UniqueConstraint("tenant_id", "novel_id", "id"), if_not_exists=True,
    )
    op.create_table(
        TABLES[1], sa.Column("id", UUID(), primary_key=True), *scoped_columns(),
        sa.Column("conversation_id", UUID(), nullable=False), sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("intent", sa.String(24), nullable=False), sa.Column("sources", JSONB(), nullable=False),
        sa.Column("job_id", UUID()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "novel_id", "conversation_id"],
                                [f"{TABLES[0]}.tenant_id", f"{TABLES[0]}.novel_id", f"{TABLES[0]}.id"], ondelete="CASCADE"),
        if_not_exists=True,
    )
    op.create_index("ix_workbench_messages_conversation", TABLES[1], ["conversation_id", "created_at"], if_not_exists=True)
    op.create_table(
        TABLES[2], sa.Column("id", UUID(), primary_key=True), *scoped_columns(),
        sa.Column("conversation_id", UUID(), nullable=False), sa.Column("message_id", UUID(), nullable=False),
        sa.Column("command_key", sa.String(128), nullable=False), sa.Column("command_digest", sa.String(64), nullable=False),
        sa.Column("request", JSONB(), nullable=False), sa.Column("snapshot", JSONB(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("content", sa.Text(), nullable=False),
        sa.Column("error", sa.Text()), sa.Column("sources", JSONB(), nullable=False),
        sa.Column("intent", sa.String(24), nullable=False), sa.Column("chapter_index", sa.Integer()),
        sa.Column("target_chapter_id", UUID()), *timestamps(), novel_scope(),
        sa.UniqueConstraint("tenant_id", "novel_id", "command_key"), if_not_exists=True,
    )
    op.create_index("ix_workbench_jobs_status", TABLES[2], ["status"], if_not_exists=True)
    op.create_table(
        TABLES[3], sa.Column("id", UUID(), primary_key=True), *scoped_columns(),
        sa.Column("title", sa.String(240), nullable=False), sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("content", sa.Text(), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_message_id", UUID()), sa.Column("provenance", JSONB(), nullable=False),
        sa.Column("review", JSONB()), sa.Column("adopted_chapter_id", UUID()), *timestamps(), novel_scope(),
        sa.UniqueConstraint("tenant_id", "novel_id", "id"), if_not_exists=True,
    )
    op.create_table(
        TABLES[4], sa.Column("asset_id", UUID(), primary_key=True), sa.Column("version", sa.Integer(), primary_key=True),
        *scoped_columns(), sa.Column("title", sa.String(240), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False), sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "novel_id", "asset_id"],
                                [f"{TABLES[3]}.tenant_id", f"{TABLES[3]}.novel_id", f"{TABLES[3]}.id"], ondelete="CASCADE"),
        if_not_exists=True,
    )
    op.create_table(
        TABLES[5], sa.Column("id", UUID(), primary_key=True), *scoped_columns(),
        sa.Column("source_type", sa.String(16), nullable=False), sa.Column("source_id", UUID(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False), sa.Column("chapter_index", sa.Integer()),
        sa.Column("start", sa.Integer(), nullable=False), sa.Column("end", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False), novel_scope(),
        sa.UniqueConstraint("tenant_id", "novel_id", "source_type", "source_id", "start"), if_not_exists=True,
    )
    op.create_index("ix_workbench_source_scope", TABLES[5], ["tenant_id", "novel_id", "source_type"], if_not_exists=True)
    op.create_index("ix_workbench_source_trgm", TABLES[5], ["text"], postgresql_using="gin",
                    postgresql_ops={"text": "gin_trgm_ops"}, if_not_exists=True)


def downgrade():
    for name in reversed(TABLES):
        op.drop_table(name)
