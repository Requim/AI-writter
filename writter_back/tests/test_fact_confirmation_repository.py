"""可信确认批次的事务、幂等和权限集成测试。"""

import asyncio
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from application.story_facts import compile_character_surnames
from infrastructure.database.story_fact_repository import PostgresStoryFactRepository
from service.ports.story_fact_repository import FactVersionConflictError


@pytest_asyncio.fixture
async def ledger(repository, tenant_context, sample_novel):
    await repository.save(str(tenant_context.tenant_id), sample_novel)
    return PostgresStoryFactRepository(repository.async_session), str(tenant_context.tenant_id), str(sample_novel.id)


def batch(novel, surname="辛", source="approval-1", characters=None):
    design = {"characters": characters or [{"character_id": "hero", "name": "辛远", "surname": surname}]}
    return compile_character_surnames(UUID(novel), design, source_ref=source, source_version=1, confirmed=True)


@pytest.mark.asyncio
async def test_confirmed_batch_concurrent_retry_and_new_approval_preserve_history(ledger):
    store, tenant, novel = ledger
    entities, facts = batch(novel)
    results = await asyncio.gather(*(store.ingest_confirmed_facts(tenant, novel, entities, facts,
        source_key="approval-1") for _ in range(2)))
    assert results[0] == results[1]
    _, same = batch(novel, source="approval-2")
    assert await store.ingest_confirmed_facts(tenant, novel, entities, same, source_key="approval-2") == results[0]
    assert len(await store.list_history(tenant, novel, entities[0].id, "surname")) == 1
    snapshot = await store.capture_constraints(tenant, novel, 1)
    assert len(snapshot.active_facts) == 1
    assert snapshot.active_facts[0].evidence.source_ref == "approval-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["changed_surname", "missing_reference", "retracted"])
async def test_partial_batch_never_survives_a_late_conflict(ledger, case):
    store, tenant, novel = ledger
    original_entities, original_facts = batch(novel)
    await store.ingest_confirmed_facts(tenant, novel, original_entities, original_facts, source_key="initial")
    entities, facts = batch(novel, source="second", characters=[
        {"character_id": "new", "name": "陆青", "surname": "陆"},
        {"character_id": "hero", "name": "辛远", "surname": "陆"},
    ])
    if case == "missing_reference":
        facts[1] = facts[1].model_copy(update={"subject_id": uuid4()})
    if case == "retracted":
        facts[1] = facts[1].model_copy(update={"status": "retracted"})
    with pytest.raises(ValueError):
        await store.ingest_confirmed_facts(tenant, novel, entities, facts, source_key="second")
    assert await store.list_entities(tenant, novel) == original_entities
    assert len(await store.list_current(tenant, novel)) == 1


@pytest.mark.asyncio
async def test_scope_and_changed_confirmation_key_are_rejected(ledger, other_tenant_context):
    store, tenant, novel = ledger
    entities, facts = batch(novel)
    with pytest.raises(ValueError, match="不可访问"):
        await store.ingest_confirmed_facts(str(other_tenant_context.tenant_id), novel, entities, facts, source_key="foreign")
    await store.ingest_confirmed_facts(tenant, novel, entities, facts, source_key="original")
    _, changed = batch(novel, source="different-source")
    with pytest.raises(FactVersionConflictError, match="来源"):
        await store.ingest_confirmed_facts(tenant, novel, entities, changed, source_key="original")
    with pytest.raises(ValueError, match="重复"):
        await store.ingest_confirmed_facts(tenant, novel, entities, facts * 2, source_key="duplicates")
