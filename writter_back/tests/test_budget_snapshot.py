"""Reload must not offer automatic continuation past a persisted request cap."""

from unittest.mock import AsyncMock
from datetime import datetime, timedelta, timezone

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from application.orchestrator import NovelOrchestrator
from application.schemas.agent_state import NovelAgentState
from infrastructure.database.creative_repository import PostgresCreativeRepository
from tests.test_creative_repository import seed_creative


async def failed(state: NovelAgentState):
    raise RuntimeError("credential must never be exposed from raw checkpoint errors")


async def budget_paused(state: NovelAgentState):
    interrupt({"action": "creative_paused", "reason": "budget_exhausted",
               "message": "chapter:1 调用预算已耗尽", "retryable": True})


async def current_budget_paused(state: NovelAgentState):
    from application.creative.errors import CreativePause
    from application.creative.runtime import pause_creative
    return pause_creative(CreativePause("budget_exhausted", "chapter:1 调用预算已耗尽"),
                          "fact_review_node")


def graph(failure):
    builder = StateGraph(NovelAgentState)
    node = (current_budget_paused if failure == "current_budget_pause" else
            budget_paused if failure == "budget_pause" else failed if failure else lambda state: {})
    builder.add_node("fact_review_node", node)
    builder.add_edge(START, "fact_review_node")
    builder.add_edge("fact_review_node", END)
    return builder.compile(checkpointer=InMemorySaver())


@pytest.mark.asyncio
async def test_new_budget_pause_event_does_not_advertise_direct_retry():
    workflow = graph("current_budget_pause")
    config = {"configurable": {"thread_id": "actual-budget-interrupt"}}
    await workflow.ainvoke({"current_chapter_content": "保留草稿"}, config)
    checkpoint = await workflow.aget_state(config)
    event = checkpoint.tasks[0].interrupts[0].value
    assert event["reason"] == "budget_exhausted"
    assert event["retryable"] is False
    assert checkpoint.values["current_chapter_content"] == "保留草稿"


@pytest.mark.asyncio
@pytest.mark.parametrize("used,reason,blocked", [
    (32, "budget_exhausted", True), (31, "budget_exhausted", False),
    (32, "session_mismatch", False),
])
async def test_budget_interrupt_reload_uses_actual_scope_and_remaining_allowance(
    repository, tenant_context, sample_novel, monkeypatch, used, reason, blocked,
):
    creative, tenant, novel = await seed_creative(repository, tenant_context, sample_novel, monkeypatch)
    for _ in range(used):
        await creative.reserve(tenant, novel, "chapter:1", "isolated-pause-fixture")
    session = await creative.get_session(tenant, novel)
    def paused(state: NovelAgentState):
        interrupt({"action": "creative_paused", "reason": reason,
                   "message": "chapter:1 调用预算已耗尽", "retryable": True})
    builder = StateGraph(NovelAgentState)
    builder.add_node("reflection_node", paused)
    builder.add_edge(START, "reflection_node")
    builder.add_edge("reflection_node", END)
    service = NovelOrchestrator(repository, AsyncMock(), {})
    service._workflow = builder.compile(checkpointer=InMemorySaver())
    monkeypatch.setattr(service, "_ensure_workflow", AsyncMock())
    monkeypatch.setattr(service, "_get_llm_instance", lambda: None)
    await service._workflow.ainvoke({
        "author_mode": "autonomous_v1", "current_chapter_index": 0,
        "creative_session_id": session["id"], "current_chapter_content": "未归档正文",
    }, service._make_config(tenant_context, novel))
    public = await service.get_public_state(tenant_context, novel)
    assert public["status"] == "paused"
    assert public["state"]["has_current_chapter_content"] is True
    if blocked:
        assert public["blocker"]["retryable"] is False
        assert public["blocker"]["used"] == public["blocker"]["limit"] == 32
        assert public["interrupts"][0]["retryable"] is False
        assert "32/32" in public["interrupts"][0]["message"]
    else:
        assert public.get("blocker") is None
        assert public["interrupts"][0]["retryable"] is True
    assert (await creative.get_session(tenant, novel))["counters"] == {"chapter:1": used}


@pytest.mark.asyncio
@pytest.mark.parametrize("used,failure,wrong_session,blocked", [
    (32, True, False, True), (31, True, False, False),
    (32, False, False, False), (32, True, True, False),
])
async def test_snapshot_budget_blocker_is_durable_scoped_and_requires_failed_work(
    repository, tenant_context, sample_novel, monkeypatch, used, failure, wrong_session, blocked,
):
    creative, tenant, novel = await seed_creative(repository, tenant_context, sample_novel, monkeypatch)
    for _ in range(used):
        await creative.reserve(tenant, novel, "chapter:1", "isolated-snapshot-fixture")
    session = await creative.get_session(tenant, novel)
    service = NovelOrchestrator(repository, AsyncMock(), {})
    service._workflow = graph(failure)
    monkeypatch.setattr(service, "_ensure_workflow", AsyncMock())
    monkeypatch.setattr(service, "_get_llm_instance", lambda: None)
    cfg = service._make_config(tenant_context, novel)
    state = {"author_mode": "autonomous_v1", "current_chapter_index": 0,
        "current_chapter_content": "已保留正文", "creative_session_id": (
            "other-session" if wrong_session else session["id"])}
    if failure:
        with pytest.raises(RuntimeError):
            await service._workflow.ainvoke(state, cfg)
    else:
        await service._workflow.ainvoke(state, cfg)
    public = await service.get_public_state(tenant_context, novel)
    if blocked:
        assert public["blocker"]["code"] == "budget_exhausted"
        assert public["blocker"]["retryable"] is False
        assert public["blocker"]["node"] == "fact_review_node"
        assert public["blocker"]["used"] == public["blocker"]["limit"] == 32
        assert "credential" not in str(public["blocker"])
    else:
        assert public.get("blocker") is None
    assert public["state"]["has_current_chapter_content"] is True
    assert (await creative.get_session(tenant, novel))["counters"] == {"chapter:1": used}


@pytest.mark.asyncio
@pytest.mark.parametrize("checkpoint_kind", ["failed", "budget_pause"])
async def test_execution_started_during_budget_read_supersedes_old_blocked_snapshot(
    repository, tenant_context, sample_novel, monkeypatch, checkpoint_kind,
):
    creative, tenant, novel = await seed_creative(repository, tenant_context, sample_novel, monkeypatch)
    for _ in range(32):
        await creative.reserve(tenant, novel, "chapter:1", "isolated-race-fixture")
    session = await creative.get_session(tenant, novel)
    service = NovelOrchestrator(repository, AsyncMock(), {})
    service._workflow = graph(True if checkpoint_kind == "failed" else "budget_pause")
    monkeypatch.setattr(service, "_ensure_workflow", AsyncMock())
    monkeypatch.setattr(service, "_get_llm_instance", lambda: None)
    cfg = service._make_config(tenant_context, novel)
    state = {"author_mode": "autonomous_v1", "current_chapter_index": 0,
        "creative_session_id": session["id"], "current_chapter_content": "已保留正文"}
    if checkpoint_kind == "failed":
        with pytest.raises(RuntimeError):
            await service._workflow.ainvoke(state, cfg)
    else:
        await service._workflow.ainvoke(state, cfg)
    original = PostgresCreativeRepository.get_session

    async def racing_read(store, *args):
        row = await original(store, *args)
        assert await service.try_start(tenant_context, novel)
        service.record_activity(tenant_context, novel, active_node="creative_decision_node")
        return row

    monkeypatch.setattr(PostgresCreativeRepository, "get_session", racing_read)
    try:
        public = await service.get_public_state(tenant_context, novel)
        assert public["status"] == "running" and public.get("blocker") is None
        assert public["interrupts"] == []
        assert public["execution"]["active_node"] == "creative_decision_node"
    finally:
        service.finish(tenant_context, novel)


@pytest.mark.asyncio
async def test_already_running_snapshot_preserves_inactivity_detection(
    repository, tenant_context, sample_novel, monkeypatch,
):
    service = NovelOrchestrator(repository, AsyncMock(), {})
    service._workflow = graph(False)
    monkeypatch.setattr(service, "_ensure_workflow", AsyncMock())
    monkeypatch.setattr("config.settings.WORKFLOW_TIMEOUT_SECONDS", 1)
    novel = str(sample_novel.id)
    assert await service.try_start(tenant_context, novel)
    key = service.execution_key(tenant_context, novel)
    service._execution_snapshots[key]["last_activity_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    try:
        public = await service.get_public_state(tenant_context, novel)
        assert public["status"] == "running"
        assert public["execution"]["is_stale"] is True
        assert public.get("blocker") is None
    finally:
        service.finish(tenant_context, novel)
