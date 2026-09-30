"""项目题材归属和关键词规范化。"""

from __future__ import annotations

import re

from .contracts import PROJECT_GENRES, SOURCE_TO_PROJECT_GENRES


def project_genres_for_source(source_category: str) -> tuple[str, ...]:
    """返回来源分类对应的主项目题材和副题材。"""
    return SOURCE_TO_PROJECT_GENRES.get(source_category.strip(), ())


def assign_project_genres(source_category: str, candidates: tuple[str, ...] = ()) -> tuple[str, tuple[str, ...]]:
    mapped = tuple(item for item in candidates if item in PROJECT_GENRES)
    ordered = mapped or project_genres_for_source(source_category)
    if not ordered:
        raise ValueError("无法为样本分配项目题材")
    return ordered[0], tuple(dict.fromkeys(ordered[1:]))


def normalize_term(value: str) -> str:
    """统一大小写和标点；中文词不做破坏性分词。"""
    return re.sub(r"\s+", "", value.strip().lower())
