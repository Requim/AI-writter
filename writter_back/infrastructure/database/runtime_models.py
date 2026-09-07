"""P5运行记录：所有序号与租约按租户和小说隔离。"""
from uuid import uuid4
from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from infrastructure.database.models import Base, utc_now


class WorkflowLeaseModel(Base):
    __tablename__ = 'workflow_leases'
    __table_args__ = (ForeignKeyConstraint(['tenant_id', 'novel_id'], ['novels.tenant_id', 'novels.id'], ondelete='CASCADE'),)
    tenant_id = Column(UUID(as_uuid=True), primary_key=True)
    novel_id = Column(UUID(as_uuid=True), primary_key=True)
    fence = Column(BigInteger, nullable=False, default=0)
    sequence = Column(BigInteger, nullable=False, default=0)
    run_id = Column(UUID(as_uuid=True), nullable=True)
    token = Column(String(64), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)


class WorkflowRunModel(Base):
    __tablename__ = 'workflow_runs'
    __table_args__ = (ForeignKeyConstraint(['tenant_id', 'novel_id'], ['novels.tenant_id', 'novels.id'], ondelete='CASCADE'),
        UniqueConstraint('tenant_id', 'novel_id', 'command_hash', 'attempt', name='uq_workflow_command_attempt'))
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    novel_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    command_hash = Column(String(64), nullable=False)
    attempt = Column(Integer, nullable=False)
    fence = Column(BigInteger, nullable=False)
    token = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False, default='running')
    cancel_requested = Column(Boolean, nullable=False, default=False)
    deadline = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class WorkflowEventModel(Base):
    __tablename__ = 'workflow_events'
    __table_args__ = (ForeignKeyConstraint(['tenant_id', 'novel_id'], ['novels.tenant_id', 'novels.id'], ondelete='CASCADE'),)
    tenant_id = Column(UUID(as_uuid=True), primary_key=True)
    novel_id = Column(UUID(as_uuid=True), primary_key=True)
    sequence = Column(BigInteger, primary_key=True)
    run_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    payload = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class WorkflowArtifactModel(Base):
    __tablename__ = 'workflow_artifacts'
    __table_args__ = (ForeignKeyConstraint(['tenant_id', 'novel_id'], ['novels.tenant_id', 'novels.id'], ondelete='CASCADE'),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    novel_id = Column(UUID(as_uuid=True), nullable=False)
    run_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    checkpoint_id = Column(String(128), nullable=True)
    kind = Column(String(32), nullable=False)
    digest = Column(String(64), nullable=False)
    payload = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
