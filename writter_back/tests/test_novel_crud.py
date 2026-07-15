"""PostgreSQL integration tests for tenant-scoped novel access."""

from uuid import uuid4

import pytest


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
async def test_outline_round_trip(repository, tenant_context, sample_novel_with_outline):
    await repository.save(str(tenant_context.tenant_id), sample_novel_with_outline)
    saved = await repository.find_by_id(
        str(tenant_context.tenant_id), str(sample_novel_with_outline.id)
    )
    assert saved is not None
    assert saved.total_outline is not None
    assert saved.total_outline.story_background == "一个发生在封闭别墅的谋杀案"
