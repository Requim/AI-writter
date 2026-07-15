"""SQLAlchemy models for tenant-isolated novel writing data."""

from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class UserModel(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    email = Column(String(320), nullable=False, unique=True, index=True)
    password_hash = Column(Text, nullable=False)
    is_platform_admin = Column(Boolean, nullable=False, default=False)
    status = Column(String(20), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class TenantModel(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(120), nullable=False)
    slug = Column(String(120), nullable=False, unique=True, index=True)
    status = Column(String(20), nullable=False, default="active")
    ai_enabled = Column(Boolean, nullable=False, default=True)
    monthly_generation_limit = Column(Integer, nullable=False, default=30)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class TenantMembershipModel(Base):
    __tablename__ = "tenant_memberships"

    tenant_id = Column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role = Column(String(20), nullable=False, default="member")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class TenantInvitationModel(Base):
    __tablename__ = "tenant_invitations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    role = Column(String(20), nullable=False, default="member")
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    accepted_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class RefreshSessionModel(Base):
    __tablename__ = "refresh_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_used_at = Column(DateTime(timezone=True), nullable=True)


class NovelModel(Base):
    __tablename__ = "novels"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_novels_tenant_id_id"),
        Index("ix_novels_tenant_updated", "tenant_id", "updated_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    novel_type = Column(String(50), nullable=False)
    title = Column(String(255), nullable=True)
    summary = Column(Text, nullable=True)
    total_outline = Column(JSONB, nullable=True)
    progress = Column(JSONB, nullable=True)
    status = Column(String(20), default="draft")
    thread_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    chapters = relationship("ChapterModel", back_populates="novel", cascade="all, delete-orphan")
    memories = relationship("MemoryModel", back_populates="novel", cascade="all, delete-orphan")


class ChapterModel(Base):
    __tablename__ = "chapters"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "novel_id"],
            ["novels.tenant_id", "novels.id"],
            ondelete="CASCADE",
            name="fk_chapters_tenant_novel",
        ),
        Index("ix_chapters_tenant_novel_index", "tenant_id", "novel_id", "chapter_index"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    novel_id = Column(UUID(as_uuid=True), nullable=False)
    chapter_index = Column(Integer, nullable=False)
    title = Column(String(255), nullable=True)
    outline = Column(JSONB, nullable=True)
    content = Column(Text, nullable=True)
    word_count = Column(Integer, default=0)
    reflection_issues = Column(JSONB, nullable=True)
    user_decision = Column(JSONB, nullable=True)
    revision_count = Column(Integer, default=0)
    revision_history = Column(JSONB, nullable=True)
    status = Column(String(20), default="draft")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    novel = relationship("NovelModel", back_populates="chapters")


class MemoryModel(Base):
    __tablename__ = "novel_memories"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "novel_id"],
            ["novels.tenant_id", "novels.id"],
            ondelete="CASCADE",
            name="fk_memories_tenant_novel",
        ),
        Index("ix_memories_tenant_novel_created", "tenant_id", "novel_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    novel_id = Column(UUID(as_uuid=True), nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Text, nullable=True)
    meta_data = Column("metadata", JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    novel = relationship("NovelModel", back_populates="memories")


class QuotaLedgerModel(Base):
    __tablename__ = "quota_ledger"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "workflow_run_id",
            "operation_type",
            "chapter_index",
            name="uq_quota_operation",
        ),
        Index("ix_quota_tenant_period", "tenant_id", "period_start"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    workflow_run_id = Column(UUID(as_uuid=True), nullable=False)
    operation_type = Column(String(30), nullable=False)
    chapter_index = Column(Integer, nullable=False, default=-1)
    period_start = Column(Date, nullable=False, default=date.today)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class AuditEventModel(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_tenant_created", "tenant_id", "created_at"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True)
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    action = Column(String(80), nullable=False)
    target_type = Column(String(40), nullable=True)
    target_id = Column(String(255), nullable=True)
    details = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
