"""Process lifecycle recovery retains fences, cancellation and current authority."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete

from api.routers import workflow_router as routes
from api.workflow_commands import ClaimedWorkflowCommand
from application.events import WorkflowEvent
from application.orchestrator import NovelOrchestrator
from application.quota_service import QuotaService
from infrastructure.database.identity_repository import IdentityRepository
from infrastructure.database.models import TenantMembershipModel
from infrastructure.database.runtime_journal import RuntimeJournal
from tests.test_workflow_runtime import seed


def recovery(context, **overrides):
    return {"user_id": str(context.user_id), "restarts": 0,
            "deadline": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "input_data": {"workflow_run_id": "saved-quota-identity"}, **overrides}


def orchestrator(repository, monkeypatch):
    instance = NovelOrchestrator(repository, AsyncMock(), {})
    monkeypatch.setattr(instance, "get_workflow_schema_version", AsyncMock(return_value=2))
    monkeypatch.setattr(instance, "get_public_state", AsyncMock(
        return_value={"interrupts": [], "next_nodes": ["review"]}))
    monkeypatch.setattr(instance, "get_workflow_run_id", AsyncMock(return_value="saved-quota-identity"))
    monkeypatch.setattr(routes, "_ensure_checkpoint_ready", AsyncMock())
    return instance


def service(store, repository, instance):
    from application.automatic_restart import AutomaticRestartService
    identity = IdentityRepository(repository.async_session)
    return AutomaticRestartService(store, repository, identity, instance, QuotaService(identity))


@pytest.mark.asyncio
async def test_restart_reloads_authority_and_schedules_checkpoint_once(
    repository, tenant_context, sample_novel, monkeypatch,
):
    store, tenant, novel = await seed(repository, tenant_context, sample_novel)
    claim = await store.claim(tenant, novel, "original", 300)
    await store.set_recovery(claim.lease_token, recovery(tenant_context))
    await store.release_for_restart(tenant, novel, "original", claim.lease_token)
    instance = orchestrator(repository, monkeypatch)
    observed = []

    async def stream(context, thread, **kwargs):
        observed.append((context.user_id, kwargs["is_retry"], kwargs.get("is_restart")))
        yield WorkflowEvent(id=1, type="completed", thread_id=thread, data={})

    monkeypatch.setattr(instance, "stream_events", stream)
    worker = service(store, repository, instance)
    assert await worker.recover_once() == 1
    tasks = list(instance._active_tasks.values())
    await asyncio.gather(*tasks)
    assert observed == [(tenant_context.user_id, False, True)]
    assert await worker.recover_once() == 0
    status = await RuntimeJournal(repository.async_session).status(tenant, novel)
    assert status["status"] == "applied" and not status["running"]
    await worker.stop()
    await store.aclose()


@pytest.mark.asyncio
async def test_removed_membership_never_resumes_old_automatic_work(
    repository, tenant_context, sample_novel, monkeypatch,
):
    store, tenant, novel = await seed(repository, tenant_context, sample_novel)
    claim = await store.claim(tenant, novel, "original", 300)
    await store.set_recovery(claim.lease_token, recovery(tenant_context))
    await store.release_for_restart(tenant, novel, "original", claim.lease_token)
    async with repository.async_session() as session, session.begin():
        await session.execute(delete(TenantMembershipModel).where(
            TenantMembershipModel.user_id == tenant_context.user_id))
    instance = orchestrator(repository, monkeypatch)
    worker = service(store, repository, instance)
    assert await worker.recover_once() == 0
    assert not instance._active_tasks
    assert await store.recovery_candidates() == []
    await worker.stop()


@pytest.mark.asyncio
async def test_exhausted_restart_budget_does_not_start_another_model_call(
    repository, tenant_context, sample_novel, monkeypatch,
):
    store, tenant, novel = await seed(repository, tenant_context, sample_novel)
    claim = await store.claim(tenant, novel, "original", 300)
    await store.set_recovery(claim.lease_token, recovery(tenant_context, restarts=3))
    await store.release_for_restart(tenant, novel, "original", claim.lease_token)
    instance = orchestrator(repository, monkeypatch)
    worker = service(store, repository, instance)
    assert await worker.recover_once() == 0
    assert not instance._active_tasks and await store.recovery_candidates() == []
    await worker.stop()


@pytest.mark.asyncio
async def test_process_shutdown_retains_automatic_intent_without_restarting_cancelled_work(
    repository, tenant_context, sample_novel, monkeypatch,
):
    store, tenant, novel = await seed(repository, tenant_context, sample_novel)
    claim = await store.claim(tenant, novel, "original", 300)
    await store.set_recovery(claim.lease_token, recovery(tenant_context))
    instance = orchestrator(repository, monkeypatch)
    assert await instance.try_start(tenant_context, novel)
    entered = asyncio.Event()

    async def stream(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()
        yield

    monkeypatch.setattr(instance, "stream_events", stream)
    prepared = routes.PreparedWorkflow(None, None, False, True,
        ClaimedWorkflowCommand("original", claim.lease_token), auto_mode=True)
    _, producer = routes._start_stream_execution(instance, store, tenant_context, novel, prepared)
    await asyncio.wait_for(entered.wait(), timeout=2)
    worker = service(store, repository, instance)
    await worker.stop()
    await instance.aclose()
    assert producer.cancelled()
    assert len(await store.recovery_candidates()) == 1
    assert await store.cancel(tenant, novel)
    assert await store.recovery_candidates() == []
    await store.aclose()


@pytest.mark.asyncio
async def test_restart_does_not_discard_orphan_with_durable_pending_task_writes(
    repository, tenant_context, sample_novel, monkeypatch,
):
    store, tenant, novel = await seed(repository, tenant_context, sample_novel)
    claim = await store.claim(tenant, novel, "original", 300)
    await store.set_recovery(claim.lease_token, recovery(tenant_context))
    await store.release_for_restart(tenant, novel, "original", claim.lease_token)
    instance = orchestrator(repository, monkeypatch)
    instance.get_public_state.return_value = {
        "interrupts": [], "next_nodes": [], "has_pending_checkpoint": True}
    observed = []

    async def stream(context, thread, **kwargs):
        observed.append(kwargs.get("is_restart"))
        yield WorkflowEvent(id=1, type="completed", thread_id=thread, data={})

    monkeypatch.setattr(instance, "stream_events", stream)
    worker = service(store, repository, instance)
    try:
        assert await worker.recover_once() == 1
        await asyncio.gather(*list(instance._active_tasks.values()))
        assert observed == [True]
        assert (await RuntimeJournal(repository.async_session).status(tenant, novel))["status"] == "applied"
    finally:
        await worker.stop()
        await store.aclose()
