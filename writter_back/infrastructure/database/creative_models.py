"""自主创作成果与逐请求账本，所有作品数据使用复合租户外键。"""

from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from infrastructure.database.models import Base, utc_now


def _scope(name: str):
    return ForeignKeyConstraint(
        ["tenant_id", "novel_id"], ["novels.tenant_id", "novels.id"],
        ondelete="CASCADE", name=name,
    )


class CreativeSessionModel(Base):
    __tablename__ = "creative_sessions"
    __table_args__ = (
        _scope("fk_creative_session_novel"),
        UniqueConstraint("tenant_id", "novel_id", name="uq_creative_session_novel"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    novel_id = Column(UUID(as_uuid=True), nullable=False)
    schema_version = Column(Integer, nullable=False, default=1)
    version = Column(Integer, nullable=False, default=1)
    config = Column(JSONB, nullable=False)
    limits = Column(JSONB, nullable=False)
    counters = Column(JSONB, nullable=False, default=dict)
    stage = Column(String(40), nullable=False, default="research")
    status = Column(String(40), nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class CreativeRecordModel(Base):
    __tablename__ = "creative_records"
    __table_args__ = (
        _scope("fk_creative_record_novel"),
        UniqueConstraint("tenant_id", "novel_id", "kind", "key", "version", name="uq_creative_record_version"),
        UniqueConstraint("tenant_id", "novel_id", "idempotency_key", name="uq_creative_record_command"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    novel_id = Column(UUID(as_uuid=True), nullable=False)
    kind = Column(String(40), nullable=False)
    key = Column(String(120), nullable=False)
    version = Column(Integer, nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    digest = Column(String(64), nullable=False)
    payload = Column(JSONB, nullable=False)
    status = Column(String(40), nullable=False)
    source = Column(String(24), nullable=False)
    input_versions = Column(JSONB, nullable=False, default=dict)
    evidence = Column(JSONB, nullable=False, default=list)
    run_artifact_id = Column(UUID(as_uuid=True), ForeignKey("workflow_artifacts.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class CreativeRequestModel(Base):
    __tablename__ = "creative_requests"
    __table_args__ = (_scope("fk_creative_request_novel"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    novel_id = Column(UUID(as_uuid=True), nullable=False)
    session_id = Column(UUID(as_uuid=True), ForeignKey("creative_sessions.id", ondelete="CASCADE"), nullable=False)
    bucket = Column(String(40), nullable=False)
    stage = Column(String(80), nullable=False)
    status = Column(String(24), nullable=False, default="unknown")
    usage = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    finished_at = Column(DateTime(timezone=True))


class AuthorRecordModel(Base):
    __tablename__ = "author_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "kind", "key", "version", name="uq_author_record_version"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_author_record_command"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(24), nullable=False)
    key = Column(UUID(as_uuid=True), nullable=False)
    version = Column(Integer, nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    digest = Column(String(64), nullable=False)
    payload = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
