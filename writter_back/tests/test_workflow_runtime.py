"""真实PostgreSQL双执行者、过期写入与持久重放回归。"""
import asyncio
from datetime import timedelta
import pytest
from sqlalchemy import select, func
from application.execution_fence import execution_fence, ExecutionLeaseLost
from application.events import WorkflowEvent
from infrastructure.command_store.postgres_command_store import PostgresWorkflowCommandStore
from infrastructure.database.runtime_models import WorkflowLeaseModel, WorkflowRunModel
from infrastructure.database.runtime_journal import RuntimeJournal
from infrastructure.database.repository import _lock_novel
from service.ports.workflow_command_store import WorkflowCommandClaimStatus as Status
from infrastructure.database.fenced_checkpointer import FencedPostgresSaver
from infrastructure.database.runtime_models import WorkflowArtifactModel
from tests.database_safety import isolated_database_url
from psycopg import AsyncConnection
from langgraph.checkpoint.base import empty_checkpoint
from api.main import app
from api.dependencies import get_tenant_context


async def seed(repository, context, novel):
    await repository.save(str(context.tenant_id), novel)
    return PostgresWorkflowCommandStore(repository.async_session), str(context.tenant_id), str(novel.id)


@pytest.mark.asyncio
async def test_different_commands_share_novel_lease(repository, tenant_context, sample_novel):
    first, tenant, novel = await seed(repository, tenant_context, sample_novel)
    second = PostgresWorkflowCommandStore(repository.async_session)
    claims = await asyncio.gather(first.claim(tenant, novel, 'a', 300), second.claim(tenant, novel, 'b', 300))
    assert sorted(claim.status for claim in claims) == sorted([Status.ACQUIRED, Status.IN_PROGRESS])


@pytest.mark.asyncio
async def test_expired_owner_cannot_write_after_takeover(repository, tenant_context, sample_novel):
    first, tenant, novel = await seed(repository, tenant_context, sample_novel)
    claim = await first.claim(tenant, novel, 'command', 300)
    old_owner = first.owners[claim.lease_token]
    async with repository.async_session() as session, session.begin():
        lease = await session.get(WorkflowLeaseModel, (tenant_context.tenant_id, sample_novel.id))
        lease.expires_at = (await session.scalar(select(func.now()))) - timedelta(seconds=1)
    second = PostgresWorkflowCommandStore(repository.async_session)
    next_claim = await second.claim(tenant, novel, 'command', 300)
    assert next_claim.status == Status.ACQUIRED
    token = execution_fence.set(old_owner)
    try:
        async with repository.async_session() as session, session.begin():
            with pytest.raises(ExecutionLeaseLost):
                await _lock_novel(session, tenant_context.tenant_id, sample_novel.id)
    finally:
        execution_fence.reset(token)
    assert not await first.finalize(tenant, novel, 'command', claim.lease_token, 100)
    assert await second.finalize(tenant, novel, 'command', next_claim.lease_token, 100)
    assert (await first.claim(tenant, novel, 'command', 300)).status == Status.ALREADY_APPLIED


@pytest.mark.asyncio
async def test_events_survive_store_restart_and_are_tenant_scoped(repository, tenant_context, sample_novel, other_tenant_context):
    store, tenant, novel = await seed(repository, tenant_context, sample_novel)
    claim = await store.claim(tenant, novel, 'a', 300)
    journal = RuntimeJournal(repository.async_session)
    owner = store.owners[claim.lease_token]
    for kind in ['status', 'content_delta', 'interrupt']:
        await journal.append(owner, WorkflowEvent(id=999, type=kind, thread_id=novel, data={'message': 'synthetic'}))
    restarted = RuntimeJournal(repository.async_session)
    assert [event.id for event in await restarted.read(tenant, novel, 1)] == [2, 3]
    assert await restarted.read(str(other_tenant_context.tenant_id), novel, 0) == []
    assert await store.finalize(tenant, novel, 'a', claim.lease_token, 100)
    assert not (await restarted.status(tenant, novel))['running']


@pytest.mark.asyncio
async def test_startup_recovers_only_expired_runs(repository, tenant_context, sample_novel):
    store, tenant, novel = await seed(repository, tenant_context, sample_novel)
    claim = await store.claim(tenant, novel, 'a', 300)
    assert await store.recover_expired() == 0
    assert await store.cancel(tenant, novel)
    assert not await store.renew(store.owners[claim.lease_token])
    async with repository.async_session() as session, session.begin():
        lease = await session.get(WorkflowLeaseModel, (tenant_context.tenant_id, sample_novel.id))
        lease.expires_at = (await session.scalar(select(func.now()))) - timedelta(seconds=1)
    assert await store.recover_expired() == 1
    async with repository.async_session() as session:
        run = await session.get(WorkflowRunModel, store.owners[claim.lease_token].run_id)
        assert run.status == 'orphaned'


@pytest.mark.asyncio
async def test_postgres_checkpoint_writes_are_fenced_and_linked(repository, tenant_context, sample_novel):
    store, tenant, novel = await seed(repository, tenant_context, sample_novel)
    url = isolated_database_url().replace('postgresql+asyncpg://', 'postgresql://')
    async with await AsyncConnection.connect(url, autocommit=True) as connection:
        saver = FencedPostgresSaver(connection)
        await saver.setup()
        claim = await store.claim(tenant, novel, 'checkpoint', 300)
        owner = store.owners[claim.lease_token]
        token = execution_fence.set(owner)
        try:
            await saver.aput({'configurable': {'thread_id': novel, 'checkpoint_ns': ''}}, empty_checkpoint(), {'source': 'input', 'step': 0}, {})
            async with repository.async_session() as session:
                artifacts = (await session.scalars(select(WorkflowArtifactModel).where(WorkflowArtifactModel.run_id == owner.run_id))).all()
                assert len(artifacts) == 1 and artifacts[0].checkpoint_id
            async with repository.async_session() as session, session.begin():
                lease = await session.get(WorkflowLeaseModel, (tenant_context.tenant_id, sample_novel.id))
                lease.expires_at = (await session.scalar(select(func.now()))) - timedelta(seconds=1)
            with pytest.raises(ExecutionLeaseLost):
                await saver.aput({'configurable': {'thread_id': novel, 'checkpoint_ns': ''}}, empty_checkpoint(), {'source': 'input', 'step': 1}, {})
        finally:
            execution_fence.reset(token)


@pytest.mark.asyncio
async def test_replay_api_uses_cursor_and_enforces_tenant(async_client, repository, tenant_context, sample_novel, other_tenant_context):
    store, tenant, novel = await seed(repository, tenant_context, sample_novel)
    claim = await store.claim(tenant, novel, 'api', 300)
    owner = store.owners[claim.lease_token]
    journal = RuntimeJournal(repository.async_session)
    await journal.append(owner, WorkflowEvent(id=99, type='status', thread_id=novel, data={}))
    await journal.append(owner, WorkflowEvent(id=99, type='completed', thread_id=novel, data={}))
    await store.finalize(tenant, novel, 'api', claim.lease_token, 300)
    response = await async_client.get(f'/api/v1/workflows/{novel}/events', headers={'Last-Event-ID': '1'})
    assert response.status_code == 200 and 'id: 2' in response.text and 'id: 1' not in response.text
    assert (await async_client.get(f'/api/v1/workflows/{novel}/events', headers={'Last-Event-ID': '-1'})).status_code == 422
    app.dependency_overrides[get_tenant_context] = lambda: other_tenant_context
    assert (await async_client.get(f'/api/v1/workflows/{novel}/events')).status_code == 404
