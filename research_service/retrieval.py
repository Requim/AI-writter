"""关键词优先的类型知识检索器。"""

from __future__ import annotations

import re

from .contracts import (
    GenreKnowledgePackage, KnowledgeQuery, SearchHit,
    OPENING_PATTERN_LABELS, PROJECT_GENRE_LABELS,
)
from .taxonomy import normalize_term


def _terms(value: str) -> tuple[str, ...]:
    normalized = normalize_term(value)
    if not normalized:
        return ()
    chunks = [item for item in re.split(r"[,，。；;、/|]+", normalized) if item]
    if len(chunks) == 1 and len(normalized) > 2:
        chunks.extend(normalized[index:index + 2] for index in range(len(normalized) - 1))
    return tuple(dict.fromkeys(chunks))


class KeywordRetriever:
    """当前检索实现；未来可用 VectorRetriever 替换，不改变知识包契约。"""

    def search(
        self,
        packages: list[GenreKnowledgePackage],
        query: KnowledgeQuery,
    ) -> list[SearchHit]:
        result = []
        query_terms = _terms(query.query)
        for package in packages:
            if package.project_genre != query.project_genre:
                continue
            score, matched = self._score(package, query_terms, query)
            if score <= 0 and (query.query or query.opening_pattern or query.mechanism):
                continue
            result.append(SearchHit(
                knowledge_version_id=package.knowledge_version_id,
                project_genre=package.project_genre,
                version=package.version,
                status=package.status,
                score=score,
                matched_terms=tuple(matched),
                content=package.model_dump(mode="json"),
            ))
        return sorted(result, key=lambda item: (-item.score, -item.version))[:query.limit]

    def _score(
        self,
        package: GenreKnowledgePackage,
        query_terms: tuple[str, ...],
        query: KnowledgeQuery,
    ) -> tuple[float, list[str]]:
        text = normalize_term(" ".join([
            package.retrieval_text, PROJECT_GENRE_LABELS.get(package.project_genre, ""),
            *package.source_categories, *package.writing_guidance,
            *[OPENING_PATTERN_LABELS.get(key, key) for key in package.opening_pattern_counts],
        ]))
        matched = [term for term in query_terms if term in text]
        score = float(len(matched) * 10)
        if query.opening_pattern in package.opening_pattern_counts:
            score += 20
            matched.append(query.opening_pattern)
        if query.mechanism in package.mechanism_counts:
            score += 15
            matched.append(query.mechanism or "")
        if not query.query and not query.opening_pattern and not query.mechanism:
            score = 1
        return score, list(dict.fromkeys(item for item in matched if item))
