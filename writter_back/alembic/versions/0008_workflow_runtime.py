"""持久运行租约、事件及产物，显式冻结迁移结构。"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '0008_workflow_runtime'
down_revision = '0007_story_facts'
branch_labels = None
depends_on = None


def scope(primary=False):
    return [sa.Column('tenant_id', UUID(as_uuid=True), primary_key=primary, nullable=False),
        sa.Column('novel_id', UUID(as_uuid=True), primary_key=primary, nullable=False),
        sa.ForeignKeyConstraint(['tenant_id', 'novel_id'], ['novels.tenant_id', 'novels.id'], ondelete='CASCADE')]


def upgrade():
    op.create_table('workflow_leases', *scope(True), sa.Column('fence', sa.BigInteger(), nullable=False),
        sa.Column('sequence', sa.BigInteger(), nullable=False), sa.Column('run_id', UUID(as_uuid=True)),
        sa.Column('token', sa.String(64)), sa.Column('expires_at', sa.DateTime(timezone=True)))
    create_runs()
    op.create_table('workflow_events', *scope(True), sa.Column('sequence', sa.BigInteger(), primary_key=True),
        sa.Column('run_id', UUID(as_uuid=True), nullable=False), sa.Column('payload', JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_workflow_events_run_id', 'workflow_events', ['run_id'])
    op.create_table('workflow_artifacts', *scope(), sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('run_id', UUID(as_uuid=True), nullable=False), sa.Column('checkpoint_id', sa.String(128)),
        sa.Column('kind', sa.String(32), nullable=False), sa.Column('digest', sa.String(64), nullable=False),
        sa.Column('payload', JSONB(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_workflow_artifacts_run_id', 'workflow_artifacts', ['run_id'])


def create_runs():
    op.create_table('workflow_runs', *scope(), sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('command_hash', sa.String(64), nullable=False), sa.Column('attempt', sa.Integer(), nullable=False),
        sa.Column('fence', sa.BigInteger(), nullable=False), sa.Column('token', sa.String(64), nullable=False),
        sa.Column('status', sa.String(24), nullable=False), sa.Column('cancel_requested', sa.Boolean(), nullable=False),
        sa.Column('deadline', sa.DateTime(timezone=True), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('tenant_id', 'novel_id', 'command_hash', 'attempt', name='uq_workflow_command_attempt'))
    op.create_index('ix_workflow_runs_tenant_id', 'workflow_runs', ['tenant_id'])
    op.create_index('ix_workflow_runs_novel_id', 'workflow_runs', ['novel_id'])


def downgrade():
    for name in ['workflow_artifacts', 'workflow_events', 'workflow_runs', 'workflow_leases']:
        op.drop_table(name)
