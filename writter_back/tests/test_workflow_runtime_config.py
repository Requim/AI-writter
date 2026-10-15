"""Compiled graphs must inject trusted runtime configuration into every wrapper."""

import asyncio
from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
import pytest

from application.runtime_observability import measured_node
from application.workflow_builder import create_novel_workflow
from tests.test_creative_repository import seed_creative


@pytest.mark.asyncio
async def test_autonomous_entry_uses_real_graph_runtime_and_stops_before_provider_calls(
    repository, tenant_context, sample_novel, monkeypatch,
):
    creative, tenant, novel = await seed_creative(
        repository, tenant_context, sample_novel, monkeypatch)
    session = await creative.get_session(tenant, novel)
    graph = create_novel_workflow(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "autonomous-config-probe",
                              "tenant_id": tenant, "novel_id": novel,
                              "creative_repository": creative, "auto_mode": True}}
    result = await graph.ainvoke({
        "novel_id": novel, "novel_type": "suspense", "author_mode": "autonomous_v1",
        "creative_session_id": session["id"], "current_chapter_index": 0,
        "target_total_chapters": 6,
    }, config=config, interrupt_after=["type_confirmation"])
    saved = await graph.aget_state(config)
    assert result["novel_type"] == "suspense"
    assert saved.next == ("research_material_node",)
    assert (await creative.get_session(tenant, novel))["counters"] == {}


class SimpleWork(TypedDict):
    completed: bool


@pytest.mark.asyncio
async def test_state_only_node_still_receives_automatic_background_deadline(monkeypatch):
    monkeypatch.setattr("config.settings.WORKFLOW_NODE_TIMEOUT_SECONDS", 0.001)
    monkeypatch.setattr("config.settings.WORKFLOW_BACKGROUND_NODE_TIMEOUT_SECONDS", 1)

    async def state_only_node(state: SimpleWork):
        await asyncio.sleep(0.03)
        return {"completed": True}

    builder = StateGraph(SimpleWork)
    builder.add_node("step", measured_node("step", state_only_node))
    builder.add_edge(START, "step")
    builder.add_edge("step", END)
    result = await builder.compile().ainvoke(
        {"completed": False}, config={"configurable": {"auto_mode": True}})
    assert result["completed"] is True
