"""Exports include only this tenant's archived, unmodified chapters."""

import pytest

from api.dependencies import get_tenant_context
from api.main import app
from tests.test_novel_crud import _store_chapter


@pytest.mark.asyncio
async def test_export_preserves_archived_prose_in_chapter_order(
    async_client, repository, tenant_context, sample_novel_with_outline,
):
    novel = sample_novel_with_outline
    await repository.save(str(tenant_context.tenant_id), novel)
    for index in (1, 0):
        await _store_chapter(repository, str(tenant_context.tenant_id), str(novel.id), index)
    response = await async_client.get(f"/api/v1/novels/{novel.id}/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "attachment;" in response.headers["content-disposition"]
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert response.text.index("第1章正文") < response.text.index("第2章正文")
    assert "测试悬疑小说" in response.text
    assert "第1章正文" in response.text and "第2章正文" in response.text


@pytest.mark.asyncio
async def test_export_is_tenant_scoped(
    async_client, repository, tenant_context, other_tenant_context, sample_novel,
):
    await repository.save(str(tenant_context.tenant_id), sample_novel)
    app.dependency_overrides[get_tenant_context] = lambda: other_tenant_context
    response = await async_client.get(f"/api/v1/novels/{sample_novel.id}/export")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_empty_book_cannot_be_downloaded_as_a_complete_manuscript(
    async_client, repository, tenant_context, sample_novel,
):
    await repository.save(str(tenant_context.tenant_id), sample_novel)
    response = await async_client.get(f"/api/v1/novels/{sample_novel.id}/export")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no_archived_chapters"


@pytest.mark.asyncio
async def test_markdown_export_keeps_original_content(
    async_client, repository, tenant_context, sample_novel_with_outline,
):
    novel = sample_novel_with_outline
    await repository.save(str(tenant_context.tenant_id), novel)
    await _store_chapter(repository, str(tenant_context.tenant_id), str(novel.id), 0)
    response = await async_client.get(f"/api/v1/novels/{novel.id}/export?format=md")
    assert response.status_code == 200
    assert "# 测试悬疑小说" in response.text
    assert "## 第1章" in response.text
    assert "第1章正文" in response.text


@pytest.mark.asyncio
async def test_export_rejects_unknown_format(async_client, sample_novel):
    response = await async_client.get(f"/api/v1/novels/{sample_novel.id}/export?format=html")
    assert response.status_code == 422
