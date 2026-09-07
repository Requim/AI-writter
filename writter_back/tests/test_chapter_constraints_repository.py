"""真实 PostgreSQL 验证快照读取、失效和事务锁生命周期。"""

import asyncio
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from infrastructure.database.models import NovelModel
from infrastructure.database.story_fact_repository import PostgresStoryFactRepository
from service.ports.story_fact_repository import FactVersionConflictError
from service.value_objects.story_fact import StoryEntity
from tests.test_story_fact_repository import _person, _surname


@pytest_asyncio.fixture
async def ledger(repository, tenant_context, sample_novel):
    await repository.save(str(tenant_context.tenant_id), sample_novel)
    return PostgresStoryFactRepository(repository.async_session), str(tenant_context.tenant_id), str(sample_novel.id)


@pytest.mark.asyncio
async def test_capture_scope_and_empty_state(ledger, other_tenant_context):
    store, tenant, novel = ledger
    empty = await store.capture_constraints(tenant, novel, 1)
    assert not empty.entities and not empty.fact_heads
    with pytest.raises(ValueError, match="不可访问"):
        await store.capture_constraints(str(other_tenant_context.tenant_id), novel, 1)
    async with store.async_session() as session, session.begin():
        await store.assert_constraints_current(session, tenant, novel, 1, empty)
    async with store.async_session() as session:
        with pytest.raises(ValueError, match="事务"):
            await store.assert_constraints_current(session, tenant, novel, 1, empty)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["new_fact", "new_entity", "correction", "retraction"])
async def test_snapshot_invalidated_by_any_ledger_change(ledger, change):
    store, tenant, novel = ledger
    person = await _person(ledger)
    if change in {"correction", "retraction"}:
        await store.append_fact(tenant, novel, _surname(person), expected_version=0, idempotency_key="initial")
    snapshot = await store.capture_constraints(tenant, novel, 2)
    if change == "new_entity":
        await store.ensure_entity(tenant, novel, StoryEntity(entity_key="other", kind="family", name="陆家"))
    else:
        status = "retracted" if change == "retraction" else "confirmed"
        await store.append_fact(tenant, novel, _surname(person, "陆", status=status),
            expected_version=0 if change == "new_fact" else 1, idempotency_key="change")
    async with store.async_session() as session, session.begin():
        with pytest.raises(FactVersionConflictError, match="已变化"):
            await store.assert_constraints_current(session, tenant, novel, 2, snapshot)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["tenant_id", "novel_id", "chapter_number"])
async def test_revalidation_rejects_snapshot_scope_mismatch(ledger, field):
    store, tenant, novel = ledger
    snapshot = await store.capture_constraints(tenant, novel, 1)
    changed = snapshot.model_copy(update={field: 2 if field == "chapter_number" else uuid4()})
    async with store.async_session() as session, session.begin():
        with pytest.raises(FactVersionConflictError, match="不匹配"):
            await store.assert_constraints_current(session, tenant, novel, 1, changed)


@pytest.mark.asyncio
async def test_guard_rollback_preserves_novel_and_retry_is_current(ledger):
    store, tenant, novel = ledger
    person = await _person(ledger)
    snapshot = await store.capture_constraints(tenant, novel, 1)
    await store.append_fact(tenant, novel, _surname(person), expected_version=0, idempotency_key="new")
    async with store.async_session() as session:
        before = await session.scalar(select(NovelModel.title).where(NovelModel.id == snapshot.novel_id))
    with pytest.raises(FactVersionConflictError):
        async with store.async_session() as session, session.begin():
            row = await session.get(NovelModel, snapshot.novel_id)
            row.title = "不应保存的标题"
            await store.assert_constraints_current(session, tenant, novel, 1, snapshot)
    async with store.async_session() as session:
        assert await session.scalar(select(NovelModel.title).where(NovelModel.id == snapshot.novel_id)) == before
    fresh = await store.capture_constraints(tenant, novel, 1)
    async with store.async_session() as session, session.begin():
        await store.assert_constraints_current(session, tenant, novel, 1, fresh)


@pytest.mark.asyncio
async def test_guard_holds_novel_lock_until_caller_transaction_ends(ledger):
    store, tenant, novel = ledger
    person = await _person(ledger)
    snapshot = await store.capture_constraints(tenant, novel, 1)
    async with store.async_session() as session, session.begin():
        await store.assert_constraints_current(session, tenant, novel, 1, snapshot)
        async with store.async_session() as other, other.begin():
            await other.execute(text("SET LOCAL lock_timeout = '200ms'"))
            with pytest.raises(DBAPIError):
                await other.execute(select(NovelModel.id).where(NovelModel.id == snapshot.novel_id).with_for_update())
    appended = await asyncio.wait_for(store.append_fact(tenant, novel, _surname(person),
        expected_version=0, idempotency_key="after-release"), timeout=10)
    assert appended.version == 1


@pytest.mark.asyncio
async def test_repeatable_read_cannot_reuse_old_database_snapshot(ledger):
    store, tenant, novel = ledger
    snapshot = await store.capture_constraints(tenant, novel, 1)
    async with store.async_session() as session, session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        with pytest.raises(ValueError, match="READ COMMITTED"):
            await store.assert_constraints_current(session, tenant, novel, 1, snapshot)
