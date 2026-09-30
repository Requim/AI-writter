from datetime import datetime, timezone
import hashlib

import httpx
import pytest

from research_service.api import create_app
from research_service.contracts import ChapterIndex, NovelMetadata, NovelPatternCard, ResearchSample
from research_service.repository import InMemoryResearchRepository


def _sample() -> ResearchSample:
    metadata = NovelMetadata(
        source_url="https://biquge.pro/novel/801.html",
        source_id="801",
        title="接口测试",
        source_category="科幻",
        project_genres=("sci_fi",),
    )
    card = NovelPatternCard(
        metadata=metadata,
        chapter_index=ChapterIndex(digest="b" * 64),
        opening_pattern="world_reveal",
        highlight_mechanisms=("world_rule",),
    )
    return ResearchSample(
        sample_id="sample-api",
        batch_id="batch-api",
        sample_digest=hashlib.sha256(b"api").hexdigest(),
        primary_project_genre="sci_fi",
        card=card,
        observed_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_api_ingest_review_and_search() -> None:
    app = create_app(InMemoryResearchRepository())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/internal/v1/research/samples", json=_sample().model_dump(mode="json"))
            assert response.status_code == 200
            version_id = response.json()["knowledge"]["knowledge_version_id"]
            reviewed = await client.post(
                f"/internal/v1/research/knowledge/{version_id}/review",
                json={"decision": "approve", "reviewer": "test"},
            )
            assert reviewed.status_code == 200
            result = await client.get(
                "/internal/v1/research/knowledge/search",
                params={"project_genre": "sci_fi", "q": "world_reveal"},
            )
            assert result.status_code == 200
            assert len(result.json()["items"]) == 1


@pytest.mark.asyncio
async def test_api_batch_is_queued_for_worker() -> None:
    repository = InMemoryResearchRepository()
    app = create_app(repository)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/internal/v1/research/batches",
                json={
                    "batch_id": "batch-queued",
                    "categories": ["科幻"],
                    "sources": {"科幻": {"popular": ["https://biquge.pro/lists/51.html"]}},
                },
            )
            assert response.status_code == 200
            job_id = response.json()["job_id"]
            status = await client.get(f"/internal/v1/research/jobs/{job_id}")
            assert status.json()["status"] == "queued"
            claimed = await repository.claim_next_job()
            assert claimed and claimed[1].batch_id == "batch-queued"


@pytest.mark.asyncio
async def test_api_rejects_batch_without_catalog_sources() -> None:
    repository = InMemoryResearchRepository()
    app = create_app(repository)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/internal/v1/research/batches",
                json={"batch_id": "batch-empty", "categories": ["科幻"], "sources": {}},
            )
            assert response.status_code == 422
            assert "缺少目录来源" in response.text
