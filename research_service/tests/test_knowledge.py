from datetime import datetime, timezone
import hashlib
from types import SimpleNamespace

import pytest

from research_service.contracts import (
    ChapterIndex,
    KnowledgeQuery,
    NovelMetadata,
    NovelPatternCard,
    ResearchSample,
)
from research_service.aggregate import build_knowledge_package
from research_service.repository import InMemoryResearchRepository, SqlAlchemyResearchRepository
from research_service.service import ResearchKnowledgeService


def _sample(sample_id: str, genre: str, opening: str, mechanism: str) -> ResearchSample:
    metadata = NovelMetadata(
        source_url=f"https://biquge.pro/novel/{sample_id}.html",
        source_id=sample_id,
        title=f"测试{sample_id}",
        source_category="科幻",
        project_genres=(genre,),
    )
    card = NovelPatternCard(
        metadata=metadata,
        chapter_index=ChapterIndex(digest="a" * 64),
        opening_pattern=opening,
        highlight_mechanisms=(mechanism,),
    )
    return ResearchSample(
        sample_id=sample_id,
        batch_id="batch-1",
        sample_digest=hashlib.sha256(sample_id.encode()).hexdigest(),
        primary_project_genre=genre,
        card=card,
        observed_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_samples_accumulate_by_project_genre_not_by_one_book() -> None:
    repository = InMemoryResearchRepository()
    service = ResearchKnowledgeService(repository)
    first = await service.ingest_sample(_sample("1", "sci_fi", "mystery_question", "world_rule"))
    second = await service.ingest_sample(_sample("2", "sci_fi", "immediate_crisis", "resource_rivalry"))
    await service.ingest_sample(_sample("3", "romance", "relationship_collision", "mutual_healing"))

    assert first is not None
    assert second is not None
    assert first and first.sample_count == 1
    assert second and second.sample_count == 2
    assert second.opening_pattern_counts == {"mystery_question": 1, "immediate_crisis": 1}
    assert (await repository.list_samples("romance"))[0].primary_project_genre == "romance"


@pytest.mark.asyncio
async def test_sample_storage_removes_source_summary() -> None:
    repository = InMemoryResearchRepository()
    service = ResearchKnowledgeService(repository)
    sample = _sample("raw-summary", "sci_fi", "world_reveal", "world_rule")
    sample = sample.model_copy(update={
        "card": sample.card.model_copy(update={
            "metadata": sample.card.metadata.model_copy(update={"summary": "来源简介原文"})
        })
    })
    await service.ingest_sample(sample)
    stored = (await repository.list_samples("sci_fi"))[0]
    assert stored.card.metadata.summary == ""


@pytest.mark.asyncio
async def test_duplicate_sample_does_not_create_new_knowledge_version() -> None:
    repository = InMemoryResearchRepository()
    service = ResearchKnowledgeService(repository)
    sample = _sample("1", "sci_fi", "mystery_question", "world_rule")
    await service.ingest_sample(sample)
    duplicate = await service.ingest_sample(sample)
    assert duplicate is None
    assert len(await repository.list_packages("sci_fi", approved_only=False)) == 1


@pytest.mark.asyncio
async def test_keyword_search_returns_only_current_approved_package() -> None:
    repository = InMemoryResearchRepository()
    service = ResearchKnowledgeService(repository)
    package = await service.ingest_sample(_sample("1", "sci_fi", "mystery_question", "world_rule"))
    assert package is not None
    await service.review(package.knowledge_version_id, "approve")
    hits = await service.search(KnowledgeQuery(project_genre="sci_fi", query="mystery"))
    assert len(hits) == 1
    assert hits[0].project_genre == "sci_fi"


class _AsyncScope:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


class _ReviewSession(_AsyncScope):
    def __init__(self, row: SimpleNamespace) -> None:
        self.row = row

    def begin(self) -> _AsyncScope:
        return _AsyncScope()

    async def get(self, model, version_id: str) -> SimpleNamespace | None:
        return self.row if version_id == self.row.knowledge_version_id else None


@pytest.mark.asyncio
async def test_sql_review_updates_persisted_package_status() -> None:
    package = build_package_for_test()
    row = SimpleNamespace(
        knowledge_version_id=package.knowledge_version_id,
        status="draft",
        package_json=package.model_dump(mode="json"),
    )
    session = _ReviewSession(row)
    repository = SqlAlchemyResearchRepository(lambda: session)

    reviewed = await repository.review_package(package.knowledge_version_id, "approve")

    assert reviewed and reviewed.status == "approved"
    assert row.status == "approved"
    assert row.package_json["status"] == "approved"


def build_package_for_test():
    return build_knowledge_package("sci_fi", [_sample("sql", "sci_fi", "world_reveal", "world_rule")], 1)


@pytest.mark.asyncio
async def test_secondary_genre_is_searchable_but_requires_its_own_review():
    repository = InMemoryResearchRepository()
    service = ResearchKnowledgeService(repository)
    sample = _sample("mapped", "horror", "mystery_question", "clue_puzzle")
    sample = sample.model_copy(update={"secondary_project_genres": ("suspense",)})
    primary = await service.ingest_sample(sample)
    assert primary.project_genre == "horror"
    draft = await service.search(KnowledgeQuery(project_genre="suspense", approved_only=False))
    assert len(draft) == 1
    assert draft[0].content["evidence_sample_ids"] == ["mapped"]
    assert not await service.search(KnowledgeQuery(project_genre="suspense"))
    await service.review(primary.knowledge_version_id, "approve")
    assert not await service.search(KnowledgeQuery(project_genre="suspense"))
    await service.review(draft[0].knowledge_version_id, "approve")
    assert len(await service.search(KnowledgeQuery(project_genre="suspense"))) == 1
    assert not await service.search(KnowledgeQuery(project_genre="romance", approved_only=False))


@pytest.mark.asyncio
async def test_chinese_search_matches_controlled_opening_labels():
    repository = InMemoryResearchRepository()
    service = ResearchKnowledgeService(repository)
    await service.ingest_sample(_sample("keywords", "sci_fi", "status_reversal", "world_rule"))
    for term in ("科幻", "开局", "身份反转"):
        assert await service.search(KnowledgeQuery(
            project_genre="sci_fi", query=term, approved_only=False,
        ))


def test_collected_plot_engine_and_originality_are_not_discarded():
    sample = _sample("rich", "sci_fi", "world_reveal", "world_rule")
    sample = sample.model_copy(update={"card": sample.card.model_copy(update={
        "plot_engine": "资源减少逼迫角色改变计划",
        "opening_beats": ("日常工作暴露异常",),
        "originality_directions": ("用互相约束替代无代价开挂",),
    })})
    package = build_knowledge_package("sci_fi", [sample], 1)
    assert "资源减少逼迫角色改变计划" in package.clusters[0].representative_notes[0]
    assert "日常工作暴露异常" in package.clusters[0].representative_notes[0]
    assert "用互相约束替代无代价开挂" in package.clusters[0].representative_notes[0]
