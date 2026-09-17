"""自动推进必须修复而不是伪造通过，且预算可以跨 checkpoint 保留。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from langgraph.types import Command

from application.automatic_recovery import recovery_update
from application.errors import AutomaticRecoveryExhausted
from application.agents.reflection_node import _route_quality_result, reflection_review_node
from application.proposals import proposal_update
from application.fact_gate_workflow import check_fact_artifact, fact_review_node
from tests.test_fact_gate import config, setup_gate
from tests.test_workflow_flow import orchestrator, tenant_context


def test_budget_survives_retries_and_resets_only_on_next_chapter():
    state = recovery_update({}, "审读")
    state.update(recovery_update(state, "审读"))
    with pytest.raises(AutomaticRecoveryExhausted):
        recovery_update(state, "审读")
    assert recovery_update({**state, "current_chapter_index": 1}, "审读")[
        "automatic_recovery"
    ]["attempts"]["审读"] == 1


def test_auto_quality_conflict_revises_without_accepting_or_interrupting():
    gate = {"decision": "human_review", "goal_review_required": True}
    result = _route_quality_result({}, {"configurable": {"auto_mode": True}}, gate, [])
    assert result.goto == "revision_node"
    assert result.update["quality_gate"]["goal_review_required"] is True
    assert result.update["quality_gate"]["source_decision"] == "human_review"


def test_exhausted_auto_quality_fails_instead_of_waiting_for_review():
    with pytest.raises(AutomaticRecoveryExhausted):
        _route_quality_result(
            {"revision_attempts": 5}, {"configurable": {"auto_mode": True}},
            {"decision": "patch"}, [],
        )


@pytest.mark.asyncio
async def test_unavailable_auto_review_retries_from_existing_draft():
    state = proposal_update({}, "reflection", {"status": "unavailable"}, 1)
    result = await reflection_review_node(state, {"configurable": {"auto_mode": True}})
    assert result.goto == "reflection_node"
    assert result.update["pending_proposal"] is None


@pytest.mark.asyncio
async def test_auto_fact_conflict_revises_without_human_acknowledgement():
    cfg = config(setup_gate())
    cfg["configurable"]["auto_mode"] = True
    pending = await check_fact_artifact(
        {}, cfg, "辛家祖祠归陆家所有。", "body", Command(goto="reflection_node")
    )
    result = await fact_review_node(pending.update, cfg)
    assert result.goto == "revision_node"
    assert "fact_acknowledgements" not in result.update
    assert result.update["automatic_recovery"]["attempts"]["事实审校:body"] == 1


@pytest.mark.asyncio
async def test_auto_retry_preserves_pending_review_instead_of_rerouting_draft():
    service, context, thread_id = orchestrator(), tenant_context(), str(uuid4())
    service.set_auto_mode(context, thread_id, True)
    service._workflow = SimpleNamespace(
        aget_state=AsyncMock(return_value=SimpleNamespace(
            values={"current_chapter_content": "已有正文"},
            next=("fact_review_node",),
            tasks=[SimpleNamespace(interrupts=[object()])],
        )),
        aupdate_state=AsyncMock(),
    )
    assert await service.prepare_retry_checkpoint(context, thread_id) == "fact_review_node"
    update = service._workflow.aupdate_state.await_args.args[1]
    assert update["next_tool"] == "fact_review_node"
    assert update["auto_mode"] is True


@pytest.mark.asyncio
async def test_real_paused_graph_switches_to_auto_and_finishes_three_chapters(monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver
    from application.workflow_builder import create_novel_workflow
    from tests.test_workflow_flow import FakeWorkflowLLM, _three_chapter_input, _manual_workflow_config

    service, context, thread_id = orchestrator(), tenant_context(), str(uuid4())
    service._workflow = create_novel_workflow(InMemorySaver())
    service._llm_instance = FakeWorkflowLLM()
    service.repository = None
    service.memory_service = None
    def isolated_config(ctx, thread, include_llm=True):
        cfg = _manual_workflow_config(service._llm_instance)
        cfg["recursion_limit"] = 120
        cfg["configurable"].update(
            thread_id=service.execution_key(ctx, thread),
            auto_mode=service._auto_mode.get(service.execution_key(ctx, thread), False),
        )
        return cfg
    monkeypatch.setattr(service, "_make_config", isolated_config)
    service.set_auto_mode(context, thread_id, False)
    result = await service.invoke(context, thread_id, _three_chapter_input())
    assert result["__interrupt__"]
    service.set_auto_mode(context, thread_id, True)
    result = await service.retry(context, thread_id)
    assert result["is_completed"] is True
    assert result["current_chapter_index"] == 3
    assert not result.get("__interrupt__")


@pytest.mark.asyncio
async def test_auto_background_run_outlives_disconnect_and_manual_deadline(monkeypatch):
    import asyncio
    from dataclasses import replace
    from api.routers import workflow_router
    from tests.test_workflow_command_idempotency import (
        FakeRedis, RedisWorkflowCommandStore, StreamingOrchestrator, prepared_stream,
    )

    monkeypatch.setattr(workflow_router.settings, "WORKFLOW_TIMEOUT_SECONDS", 0.01)
    context, thread_id = tenant_context(), str(uuid4())
    store = RedisWorkflowCommandStore("redis://unused", client=FakeRedis())
    prepared = replace(await prepared_stream(store, context, thread_id), auto_mode=True)
    service = StreamingOrchestrator()
    channel, producer = workflow_router._start_stream_execution(service, store, context, thread_id, prepared)
    body = workflow_router._stream_generator(channel, service, context, thread_id, prepared.command.command_id)
    await anext(body)
    await body.aclose()
    try:
        await asyncio.sleep(0.03)
        assert not producer.done()
    finally:
        service.gate.set()
        await asyncio.wait_for(producer, 1)
    assert service.finished
    assert not producer.cancelled()
