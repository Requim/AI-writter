from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from infrastructure.database.models import Base, utc_now


def novel_scope():
    return ForeignKeyConstraint(["tenant_id", "novel_id"], ["novels.tenant_id", "novels.id"], ondelete="CASCADE")


class ConversationModel(Base):
    __tablename__ = "workbench_conversations"
    __table_args__ = (novel_scope(), UniqueConstraint("tenant_id", "novel_id", "id"))
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    novel_id = Column(UUID(as_uuid=True), nullable=False)
    title = Column(String(240), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class MessageModel(Base):
    __tablename__ = "workbench_messages"
    __table_args__ = (ForeignKeyConstraint(
        ["tenant_id", "novel_id", "conversation_id"],
        ["workbench_conversations.tenant_id", "workbench_conversations.novel_id", "workbench_conversations.id"],
        ondelete="CASCADE",
    ), Index("ix_workbench_messages_conversation", "conversation_id", "created_at"))
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    novel_id = Column(UUID(as_uuid=True), nullable=False)
    conversation_id = Column(UUID(as_uuid=True), nullable=False)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False, default="")
    status = Column(String(24), nullable=False, default="completed")
    intent = Column(String(24), nullable=False)
    sources = Column(JSONB, nullable=False, default=list)
    job_id = Column(UUID(as_uuid=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class JobModel(Base):
    __tablename__ = "workbench_jobs"
    __table_args__ = (
        novel_scope(), UniqueConstraint("tenant_id", "novel_id", "command_key"),
        Index("ix_workbench_jobs_status", "status"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    novel_id = Column(UUID(as_uuid=True), nullable=False)
    conversation_id = Column(UUID(as_uuid=True), nullable=False)
    message_id = Column(UUID(as_uuid=True), nullable=False)
    command_key = Column(String(128), nullable=False)
    command_digest = Column(String(64), nullable=False)
    request = Column(JSONB, nullable=False)
    snapshot = Column(JSONB, nullable=False)
    status = Column(String(24), nullable=False, default="queued")
    content = Column(Text, nullable=False, default="")
    error = Column(Text)
    sources = Column(JSONB, nullable=False, default=list)
    intent = Column(String(24), nullable=False)
    chapter_index = Column(Integer)
    target_chapter_id = Column(UUID(as_uuid=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class AssetModel(Base):
    __tablename__ = "workbench_assets"
    __table_args__ = (novel_scope(), UniqueConstraint("tenant_id", "novel_id", "id"))
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    novel_id = Column(UUID(as_uuid=True), nullable=False)
    title = Column(String(240), nullable=False)
    kind = Column(String(24), nullable=False)
    content = Column(Text, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    source_message_id = Column(UUID(as_uuid=True))
    provenance = Column(JSONB, nullable=False, default=dict)
    review = Column(JSONB)
    adopted_chapter_id = Column(UUID(as_uuid=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class AssetVersionModel(Base):
    __tablename__ = "workbench_asset_versions"
    __table_args__ = (ForeignKeyConstraint(
        ["tenant_id", "novel_id", "asset_id"],
        ["workbench_assets.tenant_id", "workbench_assets.novel_id", "workbench_assets.id"],
        ondelete="CASCADE",
    ),)
    asset_id = Column(UUID(as_uuid=True), primary_key=True)
    version = Column(Integer, primary_key=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    novel_id = Column(UUID(as_uuid=True), nullable=False)
    title = Column(String(240), nullable=False)
    kind = Column(String(24), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class SourceChunkModel(Base):
    __tablename__ = "workbench_source_chunks"
    __table_args__ = (
        novel_scope(), UniqueConstraint("tenant_id", "novel_id", "source_type", "source_id", "start"),
        Index("ix_workbench_source_scope", "tenant_id", "novel_id", "source_type"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    novel_id = Column(UUID(as_uuid=True), nullable=False)
    source_type = Column(String(16), nullable=False)
    source_id = Column(UUID(as_uuid=True), nullable=False)
    title = Column(String(255), nullable=False)
    version = Column(Integer, nullable=False)
    kind = Column(String(24), nullable=False)
    chapter_index = Column(Integer)
    start = Column(Integer, nullable=False)
    end = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
