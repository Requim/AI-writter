"""Real PostgreSQL recovery intent, cancellation and takeover boundaries."""

from datetime import datetime, timedelta, timezone

import pytest

from infrastructure.database.runtime_models import WorkflowRunModel
from service.ports.workflow_command_store import WorkflowCommandClaimStatus as Status
from tests.test_workflow_runtime import seed


def intent():
    return {"user_id": "server-actor", "restarts": 0,
            "deadline": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "input_data": {"workflow_run_id": "unchanged-quota-id"}}


@pytest.mark.asyncio
async def test_automatic_restart_intent_survives_store_shutdown(
    repository, tenant_context, sample_novel,
):
    store, tenant, novel = await seed(repository, tenant_context, sample_novel)
    claim = await store.claim(tenant, novel, "automatic", 300)
    assert await store.set_recovery(claim.lease_token, intent())
    run_id = store.owners[claim.lease_token].run_id
    assert await store.release_for_restart(tenant, novel, "automatic", claim.lease_token)
    await store.aclose()
    restarted = type(store)(repository.async_session)
    candidates = await restarted.recovery_candidates()
    assert [item["run_id"] for item in candidates] == [str(run_id)]
    assert candidates[0]["recovery"]["input_data"]["workflow_run_id"] == "unchanged-quota-id"


@pytest.mark.asyncio
async def test_user_cancelled_tasks_are_never_restart_candidates(
    repository, tenant_context, sample_novel,
):
    store, tenant, novel = await seed(repository, tenant_context, sample_novel)
    claim = await store.claim(tenant, novel, "automatic", 300)
    assert await store.set_recovery(claim.lease_token, intent())
    assert await store.cancel(tenant, novel)
    assert await store.release_for_restart(tenant, novel, "automatic", claim.lease_token)
    assert await store.recovery_candidates() == []


@pytest.mark.asyncio
async def test_manual_and_completed_runs_are_not_restarted(
    repository, tenant_context, sample_novel,
):
    store, tenant, novel = await seed(repository, tenant_context, sample_novel)
    manual = await store.claim(tenant, novel, "manual", 300)
    await store.release_for_restart(tenant, novel, "manual", manual.lease_token)
    assert await store.recovery_candidates() == []
    automatic = await store.claim(tenant, novel, "automatic", 300)
    await store.set_recovery(automatic.lease_token, intent())
    await store.finalize(tenant, novel, "automatic", automatic.lease_token, 300)
    assert await store.recovery_candidates() == []


@pytest.mark.asyncio
async def test_restart_cannot_take_over_after_a_newer_user_command(
    repository, tenant_context, sample_novel,
):
    store, tenant, novel = await seed(repository, tenant_context, sample_novel)
    original = await store.claim(tenant, novel, "automatic", 300)
    await store.set_recovery(original.lease_token, intent())
    old_run = store.owners[original.lease_token].run_id
    await store.release_for_restart(tenant, novel, "automatic", original.lease_token)
    later = await store.claim(tenant, novel, "later-user-command", 300)
    await store.finalize(tenant, novel, "later-user-command", later.lease_token, 300)
    stale = await store.claim(tenant, novel, "restart", 300, expected_run_id=old_run)
    assert stale.status == Status.IN_PROGRESS
    assert await store.recovery_candidates() == []


@pytest.mark.asyncio
async def test_expired_owner_cannot_change_recovery_intent(
    repository, tenant_context, sample_novel,
):
    store, tenant, novel = await seed(repository, tenant_context, sample_novel)
    claim = await store.claim(tenant, novel, "automatic", 300)
    token = claim.lease_token
    await store.release(tenant, novel, "automatic", token)
    assert not await store.set_recovery(token, intent())


@pytest.mark.asyncio
async def test_failed_recovery_can_be_disabled_without_changing_the_book(
    repository, tenant_context, sample_novel,
):
    store, tenant, novel = await seed(repository, tenant_context, sample_novel)
    claim = await store.claim(tenant, novel, "automatic", 300)
    await store.set_recovery(claim.lease_token, intent())
    run_id = store.owners[claim.lease_token].run_id
    await store.release_for_restart(tenant, novel, "automatic", claim.lease_token)
    await store.clear_recovery(run_id)
    assert await store.recovery_candidates() == []
    assert (await repository.find_by_id(tenant, novel)).progress.current_chapter == 0
    async with repository.async_session() as session:
        assert (await session.get(WorkflowRunModel, run_id)).status == "orphaned"
