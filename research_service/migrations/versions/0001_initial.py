"""研究服务独立数据库初始结构。"""

from alembic import op
import sqlalchemy as sa

revision = "0001_research_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "research_batches",
        sa.Column("batch_id", sa.String(120), primary_key=True),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "research_jobs",
        sa.Column("job_id", sa.String(120), primary_key=True),
        sa.Column("batch_id", sa.String(120), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("phase", sa.String(48), nullable=False),
        sa.Column("processed", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Index("ix_research_jobs_batch", "batch_id"),
    )
    op.create_table(
        "research_samples",
        sa.Column("sample_id", sa.String(120), primary_key=True),
        sa.Column("batch_id", sa.String(120), nullable=False),
        sa.Column("source_host", sa.String(120), nullable=False),
        sa.Column("source_id", sa.String(80), nullable=False),
        sa.Column("sample_digest", sa.String(64), nullable=False),
        sa.Column("primary_project_genre", sa.String(40), nullable=False),
        sa.Column("sample_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_host", "source_id", "sample_digest", name="uq_research_sample_digest"),
        sa.Index("ix_research_samples_genre", "primary_project_genre"),
    )
    op.create_table(
        "genre_knowledge_versions",
        sa.Column("knowledge_version_id", sa.String(120), primary_key=True),
        sa.Column("project_genre", sa.String(40), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("package_json", sa.JSON(), nullable=False),
        sa.Column("retrieval_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_genre", "version", name="uq_genre_knowledge_version"),
        sa.Index("ix_genre_knowledge_current", "project_genre", "status"),
    )
    op.create_index(
        "ix_genre_knowledge_retrieval_trgm",
        "genre_knowledge_versions",
        ["retrieval_text"],
        postgresql_using="gin",
        postgresql_ops={"retrieval_text": "gin_trgm_ops"},
    )
    op.create_table(
        "genre_terms",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("knowledge_version_id", sa.String(120), nullable=False),
        sa.Column("project_genre", sa.String(40), nullable=False),
        sa.Column("term", sa.String(160), nullable=False),
        sa.Column("term_type", sa.String(40), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.UniqueConstraint("knowledge_version_id", "term", "term_type", name="uq_genre_term"),
        sa.Index("ix_genre_terms_lookup", "project_genre", "term"),
    )


def downgrade() -> None:
    op.drop_index("ix_genre_knowledge_retrieval_trgm", table_name="genre_knowledge_versions")
    for table in (
        "genre_terms", "genre_knowledge_versions", "research_samples",
        "research_jobs", "research_batches",
    ):
        op.drop_table(table)
