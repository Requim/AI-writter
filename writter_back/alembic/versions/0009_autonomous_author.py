"""自主创作会话、逐请求预算、证据化成果及作者档案。"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0009_autonomous_author"
down_revision = "0008_workflow_runtime"
branch_labels = None
depends_on = None


def scope():
    return [
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "novel_id"], ["novels.tenant_id", "novels.id"], ondelete="CASCADE"),
    ]


def identity():
    return [
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade():
    op.add_column("tenants", sa.Column("autonomous_author_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("tenants", sa.Column("autonomous_request_limit", sa.Integer(), nullable=False, server_default="10000"))
    op.create_table("creative_sessions", *identity(), *scope(),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("config", JSONB(), nullable=False),
        sa.Column("limits", JSONB(), nullable=False),
        sa.Column("counters", JSONB(), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "novel_id", name="uq_creative_session_novel"))
    create_records()
    op.create_table("creative_requests", *identity(), *scope(),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("creative_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bucket", sa.String(40), nullable=False),
        sa.Column("stage", sa.String(80), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("usage", JSONB(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)))
    op.create_table("author_records", *identity(),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("key", UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.UniqueConstraint("tenant_id", "kind", "key", "version", name="uq_author_record_version"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_author_record_command"))


def create_records():
    op.create_table("creative_records", *identity(), *scope(),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("input_versions", JSONB(), nullable=False),
        sa.Column("evidence", JSONB(), nullable=False),
        sa.Column("run_artifact_id", UUID(as_uuid=True), sa.ForeignKey("workflow_artifacts.id", ondelete="SET NULL")),
        sa.UniqueConstraint("tenant_id", "novel_id", "kind", "key", "version", name="uq_creative_record_version"),
        sa.UniqueConstraint("tenant_id", "novel_id", "idempotency_key", name="uq_creative_record_command"))


def downgrade():
    for table in ("author_records", "creative_requests", "creative_records", "creative_sessions"):
        op.drop_table(table)
    op.drop_column("tenants", "autonomous_request_limit")
    op.drop_column("tenants", "autonomous_author_enabled")
