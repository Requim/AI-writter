"""Create the application schema without replacing existing compatible tables."""
from infrastructure.database.models import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op

    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # The baseline is intentionally non-destructive to preserve local manuscripts.
    pass
