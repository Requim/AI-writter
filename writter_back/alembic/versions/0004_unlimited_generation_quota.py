"""Add explicit unlimited monthly generation quota policy."""

from alembic import op
import sqlalchemy as sa

revision = "0004_unlimited_generation_quota"
down_revision = "0003_chapter_consistency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "monthly_generation_unlimited",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE tenants
        SET monthly_generation_unlimited = TRUE
        WHERE monthly_generation_limit >= 2000000000
        """
    )


def downgrade() -> None:
    op.drop_column("tenants", "monthly_generation_unlimited")
