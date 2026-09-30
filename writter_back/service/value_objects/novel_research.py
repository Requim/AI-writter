"""受限小说题材研究的结构化契约；不承载原始正文。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


BIQUGE_SOURCE_CATEGORIES = ("玄幻", "武侠", "恐怖", "军事", "女频", "游戏", "科幻")
BIQUGE_CATEGORY_PATHS = {
    "玄幻": "/lists/42.html",
    "武侠": "/lists/44.html",
    "恐怖": "/lists/46.html",
    "军事": "/lists/47.html",
    "女频": "/lists/48.html",
    "游戏": "/lists/49.html",
    "科幻": "/lists/51.html",
}
OPENING_PATTERNS = (
    "immediate_crisis",
    "mystery_question",
    "status_reversal",
    "system_or_mission",
    "rebirth_or_transport",
    "relationship_collision",
    "ordinary_to_inciting_event",
    "world_reveal",
)
PROJECT_GENRE_MAP = {
    "玄幻": ("fantasy", "xianxia"),
    "武侠": ("wuxia",),
    "恐怖": ("horror", "suspense"),
    "军事": ("history",),
    "女频": ("romance",),
    "游戏": (),
    "科幻": ("sci_fi",),
}


def _validate_biquge_host(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"biquge.pro", "www.biquge.pro"}:
        raise ValueError("研究来源必须来自 biquge.pro")
    return value


class ResearchContract(BaseModel):
    """研究结果只允许结构化字段，禁止隐式带入正文。"""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SourceLocation(ResearchContract):
    url: str = Field(min_length=1, max_length=2000)
    chapter_number: int | None = Field(default=None, ge=1)
    paragraph_index: int | None = Field(default=None, ge=1)
    paraphrase: str = Field(min_length=1, max_length=500)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return _validate_biquge_host(value)


class CatalogCandidate(ResearchContract):
    url: str = Field(min_length=1, max_length=2000)
    title: str = Field(min_length=1, max_length=240)
    author: str = Field(default="", max_length=120)
    source_category: str = Field(min_length=1, max_length=40)
    bucket: Literal["popular", "new", "recent", "fallback"] = "fallback"
    rank: int = Field(default=0, ge=0)


class ResearchBatch(ResearchContract):
    batch_id: str = Field(min_length=1, max_length=120)
    source_host: Literal["biquge.pro"] = "biquge.pro"
    fetched_at: datetime
    categories: tuple[str, ...] = Field(min_length=1, max_length=7)
    sample_target_per_category: int = Field(default=10, ge=1, le=100)
    parser_version: str = Field(min_length=1, max_length=40)
    policy_version: str = Field(min_length=1, max_length=40)
    status: Literal["draft", "complete", "incomplete"] = "draft"
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values) or any(item not in BIQUGE_SOURCE_CATEGORIES for item in values):
            raise ValueError("批次分类必须是唯一的笔趣阁明确分类")
        return values

    @field_validator("fetched_at")
    @classmethod
    def validate_fetched_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("批次时间必须包含时区")
        return value


class NovelMetadata(ResearchContract):
    source_url: str = Field(min_length=1, max_length=2000)
    source_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=240)
    author: str = Field(default="", max_length=120)
    source_category: str = Field(min_length=1, max_length=40)
    project_genres: tuple[str, ...] = Field(default=(), max_length=4)
    status: str = Field(default="", max_length=40)
    summary: str = Field(default="", max_length=3000)
    updated_at: str | None = Field(default=None, max_length=40)
    latest_chapter: str = Field(default="", max_length=240)
    first_chapter_url: str | None = Field(default=None, max_length=2000)

    @field_validator("source_url", "first_chapter_url")
    @classmethod
    def validate_source_urls(cls, value: str | None) -> str | None:
        return _validate_biquge_host(value) if value else value


class ChapterIndex(ResearchContract):
    titles: tuple[str, ...] = Field(default=(), max_length=120)
    total_count: int = Field(default=0, ge=0)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    sampled: bool = False


class OpeningMetrics(ResearchContract):
    character_count: int = Field(ge=0)
    paragraph_count: int = Field(ge=0)
    dialogue_ratio: float = Field(default=0, ge=0, le=1)
    first_pressure_offset: int | None = Field(default=None, ge=0)


class NovelPatternCard(ResearchContract):
    metadata: NovelMetadata
    chapter_index: ChapterIndex
    opening_metrics: OpeningMetrics | None = None
    highlight_mechanisms: tuple[str, ...] = Field(default=(), max_length=5)
    opening_pattern: str = Field(min_length=1, max_length=60)
    opening_beats: tuple[str, ...] = Field(default=(), max_length=6)
    reader_promise: str = Field(default="", max_length=800)
    plot_engine: str = Field(default="", max_length=800)
    originality_directions: tuple[str, ...] = Field(default=(), max_length=5)
    evidence: tuple[SourceLocation, ...] = Field(default=(), max_length=8)
    confidence: Literal["high", "medium", "low"] = "low"
    limitations: tuple[str, ...] = Field(default=(), max_length=8)

    @field_validator("opening_pattern")
    @classmethod
    def validate_opening_pattern(cls, value: str) -> str:
        if value not in OPENING_PATTERNS:
            raise ValueError("开局方式必须使用受控标签")
        return value


class GenrePatternReport(ResearchContract):
    source_category: str = Field(min_length=1, max_length=40)
    sample_count: int = Field(ge=1)
    opening_pattern_counts: dict[str, int]
    mechanism_counts: dict[str, int]
    common_opening_patterns: tuple[str, ...] = Field(default=(), max_length=8)
    common_mechanisms: tuple[str, ...] = Field(default=(), max_length=12)
    originality_rules: tuple[str, ...] = Field(default=(), max_length=8)
    limitations: tuple[str, ...] = Field(default=(), max_length=8)


def project_genres_for(source_category: str) -> tuple[str, ...]:
    """保留来源分类，同时给创作流程提供保守的题材映射。"""
    return PROJECT_GENRE_MAP.get(source_category.strip(), ())


def _top_keys(values: Counter[str], limit: int) -> tuple[str, ...]:
    return tuple(key for key, _ in values.most_common(limit))


def build_genre_pattern_report(
    cards: list[NovelPatternCard], source_category: str,
) -> GenrePatternReport:
    """只聚合结构化卡片，不重新读取或拼接小说正文。"""
    if not cards:
        raise ValueError("至少需要一张研究卡片")
    if any(card.metadata.source_category != source_category for card in cards):
        raise ValueError("研究卡片必须属于同一来源分类")
    openings = Counter(card.opening_pattern for card in cards)
    mechanisms = Counter(item for card in cards for item in card.highlight_mechanisms)
    return GenrePatternReport(
        source_category=source_category,
        sample_count=len(cards),
        opening_pattern_counts=dict(openings),
        mechanism_counts=dict(mechanisms),
        common_opening_patterns=_top_keys(openings, 8),
        common_mechanisms=_top_keys(mechanisms, 12),
        limitations=("结果只代表本批样本中的结构观察，不等于市场因果结论。",),
    )
