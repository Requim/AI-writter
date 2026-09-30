"""研究样本入库、类型知识聚合和审核用例。"""

from __future__ import annotations

from .contracts import GenreKnowledgePackage, KnowledgeQuery, ResearchSample, SearchHit
from .aggregate import build_knowledge_package
from .repository import ResearchRepository
from .retrieval import KeywordRetriever


class ResearchKnowledgeService:
    def __init__(self, repository: ResearchRepository, retriever: KeywordRetriever | None = None) -> None:
        self.repository = repository
        self.retriever = retriever or KeywordRetriever()

    async def ingest_sample(self, sample: ResearchSample) -> GenreKnowledgePackage | None:
        sanitized = self._sanitize_sample(sample)
        inserted = await self.repository.add_sample(sanitized)
        if not inserted:
            return None
        primary = await self.refresh_genre(sanitized.primary_project_genre)
        for genre in dict.fromkeys(sanitized.secondary_project_genres):
            if genre != sanitized.primary_project_genre:
                await self.refresh_genre(genre)
        return primary

    @staticmethod
    def _sanitize_sample(sample: ResearchSample) -> ResearchSample:
        metadata = sample.card.metadata.model_copy(update={"summary": ""})
        card = sample.card.model_copy(update={"metadata": metadata})
        return sample.model_copy(update={"card": card})

    async def refresh_genre(self, project_genre: str) -> GenreKnowledgePackage:
        samples = await self.repository.list_samples(project_genre)
        version = await self.repository.next_version(project_genre)
        package = build_knowledge_package(project_genre, samples, version)
        await self.repository.add_package(package)
        return package

    async def search(self, query: KnowledgeQuery) -> list[SearchHit]:
        packages = await self.repository.list_packages(
            query.project_genre, approved_only=query.approved_only,
        )
        return self.retriever.search(packages, query)

    async def review(self, version_id: str, decision: str) -> GenreKnowledgePackage | None:
        return await self.repository.review_package(version_id, decision)
