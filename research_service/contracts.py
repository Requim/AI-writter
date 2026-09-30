"""研究服务的公共数据契约；不承载完整小说正文。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SOURCE_CATEGORIES = ("玄幻", "武侠", "恐怖", "军事", "女频", "游戏", "科幻")
BIQUGE_SOURCE_CATEGORIES = SOURCE_CATEGORIES
PROJECT_GENRES = (
    "fantasy", "xianxia", "wuxia", "horror", "suspense", "military",
    "history", "romance", "game", "sci_fi",
)
OPENING_PATTERNS = (
    "immediate_crisis", "mystery_question", "status_reversal",
    "system_or_mission", "rebirth_or_transport", "relationship_collision",
    "ordinary_to_inciting_event", "world_reveal",
)
OPENING_PATTERN_LABELS = {
    "immediate_crisis": "即时危机", "mystery_question": "谜题提问",
    "status_reversal": "身份反转", "system_or_mission": "系统或任务",
    "rebirth_or_transport": "重生或穿越", "relationship_collision": "关系碰撞",
    "ordinary_to_inciting_event": "日常转入事件", "world_reveal": "世界揭示",
}

SOURCE_TO_PROJECT_GENRES = {
    "玄幻": ("fantasy", "xianxia"),
    "武侠": ("wuxia",),
    "恐怖": ("horror", "suspense"),
    "军事": ("military", "history"),
    "女频": ("romance",),
    "游戏": ("game",),
    "科幻": ("sci_fi",),
}

PROJECT_GENRE_LABELS = {
    "fantasy": "奇幻 / 玄幻", "xianxia": "仙侠", "wuxia": "武侠",
    "horror": "惊悚 / 恐怖", "suspense": "悬疑", "military": "军事",
    "history": "历史", "romance": "言情", "game": "游戏", "sci_fi": "科幻",
}


def _validate_source_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.hostname not in {"biquge.pro", "www.biquge.pro"}:
        raise ValueError("研究来源必须来自 biquge.pro")
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("研究来源必须使用 HTTP 或 HTTPS")
    return value


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SourceEvidence(Contract):
    url: str = Field(min_length=1, max_length=2000)
    chapter_number: int | None = Field(default=None, ge=1)
    paraphrase: str = Field(min_length=1, max_length=500)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return _validate_source_url(value)


class CatalogCandidate(Contract):
    url: str = Field(min_length=1, max_length=2000)
    title: str = Field(min_length=1, max_length=240)
    author: str = Field(default="", max_length=120)
    source_category: str = Field(min_length=1, max_length=40)
    bucket: Literal["popular", "new", "recent", "fallback"] = "fallback"
    rank: int = Field(default=0, ge=0)


class NovelMetadata(Contract):
    source_url: str = Field(min_length=1, max_length=2000)
    source_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=240)
    author: str = Field(default="", max_length=120)
    source_category: str = Field(min_length=1, max_length=40)
    project_genres: tuple[str, ...] = Field(default=(), max_length=4)
    status: str = Field(default="", max_length=40)
    summary: str = Field(default="", max_length=3000)
    updated_at: str | None = Field(default=None, max_length=80)
    latest_chapter: str = Field(default="", max_length=240)
    first_chapter_url: str | None = Field(default=None, max_length=2000)

    @field_validator("source_url", "first_chapter_url")
    @classmethod
    def validate_urls(cls, value: str | None) -> str | None:
        return _validate_source_url(value) if value else value

    @field_validator("project_genres")
    @classmethod
    def validate_project_genres(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(value not in PROJECT_GENRES for value in values):
            raise ValueError("存在未注册的项目题材")
        return values


class ChapterIndex(Contract):
    titles: tuple[str, ...] = Field(default=(), max_length=120)
    total_count: int = Field(default=0, ge=0)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    sampled: bool = False


class OpeningMetrics(Contract):
    character_count: int = Field(default=0, ge=0)
    paragraph_count: int = Field(default=0, ge=0)
    dialogue_ratio: float = Field(default=0, ge=0, le=1)
    first_pressure_offset: int | None = Field(default=None, ge=0)


class NovelPatternCard(Contract):
    metadata: NovelMetadata
    chapter_index: ChapterIndex
    opening_metrics: OpeningMetrics | None = None
    highlight_mechanisms: tuple[str, ...] = Field(default=(), max_length=8)
    opening_pattern: str = Field(min_length=1, max_length=60)
    opening_beats: tuple[str, ...] = Field(default=(), max_length=8)
    reader_promise: str = Field(default="", max_length=800)
    plot_engine: str = Field(default="", max_length=800)
    originality_directions: tuple[str, ...] = Field(default=(), max_length=8)
    evidence: tuple[SourceEvidence, ...] = Field(default=(), max_length=8)
    confidence: Literal["high", "medium", "low"] = "low"
    limitations: tuple[str, ...] = Field(default=(), max_length=8)

    @field_validator("opening_pattern")
    @classmethod
    def validate_opening_pattern(cls, value: str) -> str:
        if value not in OPENING_PATTERNS:
            raise ValueError("开局方式必须使用受控标签")
        return value


class ResearchSample(Contract):
    sample_id: str = Field(min_length=1, max_length=120)
    batch_id: str = Field(min_length=1, max_length=120)
    sample_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    primary_project_genre: str
    secondary_project_genres: tuple[str, ...] = ()
    card: NovelPatternCard
    observed_at: datetime

    @field_validator("primary_project_genre")
    @classmethod
    def validate_primary_genre(cls, value: str) -> str:
        if value not in PROJECT_GENRES:
            raise ValueError("主项目题材未注册")
        return value


class PatternCluster(Contract):
    dimension: Literal["opening_pattern", "highlight_mechanism"]
    key: str = Field(min_length=1, max_length=120)
    sample_count: int = Field(ge=1)
    sample_ids: tuple[str, ...] = Field(default=(), max_length=200)
    representative_notes: tuple[str, ...] = Field(default=(), max_length=8)


class GenreKnowledgePackage(Contract):
    knowledge_version_id: str = Field(min_length=1, max_length=120)
    project_genre: str
    version: int = Field(ge=1)
    status: Literal["draft", "review", "approved", "rejected"] = "draft"
    sample_count: int = Field(ge=0)
    source_categories: tuple[str, ...] = ()
    opening_pattern_counts: dict[str, int] = Field(default_factory=dict)
    mechanism_counts: dict[str, int] = Field(default_factory=dict)
    clusters: tuple[PatternCluster, ...] = Field(default_factory=tuple)
    writing_guidance: tuple[str, ...] = Field(default_factory=tuple)
    originality_rules: tuple[str, ...] = Field(default_factory=tuple)
    limitations: tuple[str, ...] = Field(default_factory=tuple)
    evidence_sample_ids: tuple[str, ...] = Field(default_factory=tuple)
    retrieval_text: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BatchRequest(Contract):
    batch_id: str = Field(min_length=1, max_length=120)
    categories: tuple[str, ...] = Field(min_length=1, max_length=7)
    sample_target_per_category: int = Field(default=10, ge=1, le=100)
    sources: dict[str, dict[str, tuple[str, ...]]] = Field(default_factory=dict)
    authorized_opening: bool = False

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(value not in SOURCE_CATEGORIES for value in values):
            raise ValueError("存在未注册的来源分类")
        return tuple(dict.fromkeys(values))

    @model_validator(mode="after")
    def validate_sources(self) -> "BatchRequest":
        """每个待采集分类必须提供受限目录页，避免空批次进入 Worker。"""
        allowed_buckets = {"popular", "new", "recent", "fallback"}
        missing = []
        for category in self.categories:
            buckets = self.sources.get(category, {})
            if not any(buckets.values()):
                missing.append(category)
            for bucket, urls in buckets.items():
                if bucket not in allowed_buckets:
                    raise ValueError(f"{category} 包含未注册的来源分组：{bucket}")
                for url in urls:
                    parsed = urlparse(_validate_source_url(url))
                    if not parsed.path.startswith("/lists/"):
                        raise ValueError(f"{category} 目录来源必须使用 /lists/ 页面")
        if missing:
            raise ValueError(f"以下分类缺少目录来源：{'、'.join(missing)}")
        return self


class BatchAccepted(Contract):
    batch_id: str
    job_id: str
    status: Literal["queued"] = "queued"


class JobStatus(Contract):
    job_id: str
    batch_id: str
    status: Literal["queued", "running", "completed", "partial", "failed"]
    phase: str
    processed: int = 0
    total: int = 0
    error: str | None = None


class KnowledgeQuery(Contract):
    project_genre: str
    query: str = ""
    opening_pattern: str | None = None
    mechanism: str | None = None
    limit: int = Field(default=8, ge=1, le=50)
    approved_only: bool = True


class SearchHit(Contract):
    knowledge_version_id: str
    project_genre: str
    version: int
    status: str
    score: float
    matched_terms: tuple[str, ...] = ()
    content: dict[str, Any]


class ReviewRequest(Contract):
    decision: Literal["approve", "reject"]
    reviewer: str = Field(min_length=1, max_length=120)
    comment: str = Field(default="", max_length=1000)
