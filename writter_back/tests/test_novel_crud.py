"""PostgreSQL integration tests for tenant-scoped novel access."""

from datetime import datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from infrastructure.database.models import MemoryModel
from service.entities.chapter import Chapter
from service.value_objects.progress import Progress


async def _store_chapter(repository, tenant_id: str, novel_id: str, index: int):
    chapter = Chapter(
        novel_id=UUID(novel_id),
        chapter_index=index,
        title=f"第{index + 1}章",
        outline={"chapter_number": index + 1, "title": f"第{index + 1}章"},
        content=f"第{index + 1}章正文",
        word_count=6,
        status="completed",
    )
    await repository.replace_chapter(
        tenant_id,
        novel_id,
        chapter,
        chapter.content,
        {"type": "chapter", "chapter_index": index},
        Progress(
            current_chapter=index + 1,
            total_chapters=4,
            percentage=(index + 1) / 4 * 100,
            status="completed" if index == 3 else "writing",
        ),
        chapter_summary=f"第{index + 1}章摘要",
        story_state=f'{{"updated_through_chapter": {index + 1}}}',
        rolling_plan=f"第{index + 1}章后续规划",
    )
    return chapter


@pytest.mark.asyncio
async def test_create_and_list_novel_for_current_tenant(
    async_client, repository, tenant_context
):
    response = await async_client.post(
        "/api/v1/novels",
        json={
            "novel_type": "suspense",
            "title": "租户甲的小说",
            "summary": "隔离测试",
        },
    )
    assert response.status_code == 201
    novel_id = response.json()["novel_id"]
    novel = await repository.find_by_id(str(tenant_context.tenant_id), novel_id)
    assert novel is not None
    assert novel.tenant_id == tenant_context.tenant_id
    listed = await async_client.get("/api/v1/novels")
    assert [item["id"] for item in listed.json()] == [novel_id]


@pytest.mark.asyncio
async def test_cross_tenant_resource_is_invisible(
    repository, tenant_context, other_tenant_context, sample_novel
):
    await repository.save(str(tenant_context.tenant_id), sample_novel)
    assert await repository.find_by_id(
        str(other_tenant_context.tenant_id), str(sample_novel.id)
    ) is None
    await repository.delete(str(other_tenant_context.tenant_id), str(sample_novel.id))
    assert await repository.find_by_id(
        str(tenant_context.tenant_id), str(sample_novel.id)
    ) is not None


@pytest.mark.asyncio
async def test_invalid_type_and_missing_novel(async_client):
    invalid = await async_client.post(
        "/api/v1/novels", json={"novel_type": "invalid_type"}
    )
    assert invalid.status_code == 400
    missing = await async_client.get(f"/api/v1/novels/{uuid4()}")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_genre_taxonomy_endpoint_returns_authoritative_profiles(async_client):
    response = await async_client.get("/api/v1/novels/genre-taxonomy")

    assert response.status_code == 200
    taxonomy = response.json()
    assert len(taxonomy) == 10
    horror = next(item for item in taxonomy if item["value"] == "horror")
    assert horror["label"] == "惊悚"
    assert taxonomy[0]["subgenres"][0]["value"]
    assert any(item["value"] == "balanced" for item in taxonomy[0]["pace_options"])


@pytest.mark.asyncio
async def test_outline_round_trip(repository, tenant_context, sample_novel_with_outline):
    await repository.save(str(tenant_context.tenant_id), sample_novel_with_outline)
    saved = await repository.find_by_id(
        str(tenant_context.tenant_id), str(sample_novel_with_outline.id)
    )
    assert saved is not None
    assert saved.total_outline is not None
    assert saved.total_outline.story_background == "一个发生在封闭别墅的谋杀案"


@pytest.mark.asyncio
async def test_chapter_edit_updates_memory_and_rejects_stale_version(
    repository, tenant_context, sample_novel_with_outline
):
    tenant_id = str(tenant_context.tenant_id)
    novel_id = str(sample_novel_with_outline.id)
    await repository.save(tenant_id, sample_novel_with_outline)
    chapter = await _store_chapter(repository, tenant_id, novel_id, 0)
    chapter.title = "修订后的第一章"
    chapter.content = "修订后的正文内容"
    chapter.word_count = len(chapter.content)
    chapter.updated_at = datetime.now()

    saved = await repository.update_chapter_consistently(
        tenant_id,
        novel_id,
        chapter,
        1,
        chapter.content,
        {"type": "chapter", "chapter_index": 0, "title": chapter.title},
        "修订后的摘要",
    )
    conflict = await repository.update_chapter_consistently(
        tenant_id,
        novel_id,
        chapter,
        1,
        chapter.content,
        {"type": "chapter", "chapter_index": 0},
        "不应写入的摘要",
    )

    assert saved is not None and saved.version == 2
    assert conflict is None
    novel = await repository.find_by_id(tenant_id, novel_id)
    assert novel is not None
    assert novel.progress.checkpoint_sync == {
        "next_index": 1,
        "discard_from_index": 1,
        "is_completed": False,
    }
    async with repository.async_session() as session:
        memories = (
            await session.execute(
                select(MemoryModel).where(MemoryModel.novel_id == chapter.novel_id)
            )
        ).scalars().all()
    memory_types = {item.meta_data["type"] for item in memories}
    assert memory_types == {"chapter", "chapter_summary"}
    assert any(item.content == "修订后的正文内容" for item in memories)


@pytest.mark.asyncio
async def test_chapter_rewind_removes_following_chapters_and_memories(
    repository, tenant_context, sample_novel_with_outline
):
    tenant_id = str(tenant_context.tenant_id)
    novel_id = str(sample_novel_with_outline.id)
    await repository.save(tenant_id, sample_novel_with_outline)
    chapters = [
        await _store_chapter(repository, tenant_id, novel_id, index)
        for index in range(4)
    ]

    deleted, rewind_to = await repository.rewind_chapters_atomically(
        tenant_id, novel_id, [str(chapters[1].id)]
    )

    novel = await repository.find_by_id_with_chapters(tenant_id, novel_id)
    assert deleted == 3
    assert rewind_to == 1
    assert novel is not None and novel.progress.current_chapter == 1
    assert novel.progress.checkpoint_sync == {
        "next_index": 1,
        "discard_from_index": 1,
        "is_completed": False,
    }
    assert [chapter.chapter_index for chapter in novel.chapters] == [0]
    async with repository.async_session() as session:
        memories = (
            await session.execute(
                select(MemoryModel).where(
                    MemoryModel.novel_id == sample_novel_with_outline.id
                )
            )
        ).scalars().all()
    assert {item.meta_data["type"] for item in memories} == {
        "chapter",
        "chapter_summary",
    }
    assert all(item.meta_data.get("chapter_index") == 0 for item in memories)
