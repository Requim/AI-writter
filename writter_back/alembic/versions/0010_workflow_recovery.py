"""Persist bounded automatic execution intent for process restart."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010_workflow_recovery"
down_revision = "0009_autonomous_author"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("workflow_runs", sa.Column("recovery_payload", JSONB(), nullable=True))


def downgrade():
    op.drop_column("workflow_runs", "recovery_payload")
