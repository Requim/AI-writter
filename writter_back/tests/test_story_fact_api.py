"""事实台账真实 API：租户隔离、预览无写入、确认幂等与并发冲突。"""
import pytest


async def seed(client, repository, tenant_context, sample_novel):
    await repository.save(str(tenant_context.tenant_id), sample_novel)
    base = f"/api/v1/novels/{sample_novel.id}/facts"
    result = await client.post(base + "/entities", json={"entity_key": "hero", "kind": "character", "name": "辛远"})
    assert result.status_code == 200
    change = {"subject_id": result.json()["id"], "predicate": "surname", "value_text": "辛", "expected_version": 0,
        "valid_from_chapter": 1, "status": "confirmed", "reason": "作者核对族谱"}
    return base, change


@pytest.mark.asyncio
async def test_preview_confirm_history_and_repeated_confirmation(async_client, repository, tenant_context, sample_novel):
    base, change = await seed(async_client, repository, tenant_context, sample_novel)
    preview = await async_client.post(base + "/proposals", json=change)
    assert preview.status_code == 200
    assert (await async_client.get(base)).json()["fact_heads"] == []
    token = {"token": preview.json()["token"]}
    saved = await async_client.post(base + "/confirm", json=token)
    assert saved.status_code == 200 and saved.json()["version"] == 1
    assert (await async_client.post(base + "/confirm", json=token)).json()["id"] == saved.json()["id"]
    history = await async_client.get(base + "/history/" + change["subject_id"] + "/surname")
    assert len(history.json()) == 1


@pytest.mark.asyncio
async def test_competing_proposals_only_one_version_wins(async_client, repository, tenant_context, sample_novel):
    base, change = await seed(async_client, repository, tenant_context, sample_novel)
    first = (await async_client.post(base + "/proposals", json=change)).json()
    second = (await async_client.post(base + "/proposals", json={**change, "value_text": "陆"})).json()
    assert (await async_client.post(base + "/confirm", json={"token": first["token"]})).status_code == 200
    assert (await async_client.post(base + "/confirm", json={"token": second["token"]})).status_code == 409
    assert (await async_client.get(base)).json()["fact_heads"][0]["value_text"] == "辛"


@pytest.mark.asyncio
async def test_other_tenant_cannot_read_or_confirm(async_client, repository, tenant_context, sample_novel, other_tenant_context):
    from api.main import app
    from api.dependencies import get_tenant_context
    base, change = await seed(async_client, repository, tenant_context, sample_novel)
    preview = (await async_client.post(base + "/proposals", json=change)).json()
    app.dependency_overrides[get_tenant_context] = lambda: other_tenant_context
    assert (await async_client.get(base)).status_code == 404
    assert (await async_client.post(base + "/confirm", json={"token": preview["token"]})).status_code == 404


@pytest.mark.asyncio
async def test_invalid_relation_kind_is_not_previewed(async_client, repository, tenant_context, sample_novel):
    base, change = await seed(async_client, repository, tenant_context, sample_novel)
    result = await async_client.post(base + "/proposals", json={**change, "predicate": "family", "value_text": None,
        "object_entity_id": change["subject_id"]})
    assert result.status_code == 422
