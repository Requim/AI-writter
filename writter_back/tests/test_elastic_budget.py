"""Real PostgreSQL allocation tests; no simulated provider acceptance."""

import asyncio
from dataclasses import replace

import pytest
from sqlalchemy import select

from api.dependencies import get_tenant_context
from api.main import app
from application.creative.errors import CreativePause
from infrastructure.database.creative_models import CreativeRequestModel, CreativeSessionModel
from infrastructure.database.creative_repository import PostgresCreativeRepository
from tests.test_creative_budget_grants import seed_book


async def activate(client, novel, *, version=1, total=200, key="elastic", **extra):
    return await client.put(f"/api/v1/novels/{novel}/creative/budget-policy", json={
        "expected_version": version, "expected_total": total,
        "mode": "elastic_v1", "reason": "Approved allocation-only optimization", **extra,
    }, headers={"Idempotency-Key": key})


@pytest.mark.asyncio
async def test_elastic_activation_preserves_total_and_all_physical_spend(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    for _ in range(32):
        await creative.reserve(tenant, novel, "chapter:1", "reflection_node")
    response = await activate(async_client, novel)
    assert response.status_code == 200, response.text
    assert response.json()["limits"]["total"] == 200
    assert response.json()["limits"]["chapter"] == 32
    assert response.json()["counters"] == {"chapter:1": 32}
    await creative.reserve(tenant, novel, "chapter:1", "reflection_node")
    restarted = PostgresCreativeRepository(repository.async_session)
    assert (await restarted.get_session(tenant, novel))["counters"] == {"chapter:1": 33}
    replay = await activate(async_client, novel)
    assert replay.status_code == 200 and replay.json() == response.json()
    stale = await activate(async_client, novel, key="stale")
    assert stale.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [
    {"expected_total": 201}, {"unlimited": True}, {"chapter_hard": 10000},
])
async def test_policy_request_cannot_change_total_or_inject_allowances(
    async_client, repository, tenant_context, sample_novel, monkeypatch, extra,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    before = await creative.get_session(str(tenant_context.tenant_id), str(sample_novel.id))
    response = await activate(async_client, sample_novel.id, **extra)
    assert response.status_code in {409, 422}
    assert await creative.get_session(str(tenant_context.tenant_id), str(sample_novel.id)) == before


@pytest.mark.asyncio
async def test_member_and_outsider_cannot_activate_policy(
    async_client, repository, tenant_context, other_tenant_context, sample_novel, monkeypatch,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    app.dependency_overrides[get_tenant_context] = lambda: replace(tenant_context, role="member")
    assert (await activate(async_client, sample_novel.id)).status_code == 403
    app.dependency_overrides[get_tenant_context] = lambda: other_tenant_context
    assert (await activate(async_client, sample_novel.id)).status_code == 404
    saved = await creative.get_session(str(tenant_context.tenant_id), str(sample_novel.id))
    assert "policy" not in saved["limits"]


async def set_counters(repository, context, novel, counters):
    async with repository.async_session.begin() as session:
        row = await session.scalar(select(CreativeSessionModel).where(
            CreativeSessionModel.tenant_id == context.tenant_id,
            CreativeSessionModel.novel_id == novel.id,
        ).with_for_update())
        row.counters = counters


@pytest.mark.asyncio
async def test_concurrent_elastic_calls_preserve_future_chapters_and_review(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    novel, tenant = str(sample_novel.id), str(tenant_context.tenant_id)
    assert (await activate(async_client, novel)).status_code == 200
    # Total 200 minus prep60, review44, future2*24 leaves chapter1 at48.
    await set_counters(repository, tenant_context, sample_novel, {"chapter:1": 47})
    outcomes = await asyncio.gather(
        creative.reserve(tenant, novel, "chapter:1", "one"),
        creative.reserve(tenant, novel, "chapter:1", "two"), return_exceptions=True,
    )
    assert sum(isinstance(value, str) for value in outcomes) == 1
    assert sum(isinstance(value, CreativePause) for value in outcomes) == 1
    assert (await creative.get_session(tenant, novel))["counters"] == {"chapter:1": 48}


@pytest.mark.asyncio
async def test_round_replay_and_restart_never_replenish_spent_requests(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    assert (await activate(async_client, novel)).status_code == 200
    await creative.begin_budget_round(tenant, novel, "chapter:1", "body-hash", "review")
    for _ in range(12):
        await creative.reserve(tenant, novel, "chapter:1", "reflection_node")
    restarted = PostgresCreativeRepository(repository.async_session)
    await restarted.begin_budget_round(tenant, novel, "chapter:1", "body-hash", "review")
    with pytest.raises(CreativePause):
        await restarted.reserve(tenant, novel, "chapter:1", "reflection_node")
    saved = await restarted.get_session(tenant, novel)
    assert saved["counters"] == {"chapter:1": 12}
    assert saved["limits"]["round"]["remaining"] == 0


@pytest.mark.asyncio
async def test_insufficient_complete_round_pauses_without_consuming(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    assert (await activate(async_client, novel)).status_code == 200
    await set_counters(repository, tenant_context, sample_novel, {"chapter:1": 31})
    with pytest.raises(CreativePause):
        await creative.begin_budget_round(tenant, novel, "chapter:1", "new-body", "repair")
    assert (await creative.get_session(tenant, novel))["counters"] == {"chapter:1": 31}


@pytest.mark.asyncio
async def test_repair_round_adapts_to_complete_minimum_without_raising_cap(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    assert (await activate(async_client, novel)).status_code == 200
    # Protected allowances leave48 for chapter1; 30 spent leaves18.
    await set_counters(repository, tenant_context, sample_novel, {"chapter:1": 30})
    await creative.begin_budget_round(tenant, novel, "chapter:1", "new-body", "repair")
    saved = await creative.get_session(tenant, novel)
    assert saved["limits"]["round"]["size"] == 18
    assert saved["limits"]["round"]["remaining"] == 18
    assert saved["limits"]["total"] == 200
    assert saved["counters"] == {"chapter:1": 30}


@pytest.mark.asyncio
@pytest.mark.parametrize("elastic", [False, True])
async def test_whole_book_total_is_enforced_for_legacy_and_elastic(
    async_client, repository, tenant_context, sample_novel, monkeypatch, elastic,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    if elastic:
        assert (await activate(async_client, novel)).status_code == 200
    # Historical overflow/import must not let a fresh bucket evade the total.
    await set_counters(repository, tenant_context, sample_novel, {
        "preparation": 59, "review": 44, "chapter:1": 96, "chapter:2": 1,
    })
    before = await creative.get_session(tenant, novel)
    with pytest.raises(CreativePause):
        await creative.reserve(tenant, novel, "preparation", "creative_development_node")
    assert (await creative.get_session(tenant, novel)) == before


@pytest.mark.asyncio
async def test_distinct_buckets_cannot_concurrently_overrun_book_total(
    repository, tenant_context, sample_novel, monkeypatch,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    await set_counters(repository, tenant_context, sample_novel, {
        "preparation": 60, "review": 43, "chapter:1": 96,
    })
    outcomes = await asyncio.gather(
        creative.reserve(tenant, novel, "chapter:2", "writer"),
        creative.reserve(tenant, novel, "review", "recap"), return_exceptions=True,
    )
    assert sum(isinstance(value, str) for value in outcomes) == 1
    assert sum(isinstance(value, CreativePause) for value in outcomes) == 1
    saved = await creative.get_session(tenant, novel)
    assert sum(saved["counters"].values()) == 200


@pytest.mark.asyncio
async def test_hard_chapter_cap_survives_large_shared_surplus(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    assert (await activate(async_client, novel)).status_code == 200
    await set_counters(repository, tenant_context, sample_novel, {
        "preparation": 60, "review": 44, "chapter:3": 63,
    })
    await creative.reserve(tenant, novel, "chapter:3", "reflection_node")
    with pytest.raises(CreativePause):
        await creative.reserve(tenant, novel, "chapter:3", "reflection_node")
    assert (await creative.get_session(tenant, novel))["counters"]["chapter:3"] == 64


@pytest.mark.asyncio
async def test_concurrent_identical_round_creation_holds_only_once(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    assert (await activate(async_client, novel)).status_code == 200
    await asyncio.gather(
        creative.begin_budget_round(tenant, novel, "chapter:1", "source", "repair"),
        creative.begin_budget_round(tenant, novel, "chapter:1", "source", "repair"),
    )
    saved = await creative.get_session(tenant, novel)
    assert saved["counters"] == {}
    assert saved["limits"]["round"]["remaining"] == 20
    records = await creative.records(tenant, novel, "control")
    assert sum(row["payload"].get("operation") == "begin" for row in records) == 1


@pytest.mark.asyncio
async def test_finish_merges_budget_receipt_with_provider_usage(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    assert (await activate(async_client, novel)).status_code == 200
    request_id = await creative.reserve(tenant, novel, "chapter:1", "reflection_node")
    await creative.finish_request(tenant, novel, request_id, {"prompt_tokens": 71})
    async with repository.async_session() as session:
        row = await session.scalar(select(CreativeRequestModel).where(
            CreativeRequestModel.novel_id == sample_novel.id))
        assert row.status == "completed"
        assert row.usage["prompt_tokens"] == 71
        assert row.usage["budget"]["policy"] == "elastic_v1"
        assert row.usage["budget"]["soft_threshold_exceeded"] is False


@pytest.mark.asyncio
async def test_runtime_review_scope_persists_hold_and_reuses_it(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    from application.creative.runtime import creative_node_scope
    from service.ports.model_meter import active_model_meter

    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    assert (await activate(async_client, novel)).status_code == 200
    saved = await creative.get_session(tenant, novel)
    state = {"author_mode": "autonomous_v1", "creative_session_id": saved["id"],
        "current_chapter_index": 0, "current_chapter_content": "A complete retained candidate."}
    config = {"configurable": {"creative_repository": creative, "tenant_id": tenant, "novel_id": novel}}
    for _ in range(2):
        async with creative_node_scope("reflection_node", state, config):
            await active_model_meter.get().reserve()
    saved = await creative.get_session(tenant, novel)
    assert saved["limits"]["round"]["size"] == 12
    assert saved["limits"]["round"]["remaining"] == 10
    assert saved["counters"] == {"chapter:1": 2}


@pytest.mark.asyncio
async def test_timeout_receipt_is_unknown_charged_and_does_not_leak_error(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    from unittest.mock import AsyncMock, Mock
    from infrastructure.llm.metering import completion
    from service.ports.model_meter import CreativeRequestMeter, active_model_meter

    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    client = Mock()
    client.with_options.return_value = client
    client.chat.completions.create = AsyncMock(side_effect=TimeoutError("private provider credential"))
    token = active_model_meter.set(CreativeRequestMeter(creative, tenant, novel, "chapter:1", "review"))
    try:
        with pytest.raises(TimeoutError):
            await completion(client, model="test")
    finally:
        active_model_meter.reset(token)
    async with repository.async_session() as session:
        row = await session.scalar(select(CreativeRequestModel).where(
            CreativeRequestModel.novel_id == sample_novel.id))
        assert row.status == "unknown" and row.finished_at is not None
        assert row.usage["outcome"]["error_type"] == "TimeoutError"
        assert row.usage["outcome"]["elapsed_ms"] >= 0
        assert "credential" not in str(row.usage)
    assert (await creative.get_session(tenant, novel))["counters"] == {"chapter:1": 1}


@pytest.mark.asyncio
async def test_budget_snapshot_uses_elastic_capacity_not_soft_threshold(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    from application.checkpoint_budget import checkpoint_budget_blocker

    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    for _ in range(32):
        await creative.reserve(tenant, novel, "chapter:1", "reflection_node")
    assert (await activate(async_client, novel)).status_code == 200
    saved = await creative.get_session(tenant, novel)
    values = {"author_mode": "autonomous_v1", "creative_session_id": saved["id"], "current_chapter_index": 0}
    config = {"configurable": {"creative_repository": creative, "tenant_id": tenant, "novel_id": novel}}
    assert await checkpoint_budget_blocker(values, config, "reflection_node") is None
    await creative.begin_budget_round(tenant, novel, "chapter:1", "body", "review")
    for _ in range(12):
        await creative.reserve(tenant, novel, "chapter:1", "reflection_node")
    blocker = await checkpoint_budget_blocker(values, config, "reflection_node")
    assert blocker["retryable"] is False
    assert blocker["used"] == blocker["limit"] == 44


@pytest.mark.asyncio
async def test_completed_round_release_never_refunds_or_reopens_same_body(
    async_client, repository, tenant_context, sample_novel, monkeypatch,
):
    creative = await seed_book(repository, tenant_context, sample_novel, monkeypatch)
    tenant, novel = str(tenant_context.tenant_id), str(sample_novel.id)
    assert (await activate(async_client, novel)).status_code == 200
    await creative.begin_budget_round(tenant, novel, "chapter:1", "unchanged-body", "repair")
    await creative.reserve(tenant, novel, "chapter:1", "revision_node")
    await creative.release_budget_round(tenant, novel, "chapter:1")
    with pytest.raises(CreativePause):
        await creative.begin_budget_round(tenant, novel, "chapter:1", "unchanged-body", "repair")
    saved = await creative.get_session(tenant, novel)
    assert saved["counters"] == {"chapter:1": 1}
    assert saved["limits"]["round"]["status"] == "released"
