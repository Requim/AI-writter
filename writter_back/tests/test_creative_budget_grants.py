"""Operator grants extend one existing book, never tenant defaults or counters."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from application.creative.errors import CreativePause
from infrastructure.database.creative_repository import PostgresCreativeRepository
from infrastructure.database.models import TenantModel
from service.entities.novel import Novel
from service.value_objects.creative import AuthorConfiguration, BudgetLimits, CreativeRecord
from service.value_objects.outline import Outline


async def seed_book(repository, context, novel, monkeypatch):
    monkeypatch.setattr("config.settings.AUTONOMOUS_AUTHOR_ENABLED", True)
    monkeypatch.setattr("config.settings.NOVEL_PLANNING_V1_ENABLED", True)
    async with repository.async_session() as session, session.begin():
        tenant = await session.get(TenantModel, context.tenant_id)
        tenant.autonomous_author_enabled = True
        tenant.novel_planning_v1_enabled = True
    novel.total_outline = Outline(total_chapters=3, author_config=AuthorConfiguration(
        budget=BudgetLimits(search=0, preparation_search=0),
    ).model_dump(mode="json"))
    await repository.save(str(context.tenant_id), novel)
    return PostgresCreativeRepository(repository.async_session)


async def grant(creative, context, novel, *, source="system", status="authorized", payload=None):
    return await creative.put(str(context.tenant_id), str(novel.id), CreativeRecord(
        kind="control", key="operator_chapter_budget", source=source, status=status,
        payload=payload if payload is not None else {
            "chapter_limit": 48, "authorization": "User approved this book only.",
        },
    ), expected_version=0, idempotency_key="operator-grant")


def update_payload(chapter=48, version=1):
    return {"expected_version": version, "limits": {
        "preparation": 60, "chapter": chapter, "review": 44,
        "search": 0, "preparation_search": 0,
    }}


@pytest.mark.asyncio
async def test_authorized_extension_preserves_consumption_and_enforces_new_cap(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    for _ in range(32):
        await creative.reserve(tenant, novel, "chapter:2", "reflection_node")
    await creative.reserve(tenant, novel, "preparation", "creative_development_node")
    with pytest.raises(CreativePause, match="预算"):
        await creative.reserve(tenant, novel, "chapter:2", "reflection_node")
    await grant(creative, tenant_context, sample_novel)
    response = await async_client.put(f"/api/v1/novels/{novel}/creative/budget",
                                     json=update_payload(), headers={"Idempotency-Key": "extend"})
    assert response.status_code == 200, response.text
    assert response.json()["limits"] == {
        "preparation": 60, "chapter": 48, "review": 44, "search": 0,
        "preparation_search": 0, "total": 248, "chapters": 3,
    }
    assert response.json()["counters"] == {"chapter:2": 32, "preparation": 1}
    for _ in range(16):
        await creative.reserve(tenant, novel, "chapter:2", "reflection_node")
    with pytest.raises(CreativePause, match="预算"):
        await creative.reserve(tenant, novel, "chapter:2", "reflection_node")
    replay = await async_client.put(f"/api/v1/novels/{novel}/creative/budget",
                                   json=update_payload(), headers={"Idempotency-Key": "extend"})
    assert replay.status_code == 200 and replay.json() == response.json()
    saved = await creative.get_session(tenant, novel)
    assert saved["counters"] == {"chapter:2": 48, "preparation": 1}
    assert saved["config"]["budget"]["chapter"] == 48
    stale = await async_client.put(f"/api/v1/novels/{novel}/creative/budget",
                                  json=update_payload(), headers={"Idempotency-Key": "stale"})
    assert stale.status_code == 409


@pytest.mark.asyncio
async def test_client_cannot_grant_itself_extra_requests(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    novel = str(sample_novel.id)
    before = await creative.get_session(str(tenant_context.tenant_id), novel)
    response = await async_client.put(f"/api/v1/novels/{novel}/creative/budget",
                                     json={**update_payload(), "grant": {"chapter_limit": 48}},
                                     headers={"Idempotency-Key": "unapproved"})
    assert response.status_code == 422
    assert await creative.get_session(str(tenant_context.tenant_id), novel) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("source,status", [
    ("author", "authorized"), ("model", "authorized"),
    ("human_reader", "authorized"), ("system", "revoked"),
])
async def test_only_authorized_operator_record_grants_extra_requests(
    async_client, repository, tenant_context, sample_novel, monkeypatch, source, status,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    await grant(creative, tenant_context, sample_novel, source=source, status=status)
    response = await async_client.put(f"/api/v1/novels/{sample_novel.id}/creative/budget",
                                     json=update_payload(), headers={"Idempotency-Key": "rejected"})
    assert response.status_code == 422
    assert (await creative.get_session(str(tenant_context.tenant_id), str(sample_novel.id)))["limits"]["chapter"] == 32


@pytest.mark.asyncio
async def test_grant_does_not_extend_another_book_or_tenant(
    async_client, repository, tenant_context, other_tenant_context, sample_novel, monkeypatch,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    await grant(creative, tenant_context, sample_novel)
    second = Novel(id=uuid4(), tenant_id=tenant_context.tenant_id,
                   user_id=tenant_context.user_id, novel_type="suspense", title="Another book")
    await seed_book(repository, tenant_context, second, monkeypatch)
    response = await async_client.put(f"/api/v1/novels/{second.id}/creative/budget",
                                     json=update_payload(), headers={"Idempotency-Key": "other-book"})
    assert response.status_code == 422
    outsider = Novel(id=uuid4(), tenant_id=other_tenant_context.tenant_id,
                     user_id=other_tenant_context.user_id, novel_type="suspense", title="Other tenant")
    await seed_book(repository, other_tenant_context, outsider, monkeypatch)
    response = await async_client.put(f"/api/v1/novels/{outsider.id}/creative/budget",
                                     json=update_payload(), headers={"Idempotency-Key": "other-tenant"})
    assert response.status_code == 422
    assert (await creative.get_session(str(other_tenant_context.tenant_id), str(outsider.id)))["limits"]["chapter"] == 32


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"chapter_limit": "48", "authorization": "Approved"},
    {"chapter_limit": 49, "authorization": "Approved"},
    {"chapter_limit": 48, "authorization": ""},
    {"chapter_limit": 48, "authorization": "Approved", "unlimited": True},
])
async def test_invalid_operator_grant_fails_closed(
    async_client, repository, tenant_context, sample_novel, monkeypatch, payload,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    await grant(creative, tenant_context, sample_novel, payload=payload)
    response = await async_client.put(f"/api/v1/novels/{sample_novel.id}/creative/budget",
                                     json=update_payload(), headers={"Idempotency-Key": "invalid-grant"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_requested_limit_cannot_exceed_exact_operator_allowance(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    await grant(creative, tenant_context, sample_novel, payload={
        "chapter_limit": 40, "authorization": "Only forty requests approved.",
    })
    response = await async_client.put(f"/api/v1/novels/{sample_novel.id}/creative/budget",
                                     json=update_payload(), headers={"Idempotency-Key": "too-many"})
    assert response.status_code == 422
    response = await async_client.put(f"/api/v1/novels/{sample_novel.id}/creative/budget",
                                     json=update_payload(40), headers={"Idempotency-Key": "allowed"})
    assert response.status_code == 200
    assert response.json()["limits"]["total"] == 224


@pytest.mark.asyncio
async def test_extension_respects_existing_tenant_total_request_limit(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    await grant(creative, tenant_context, sample_novel)
    async with repository.async_session() as session, session.begin():
        tenant = await session.get(TenantModel, tenant_context.tenant_id)
        tenant.autonomous_request_limit = 200
    response = await async_client.put(f"/api/v1/novels/{sample_novel.id}/creative/budget",
                                     json=update_payload(), headers={"Idempotency-Key": "tenant-cap"})
    assert response.status_code == 422
    assert (await creative.get_session(str(tenant_context.tenant_id), str(sample_novel.id)))["limits"]["total"] == 200


def test_new_book_configuration_keeps_original_chapter_cap():
    assert AuthorConfiguration().budget.chapter == 32
    with pytest.raises(ValidationError):
        AuthorConfiguration(budget={"chapter": 48})


@pytest.mark.asyncio
async def test_authorized_book_still_rejects_requests_above_absolute_cap(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    await grant(creative, tenant_context, sample_novel)
    response = await async_client.put(f"/api/v1/novels/{sample_novel.id}/creative/budget",
                                     json=update_payload(49), headers={"Idempotency-Key": "above-cap"})
    assert response.status_code == 422
    assert (await creative.get_session(str(tenant_context.tenant_id), str(sample_novel.id)))["limits"]["chapter"] == 32


@pytest.mark.asyncio
async def test_budget_reduction_cannot_erase_existing_consumption(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    for _ in range(3):
        await creative.reserve(tenant, novel, "chapter:2", "reflection_node")
    before = await creative.get_session(tenant, novel)
    response = await async_client.put(f"/api/v1/novels/{novel}/creative/budget",
                                     json=update_payload(2), headers={"Idempotency-Key": "too-small"})
    assert response.status_code == 422
    assert await creative.get_session(tenant, novel) == before


@pytest.mark.asyncio
async def test_latest_revocation_does_not_fall_back_to_old_authorization(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    await grant(creative, tenant_context, sample_novel)
    await creative.put(str(tenant_context.tenant_id), str(sample_novel.id), CreativeRecord(
        kind="control", key="operator_chapter_budget", source="system", status="revoked",
        payload={"chapter_limit": 48, "authorization": "Operator revoked the earlier grant."},
    ), expected_version=1, idempotency_key="revoke-grant")
    response = await async_client.put(f"/api/v1/novels/{sample_novel.id}/creative/budget",
                                     json=update_payload(), headers={"Idempotency-Key": "revoked-v2"})
    assert response.status_code == 422
    assert (await creative.get_session(str(tenant_context.tenant_id), str(sample_novel.id)))["limits"]["chapter"] == 32
