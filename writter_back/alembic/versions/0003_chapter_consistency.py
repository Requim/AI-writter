"""Add chapter optimistic locking and tenant-scoped chapter uniqueness."""

from alembic import op
import sqlalchemy as sa

revision = "0003_chapter_consistency"
down_revision = "0002_tenant_isolation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chapters",
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM chapters
                GROUP BY tenant_id, novel_id, chapter_index
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'chapters contains duplicate tenant/novel/chapter_index rows; '
                    'back up and resolve them before rerunning this migration';
            END IF;
        END $$;
        """
    )
    op.drop_index("ix_chapters_tenant_novel_index", table_name="chapters")
    op.create_unique_constraint(
        "uq_chapters_tenant_novel_index",
        "chapters",
        ["tenant_id", "novel_id", "chapter_index"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_chapters_tenant_novel_index",
        "chapters",
        type_="unique",
    )
    op.create_index(
        "ix_chapters_tenant_novel_index",
        "chapters",
        ["tenant_id", "novel_id", "chapter_index"],
    )
    op.drop_column("chapters", "version")
