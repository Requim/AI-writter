"""SQLAlchemy models for tenant-isolated novel writing data."""

from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    false,
    func,
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
    monthly_generation_unlimited = Column(Boolean, nullable=False, default=False)
    novel_planning_v1_enabled = Column(
        Boolean, nullable=False, default=False, server_default=false()
    )
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
    plan_versions = relationship(
        "NovelPlanVersionModel", back_populates="novel", cascade="all, delete-orphan"
    )
    plan_executions = relationship(
        "NovelPlanExecutionModel", back_populates="novel", cascade="all, delete-orphan"
    )
    tactical_plan_versions = relationship(
        "NovelTacticalPlanVersionModel",
        back_populates="novel",
        cascade="all, delete-orphan",
    )


class NovelPlanVersionModel(Base):
    __tablename__ = "novel_plan_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "novel_id"],
            ["novels.tenant_id", "novels.id"],
            ondelete="CASCADE",
            name="fk_plan_versions_tenant_novel",
        ),
        UniqueConstraint(
            "tenant_id", "novel_id", "version", name="uq_plan_versions_version"
        ),
        UniqueConstraint(
            "tenant_id", "novel_id", "idempotency_key",
            name="uq_plan_versions_idempotency",
        ),
        Index(
            "ix_plan_versions_tenant_novel",
            "tenant_id",
            "novel_id",
            "version",
        ),
        CheckConstraint("version >= 1", name="ck_plan_versions_positive_version"),
        CheckConstraint("source <> ''", name="ck_plan_versions_source"),
        CheckConstraint(
            "trigger_chapter IS NULL OR trigger_chapter >= 1",
            name="ck_plan_versions_trigger_chapter",
        ),
        CheckConstraint(
            "idempotency_key IS NULL OR idempotency_key <> ''",
            name="ck_plan_versions_idempotency_key",
        ),
        CheckConstraint(
            "jsonb_typeof(plan) = 'object'", name="ck_plan_versions_plan_object"
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    novel_id = Column(UUID(as_uuid=True), nullable=False)
    version = Column(Integer, nullable=False)
    source = Column(String(30), nullable=False)
    trigger_chapter = Column(Integer, nullable=True)
    change_summary = Column(Text, nullable=False, default="", server_default="")
    idempotency_key = Column(String(128), nullable=True)
    plan_data = Column("plan", JSONB, nullable=False)
    created_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )

    novel = relationship("NovelModel", back_populates="plan_versions")


class NovelTacticalPlanVersionModel(Base):
    __tablename__ = "novel_tactical_plan_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "novel_id"],
            ["novels.tenant_id", "novels.id"],
            ondelete="CASCADE",
            name="fk_tactical_versions_tenant_novel",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "novel_id", "novel_plan_version"],
            [
                "novel_plan_versions.tenant_id",
                "novel_plan_versions.novel_id",
                "novel_plan_versions.version",
            ],
            ondelete="CASCADE",
            name="fk_tactical_versions_plan_version",
        ),
        UniqueConstraint(
            "tenant_id", "novel_id", "version",
            name="uq_tactical_versions_version",
        ),
        UniqueConstraint(
            "tenant_id", "novel_id", "idempotency_key",
            name="uq_tactical_versions_idempotency",
        ),
        Index(
            "ix_tactical_versions_tenant_novel",
            "tenant_id", "novel_id", "version",
        ),
        CheckConstraint("version >= 1", name="ck_tactical_versions_version"),
        CheckConstraint(
            "novel_plan_version >= 1", name="ck_tactical_versions_plan_version"
        ),
        CheckConstraint(
            "story_state_revision >= 0", name="ck_tactical_versions_story_revision"
        ),
        CheckConstraint(
            "window_start >= 1 AND window_end >= window_start "
            "AND window_end - window_start <= 6",
            name="ck_tactical_versions_window",
        ),
        CheckConstraint("source <> ''", name="ck_tactical_versions_source"),
        CheckConstraint(
            "idempotency_key <> ''",
            name="ck_tactical_versions_idempotency_key",
        ),
        CheckConstraint(
            "jsonb_typeof(window) = 'object'",
            name="ck_tactical_versions_window_object",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    novel_id = Column(UUID(as_uuid=True), nullable=False)
    version = Column(Integer, nullable=False)
    novel_plan_version = Column(Integer, nullable=False)
    story_state_revision = Column(Integer, nullable=False)
    window_start = Column(Integer, nullable=False)
    window_end = Column(Integer, nullable=False)
    source = Column(String(30), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    window_data = Column("window", JSONB, nullable=False)
    created_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=utc_now, server_default=func.now(),
    )

    novel = relationship("NovelModel", back_populates="tactical_plan_versions")


class NovelPlanExecutionModel(Base):
    __tablename__ = "novel_plan_executions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "novel_id"],
            ["novels.tenant_id", "novels.id"],
            ondelete="CASCADE",
            name="fk_plan_executions_tenant_novel",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "novel_id", "plan_version"],
            [
                "novel_plan_versions.tenant_id",
                "novel_plan_versions.novel_id",
                "novel_plan_versions.version",
            ],
            ondelete="CASCADE",
            name="fk_plan_executions_plan_version",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "novel_id", "tactical_version"],
            [
                "novel_tactical_plan_versions.tenant_id",
                "novel_tactical_plan_versions.novel_id",
                "novel_tactical_plan_versions.version",
            ],
            ondelete="CASCADE",
            name="fk_plan_executions_tactical_version",
        ),
        UniqueConstraint(
            "tenant_id",
            "novel_id",
            "chapter_number",
            name="uq_plan_executions_chapter",
        ),
        Index(
            "ix_plan_executions_tenant_novel",
            "tenant_id",
            "novel_id",
            "chapter_number",
        ),
        CheckConstraint("chapter_number >= 1", name="ck_plan_execution_chapter"),
        CheckConstraint("plan_version >= 1", name="ck_plan_execution_version"),
        CheckConstraint(
            "tactical_version IS NULL OR tactical_version >= 1",
            name="ck_plan_execution_tactical_version",
        ),
        CheckConstraint("actual_words >= 0", name="ck_plan_execution_words"),
        CheckConstraint("status <> ''", name="ck_plan_execution_status"),
        CheckConstraint(
            "drift_severity IN ('none', 'minor', 'major')",
            name="ck_plan_execution_drift",
        ),
        CheckConstraint(
            "jsonb_typeof(fulfillment) = 'object'",
            name="ck_plan_execution_fulfillment_object",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    novel_id = Column(UUID(as_uuid=True), nullable=False)
    chapter_number = Column(Integer, nullable=False)
    plan_version = Column(Integer, nullable=False)
    tactical_version = Column(Integer, nullable=True)
    status = Column(String(30), nullable=False)
    actual_words = Column(Integer, nullable=False, default=0, server_default="0")
    fulfillment = Column(JSONB, nullable=False, default=dict, server_default="{}")
    drift_severity = Column(
        String(10), nullable=False, default="none", server_default="none"
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=utc_now,
        server_default=func.now(), onupdate=utc_now
    )

    novel = relationship("NovelModel", back_populates="plan_executions")


class ChapterModel(Base):
    __tablename__ = "chapters"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "novel_id"],
            ["novels.tenant_id", "novels.id"],
            ondelete="CASCADE",
            name="fk_chapters_tenant_novel",
        ),
        UniqueConstraint(
            "tenant_id",
            "novel_id",
            "chapter_index",
            name="uq_chapters_tenant_novel_index",
        ),
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
    version = Column(Integer, nullable=False, default=1, server_default="1")
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
