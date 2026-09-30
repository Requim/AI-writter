"""独立PostgreSQL上的会话、CAS、预算重启与租户边界验收。"""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select

from application.creative.errors import CreativeConflict, CreativePause
from infrastructure.database.creative_repository import PostgresCreativeRepository
from infrastructure.database.models import TenantModel
from service.value_objects.creative import AuthorConfiguration, BudgetLimits, CreativeRecord
from service.value_objects.outline import Outline


async def seed_creative(repository, context, novel, monkeypatch):
    monkeypatch.setattr("config.settings.AUTONOMOUS_AUTHOR_ENABLED", True)
    monkeypatch.setattr("config.settings.NOVEL_PLANNING_V1_ENABLED", True)
    async with repository.async_session() as session, session.begin():
        tenant = await session.get(TenantModel, context.tenant_id)
        tenant.autonomous_author_enabled = True
        tenant.novel_planning_v1_enabled = True
    config = AuthorConfiguration(budget=BudgetLimits(preparation=1)).model_dump(mode="json")
    novel.total_outline = Outline(total_chapters=6, author_config=config)
    await repository.save(str(context.tenant_id), novel)
    return PostgresCreativeRepository(repository.async_session), str(context.tenant_id), str(novel.id)


@pytest.mark.asyncio
async def test_creative_budget_survives_repository_restart(repository, tenant_context, sample_novel, monkeypatch):
    creative, tenant, novel = await seed_creative(repository, tenant_context, sample_novel, monkeypatch)
    await creative.reserve(tenant, novel, "preparation", "candidate")
    restarted = PostgresCreativeRepository(repository.async_session)
    assert (await restarted.get_session(tenant, novel))["counters"]["preparation"] == 1
    with pytest.raises(CreativePause, match="预算"):
        await restarted.reserve(tenant, novel, "preparation", "candidate_retry")


@pytest.mark.asyncio
async def test_creative_records_are_cas_idempotent_and_tenant_scoped(repository, tenant_context, sample_novel, other_tenant_context, monkeypatch):
    creative, tenant, novel = await seed_creative(repository, tenant_context, sample_novel, monkeypatch)
    record = CreativeRecord(kind="decision", key="turn", payload={"route": "one"}, source="system")
    first = await creative.put(tenant, novel, record, expected_version=0, idempotency_key="first")
    second = await creative.put(tenant, novel, record, expected_version=0, idempotency_key="first")
    assert first["id"] == second["id"]
    with pytest.raises(CreativeConflict):
        await creative.put(tenant, novel, record, expected_version=0, idempotency_key="stale")
    other = str(other_tenant_context.tenant_id)
    assert await creative.get_session(other, novel) is None
    assert await creative.records(other, novel) == []
    with pytest.raises(LookupError):
        await creative.put(other, novel, record, expected_version=0, idempotency_key="cross")


@pytest.mark.asyncio
async def test_concurrent_budget_reservations_cannot_overspend(repository, tenant_context, sample_novel, monkeypatch):
    creative, tenant, novel = await seed_creative(repository, tenant_context, sample_novel, monkeypatch)
    outcomes = await asyncio.gather(
        creative.reserve(tenant, novel, "preparation", "a"),
        creative.reserve(tenant, novel, "preparation", "b"), return_exceptions=True,
    )
    assert sum(isinstance(value, CreativePause) for value in outcomes) == 1
    assert sum(isinstance(value, str) for value in outcomes) == 1


@pytest.mark.asyncio
async def test_default_off_rejects_new_autonomous_session(repository, tenant_context, sample_novel, monkeypatch):
    monkeypatch.setattr("config.settings.AUTONOMOUS_AUTHOR_ENABLED", False)
    sample_novel.total_outline = Outline(total_chapters=6, author_config=AuthorConfiguration().model_dump(mode="json"))
    with pytest.raises(CreativePause, match="开放"):
        await repository.save(str(tenant_context.tenant_id), sample_novel)
    assert await repository.find_by_id(str(tenant_context.tenant_id), str(sample_novel.id)) is None
