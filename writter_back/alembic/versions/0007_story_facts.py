"""新增实体、版本化规范事实与正文断言；不回填历史正文。"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0007_story_facts"
down_revision = "0006_tactical_planning"
branch_labels = None
depends_on = None


def _scope():
    return [
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "novel_id"], ["novels.tenant_id", "novels.id"], ondelete="CASCADE"),
    ]


def _statement_fields():
    return [
        sa.Column("subject_id", UUID(as_uuid=True), nullable=False),
        sa.Column("predicate", sa.String(40), nullable=False),
        sa.Column("object_entity_id", UUID(as_uuid=True), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("evidence", JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "novel_id", "subject_id"],
                                ["story_entities.tenant_id", "story_entities.novel_id", "story_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id", "novel_id", "object_entity_id"],
                                ["story_entities.tenant_id", "story_entities.novel_id", "story_entities.id"]),
    ]


def _create_entities():
    op.create_table(
        "story_entities", *_scope(),
        sa.Column("entity_key", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("aliases", JSONB(), nullable=False),
        sa.UniqueConstraint("tenant_id", "novel_id", "id", name="uq_story_entity_scope"),
        sa.UniqueConstraint("tenant_id", "novel_id", "entity_key", name="uq_story_entity_key"),
        sa.CheckConstraint("kind IN ('character','family','place','item')", name="ck_story_entity_kind"),
    )


def _create_versions():
    op.create_table(
        "story_fact_versions", *_scope(), *_statement_fields(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("valid_from_chapter", sa.Integer(), nullable=False),
        sa.Column("valid_to_chapter", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "novel_id", "subject_id", "predicate", "version", name="uq_story_fact_version"),
        sa.UniqueConstraint("tenant_id", "novel_id", "idempotency_key", name="uq_story_fact_request"),
        sa.CheckConstraint("version > 0 AND valid_from_chapter > 0", name="ck_story_fact_positive"),
        sa.CheckConstraint("valid_to_chapter IS NULL OR valid_to_chapter >= valid_from_chapter", name="ck_story_fact_range"),
        sa.CheckConstraint("status IN ('confirmed','retracted')", name="ck_story_fact_status"),
        sa.CheckConstraint("(object_entity_id IS NULL) <> (value_text IS NULL)", name="ck_story_fact_value"),
    )


def upgrade():
    _create_entities()
    _create_versions()
    op.create_table(
        "story_fact_assertions", *_scope(), *_statement_fields(),
        sa.Column("chapter_number", sa.Integer(), nullable=False),
        sa.CheckConstraint("chapter_number > 0", name="ck_story_assertion_chapter"),
        sa.CheckConstraint("(object_entity_id IS NULL) <> (value_text IS NULL)", name="ck_story_assertion_value"),
    )
    op.create_index("ix_story_assertion_scope", "story_fact_assertions", ["tenant_id", "novel_id", "chapter_number"])


def downgrade():
    op.drop_table("story_fact_assertions")
    op.drop_table("story_fact_versions")
    op.drop_table("story_entities")
