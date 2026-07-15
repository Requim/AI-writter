"""Add tenant identity, membership, quota and tenant-scoped business data."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from infrastructure.database.models import Base

revision = "0002_tenant_isolation"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

LEGACY_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def _create_identity_tables() -> None:
    bind = op.get_bind()
    for name in (
        "users",
        "tenants",
        "tenant_memberships",
        "tenant_invitations",
        "refresh_sessions",
    ):
        Base.metadata.tables[name].create(bind=bind, checkfirst=True)


def upgrade() -> None:
    _create_identity_tables()
    op.execute(
        sa.text(
            "INSERT INTO tenants "
            "(id, name, slug, status, ai_enabled, monthly_generation_limit, created_at, updated_at) "
            "VALUES (:id, '默认个人租户', 'default-personal', 'active', true, 30, NOW(), NOW()) "
            "ON CONFLICT (id) DO NOTHING"
        ).bindparams(id=LEGACY_TENANT_ID)
    )

    inspector = sa.inspect(op.get_bind())
    novel_columns = {column["name"] for column in inspector.get_columns("novels")}
    if "tenant_id" not in novel_columns:
        op.add_column("novels", sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.execute(sa.text("UPDATE novels SET tenant_id = :id WHERE tenant_id IS NULL").bindparams(id=LEGACY_TENANT_ID))
        op.alter_column("novels", "tenant_id", nullable=False)
        op.create_foreign_key("fk_novels_tenant", "novels", "tenants", ["tenant_id"], ["id"])
        op.create_unique_constraint("uq_novels_tenant_id_id", "novels", ["tenant_id", "id"])
        op.create_index("ix_novels_tenant_updated", "novels", ["tenant_id", "updated_at"])

    chapter_columns = {column["name"] for column in inspector.get_columns("chapters")}
    if "tenant_id" not in chapter_columns:
        op.add_column("chapters", sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.execute(
            "UPDATE chapters SET tenant_id = novels.tenant_id "
            "FROM novels WHERE chapters.novel_id = novels.id"
        )
        op.alter_column("chapters", "tenant_id", nullable=False)
        chapter_foreign_keys = {
            item["name"] for item in inspector.get_foreign_keys("chapters")
        }
        if "chapters_novel_id_fkey" in chapter_foreign_keys:
            op.drop_constraint("chapters_novel_id_fkey", "chapters", type_="foreignkey")
        op.create_foreign_key(
            "fk_chapters_tenant_novel",
            "chapters",
            "novels",
            ["tenant_id", "novel_id"],
            ["tenant_id", "id"],
            ondelete="CASCADE",
        )
        op.create_index(
            "ix_chapters_tenant_novel_index",
            "chapters",
            ["tenant_id", "novel_id", "chapter_index"],
        )

    memory_columns = {
        column["name"] for column in inspector.get_columns("novel_memories")
    }
    if "tenant_id" not in memory_columns:
        op.add_column("novel_memories", sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.execute(
            "UPDATE novel_memories SET tenant_id = novels.tenant_id "
            "FROM novels WHERE novel_memories.novel_id = novels.id"
        )
        op.alter_column("novel_memories", "tenant_id", nullable=False)
        memory_foreign_keys = {
            item["name"] for item in inspector.get_foreign_keys("novel_memories")
        }
        if "novel_memories_novel_id_fkey" in memory_foreign_keys:
            op.drop_constraint(
                "novel_memories_novel_id_fkey",
                "novel_memories",
                type_="foreignkey",
            )
        op.create_foreign_key(
            "fk_memories_tenant_novel",
            "novel_memories",
            "novels",
            ["tenant_id", "novel_id"],
            ["tenant_id", "id"],
            ondelete="CASCADE",
        )
        op.create_index(
            "ix_memories_tenant_novel_created",
            "novel_memories",
            ["tenant_id", "novel_id", "created_at"],
        )

    bind = op.get_bind()
    for name in ("quota_ledger", "audit_events"):
        Base.metadata.tables[name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for name in ("audit_events", "quota_ledger"):
        Base.metadata.tables[name].drop(bind=bind, checkfirst=True)

    op.drop_index("ix_memories_tenant_novel_created", table_name="novel_memories")
    op.drop_constraint("fk_memories_tenant_novel", "novel_memories", type_="foreignkey")
    op.create_foreign_key(
        "novel_memories_novel_id_fkey",
        "novel_memories",
        "novels",
        ["novel_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_column("novel_memories", "tenant_id")

    op.drop_index("ix_chapters_tenant_novel_index", table_name="chapters")
    op.drop_constraint("fk_chapters_tenant_novel", "chapters", type_="foreignkey")
    op.create_foreign_key(
        "chapters_novel_id_fkey",
        "chapters",
        "novels",
        ["novel_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_column("chapters", "tenant_id")

    op.drop_index("ix_novels_tenant_updated", table_name="novels")
    op.drop_constraint("uq_novels_tenant_id_id", "novels", type_="unique")
    op.drop_constraint("fk_novels_tenant", "novels", type_="foreignkey")
    op.drop_column("novels", "tenant_id")

    for name in (
        "refresh_sessions",
        "tenant_invitations",
        "tenant_memberships",
        "tenants",
        "users",
    ):
        Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
