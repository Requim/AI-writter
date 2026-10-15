"""Process recovery resumes saved work without allocating another review budget."""

from typing import TypedDict
from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from application.orchestrator import NovelOrchestrator
from tests.test_workflow_command_idempotency import tenant_context


class SavedWork(TypedDict):
    workflow_run_id: str
    automatic_recovery: dict
    reviewed: bool


@pytest.mark.asyncio
async def test_process_restart_preserves_saved_quality_budget_and_quota_identity(monkeypatch):
    context, novel = tenant_context(), "restart-budget"
    service = NovelOrchestrator(AsyncMock(), AsyncMock(), {})
    fail = True

    async def review(state: SavedWork):
        if fail:
            raise RuntimeError("simulated process interruption")
        assert state["automatic_recovery"] == {"attempts": {"revision": 2}}
        assert state["workflow_run_id"] == "original-quota-id"
        return {"reviewed": True}

    builder = StateGraph(SavedWork)
    builder.add_node("review", review)
    builder.add_edge(START, "review")
    builder.add_edge("review", END)
    service._workflow = builder.compile(checkpointer=InMemorySaver())
    monkeypatch.setattr(service, "_ensure_workflow", AsyncMock())
    monkeypatch.setattr(service, "_get_llm_instance", lambda: None)
    config = service._make_config(context, novel)
    with pytest.raises(RuntimeError, match="simulated process"):
        await service._workflow.ainvoke(
            {"workflow_run_id": "original-quota-id",
             "automatic_recovery": {"attempts": {"revision": 2}}, "reviewed": False}, config)
    fail = False
    events = [event async for event in service.stream_events(context, novel, is_restart=True)]
    saved = await service._workflow.aget_state(config)
    assert saved.values["reviewed"] is True
    assert saved.values["workflow_run_id"] == "original-quota-id"
    assert events[-1].type == "completed"


@pytest.mark.asyncio
async def test_process_restart_rejects_checkpoint_without_pending_work(monkeypatch):
    service = NovelOrchestrator(AsyncMock(), AsyncMock(), {})
    builder = StateGraph(SavedWork)
    builder.add_edge(START, END)
    service._workflow = builder.compile(checkpointer=InMemorySaver())
    monkeypatch.setattr(service, "_ensure_workflow", AsyncMock())
    monkeypatch.setattr(service, "_get_llm_instance", lambda: None)
    with pytest.raises(Exception, match="checkpoint"):
        _ = [event async for event in service.stream_events(
            tenant_context(), "no-saved-work", is_restart=True)]


class InterruptedSnapshotSaver(InMemorySaver):
    fail_snapshot = True

    async def aput(self, config, checkpoint, metadata, new_versions):
        if self.fail_snapshot and metadata.get("step") == 1:
            raise RuntimeError("snapshot interrupted after durable task writes")
        return await super().aput(config, checkpoint, metadata, new_versions)


@pytest.mark.asyncio
async def test_restart_uses_durable_task_results_when_next_snapshot_was_interrupted(monkeypatch):
    context, novel = tenant_context(), "restart-pending-writes"
    service = NovelOrchestrator(AsyncMock(), AsyncMock(), {})
    saver = InterruptedSnapshotSaver()
    initialized = []

    async def initialize(state):
        initialized.append(True)
        return {"automatic_recovery": {"attempts": {"revision": 2}}}

    async def review(state):
        if saver.fail_snapshot:
            raise RuntimeError("worker interrupted before snapshot completed")
        assert state["workflow_run_id"] == "original-quota-id"
        assert state["automatic_recovery"] == {"attempts": {"revision": 2}}
        return {"reviewed": True}

    builder = StateGraph(SavedWork)
    builder.add_node("initialize", initialize)
    builder.add_node("review", review)
    builder.add_edge(START, "initialize")
    builder.add_edge("initialize", "review")
    builder.add_edge("review", END)
    service._workflow = builder.compile(checkpointer=saver)
    monkeypatch.setattr(service, "_ensure_workflow", AsyncMock())
    monkeypatch.setattr(service, "_get_llm_instance", lambda: None)
    config = service._make_config(context, novel)
    with pytest.raises(RuntimeError, match="interrupted"):
        await service._workflow.ainvoke({"workflow_run_id": "original-quota-id"}, config)
    public = await service.get_public_state(context, novel)
    assert public["next_nodes"] == []
    assert public.get("has_pending_checkpoint") is True
    saver.fail_snapshot = False
    events = [event async for event in service.stream_events(context, novel, is_restart=True)]
    saved = await service._workflow.aget_state(config)
    assert saved.values["reviewed"] is True and initialized == [True]
    assert events[-1].type == "completed"
