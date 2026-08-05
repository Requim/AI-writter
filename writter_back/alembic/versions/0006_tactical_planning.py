"""Add tenant-gated rolling tactical plan versions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_tactical_planning"
down_revision = "0005_novel_planning"
branch_labels = None
depends_on = None


def _tactical_columns() -> list[sa.Column]:
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("novel_plan_version", sa.Integer(), nullable=False),
        sa.Column("story_state_revision", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.Integer(), nullable=False),
        sa.Column("window_end", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "window", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    ]


def _tactical_foreign_keys() -> list[sa.ForeignKeyConstraint]:
    return [
        sa.ForeignKeyConstraint(
            ["tenant_id", "novel_id"], ["novels.tenant_id", "novels.id"],
            name="fk_tactical_versions_tenant_novel", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "novel_id", "novel_plan_version"],
            ["novel_plan_versions.tenant_id", "novel_plan_versions.novel_id",
             "novel_plan_versions.version"],
            name="fk_tactical_versions_plan_version", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
    ]


def _tactical_uniques() -> list[sa.UniqueConstraint]:
    return [
        sa.UniqueConstraint(
            "tenant_id", "novel_id", "version",
            name="uq_tactical_versions_version",
        ),
        sa.UniqueConstraint(
            "tenant_id", "novel_id", "idempotency_key",
            name="uq_tactical_versions_idempotency",
        ),
    ]


def _tactical_checks() -> list[sa.CheckConstraint]:
    return [
        sa.CheckConstraint("version >= 1", name="ck_tactical_versions_version"),
        sa.CheckConstraint(
            "novel_plan_version >= 1", name="ck_tactical_versions_plan_version"
        ),
        sa.CheckConstraint(
            "story_state_revision >= 0", name="ck_tactical_versions_story_revision"
        ),
        sa.CheckConstraint(
            "window_start >= 1 AND window_end >= window_start "
            "AND window_end - window_start <= 6",
            name="ck_tactical_versions_window",
        ),
        sa.CheckConstraint("source <> ''", name="ck_tactical_versions_source"),
        sa.CheckConstraint(
            "idempotency_key <> ''",
            name="ck_tactical_versions_idempotency_key",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(window) = 'object'",
            name="ck_tactical_versions_window_object",
        ),
    ]


def _create_tactical_versions() -> None:
    op.create_table(
        "novel_tactical_plan_versions",
        *_tactical_columns(),
        *_tactical_foreign_keys(),
        *_tactical_uniques(),
        *_tactical_checks(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tactical_versions_tenant_novel",
        "novel_tactical_plan_versions",
        ["tenant_id", "novel_id", "version"],
    )


def _add_execution_tactical_version() -> None:
    op.add_column(
        "novel_plan_executions",
        sa.Column("tactical_version", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_plan_execution_tactical_version", "novel_plan_executions",
        "tactical_version IS NULL OR tactical_version >= 1",
    )
    op.create_foreign_key(
        "fk_plan_executions_tactical_version",
        "novel_plan_executions", "novel_tactical_plan_versions",
        ["tenant_id", "novel_id", "tactical_version"],
        ["tenant_id", "novel_id", "version"], ondelete="CASCADE",
    )


def _add_plan_idempotency() -> None:
    op.add_column(
        "novel_plan_versions",
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
    )
    op.create_unique_constraint(
        "uq_plan_versions_idempotency",
        "novel_plan_versions",
        ["tenant_id", "novel_id", "idempotency_key"],
    )
    op.create_check_constraint(
        "ck_plan_versions_idempotency_key",
        "novel_plan_versions",
        "idempotency_key IS NULL OR idempotency_key <> ''",
    )


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "novel_planning_v1_enabled", sa.Boolean(),
            server_default=sa.false(), nullable=False,
        ),
    )
    _add_plan_idempotency()
    _create_tactical_versions()
    _add_execution_tactical_version()


def downgrade() -> None:
    op.drop_constraint(
        "fk_plan_executions_tactical_version",
        "novel_plan_executions", type_="foreignkey",
    )
    op.drop_constraint(
        "ck_plan_execution_tactical_version",
        "novel_plan_executions", type_="check",
    )
    op.drop_column("novel_plan_executions", "tactical_version")
    op.drop_index(
        "ix_tactical_versions_tenant_novel",
        table_name="novel_tactical_plan_versions",
    )
    op.drop_table("novel_tactical_plan_versions")
    op.drop_constraint(
        "ck_plan_versions_idempotency_key",
        "novel_plan_versions", type_="check",
    )
    op.drop_constraint(
        "uq_plan_versions_idempotency",
        "novel_plan_versions", type_="unique",
    )
    op.drop_column("novel_plan_versions", "idempotency_key")
    op.drop_column("tenants", "novel_planning_v1_enabled")
