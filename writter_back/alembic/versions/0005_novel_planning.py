"""Add versioned novel plans and chapter plan executions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_novel_planning"
down_revision = "0004_unlimited_generation_quota"
branch_labels = None
depends_on = None


def _tenant_novel_foreign_key(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", "novel_id"],
        ["novels.tenant_id", "novels.id"],
        name=name,
        ondelete="CASCADE",
    )


def _create_plan_versions() -> None:
    op.create_table(
        "novel_plan_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("trigger_chapter", sa.Integer(), nullable=True),
        sa.Column("change_summary", sa.Text(), server_default="", nullable=False),
        sa.Column("plan", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        _tenant_novel_foreign_key("fk_plan_versions_tenant_novel"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "novel_id", "version", name="uq_plan_versions_version"
        ),
        sa.CheckConstraint("version >= 1", name="ck_plan_versions_positive_version"),
        sa.CheckConstraint("source <> ''", name="ck_plan_versions_source"),
        sa.CheckConstraint(
            "trigger_chapter IS NULL OR trigger_chapter >= 1",
            name="ck_plan_versions_trigger_chapter",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(plan) = 'object'", name="ck_plan_versions_plan_object"
        ),
    )
    op.create_index(
        "ix_plan_versions_tenant_novel",
        "novel_plan_versions",
        ["tenant_id", "novel_id", "version"],
    )


def _create_plan_executions() -> None:
    op.create_table(
        "novel_plan_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chapter_number", sa.Integer(), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("actual_words", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fulfillment", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column(
            "drift_severity", sa.String(length=10), server_default="none", nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        _tenant_novel_foreign_key("fk_plan_executions_tenant_novel"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "novel_id", "plan_version"],
            [
                "novel_plan_versions.tenant_id",
                "novel_plan_versions.novel_id",
                "novel_plan_versions.version",
            ],
            name="fk_plan_executions_plan_version",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "novel_id",
            "chapter_number",
            name="uq_plan_executions_chapter",
        ),
        sa.CheckConstraint("chapter_number >= 1", name="ck_plan_execution_chapter"),
        sa.CheckConstraint("plan_version >= 1", name="ck_plan_execution_version"),
        sa.CheckConstraint("actual_words >= 0", name="ck_plan_execution_words"),
        sa.CheckConstraint("status <> ''", name="ck_plan_execution_status"),
        sa.CheckConstraint(
            "drift_severity IN ('none', 'minor', 'major')",
            name="ck_plan_execution_drift",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(fulfillment) = 'object'",
            name="ck_plan_execution_fulfillment_object",
        ),
    )
    op.create_index(
        "ix_plan_executions_tenant_novel",
        "novel_plan_executions",
        ["tenant_id", "novel_id", "chapter_number"],
    )


def upgrade() -> None:
    _create_plan_versions()
    _create_plan_executions()


def downgrade() -> None:
    op.drop_index(
        "ix_plan_executions_tenant_novel", table_name="novel_plan_executions"
    )
    op.drop_table("novel_plan_executions")
    op.drop_index("ix_plan_versions_tenant_novel", table_name="novel_plan_versions")
    op.drop_table("novel_plan_versions")
