"""研究数据库模型；与写作数据库完全没有外键关系。"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ResearchBase(DeclarativeBase):
    pass


class ResearchBatchModel(ResearchBase):
    __tablename__ = "research_batches"

    batch_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ResearchJobModel(ResearchBase):
    __tablename__ = "research_jobs"

    job_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    phase: Mapped[str] = mapped_column(String(48), nullable=False, default="queued")
    processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ResearchSampleModel(ResearchBase):
    __tablename__ = "research_samples"
    __table_args__ = (
        UniqueConstraint("source_host", "source_id", "sample_digest", name="uq_research_sample_digest"),
        Index("ix_research_samples_genre", "primary_project_genre"),
    )

    sample_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_host: Mapped[str] = mapped_column(String(120), nullable=False, default="biquge.pro")
    source_id: Mapped[str] = mapped_column(String(80), nullable=False)
    sample_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    primary_project_genre: Mapped[str] = mapped_column(String(40), nullable=False)
    sample_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class GenreKnowledgeVersionModel(ResearchBase):
    __tablename__ = "genre_knowledge_versions"
    __table_args__ = (
        UniqueConstraint("project_genre", "version", name="uq_genre_knowledge_version"),
        Index("ix_genre_knowledge_current", "project_genre", "status"),
        Index(
            "ix_genre_knowledge_retrieval_trgm",
            "retrieval_text",
            postgresql_using="gin",
            postgresql_ops={"retrieval_text": "gin_trgm_ops"},
        ),
    )

    knowledge_version_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    project_genre: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    package_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    retrieval_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class GenreTermModel(ResearchBase):
    __tablename__ = "genre_terms"
    __table_args__ = (
        UniqueConstraint("knowledge_version_id", "term", "term_type", name="uq_genre_term"),
        Index("ix_genre_terms_lookup", "project_genre", "term"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knowledge_version_id: Mapped[str] = mapped_column(String(120), nullable=False)
    project_genre: Mapped[str] = mapped_column(String(40), nullable=False)
    term: Mapped[str] = mapped_column(String(160), nullable=False)
    term_type: Mapped[str] = mapped_column(String(40), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
