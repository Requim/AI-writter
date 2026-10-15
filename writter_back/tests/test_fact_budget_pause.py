"""Actual PostgreSQL budget denial must remain a resumable graph pause."""

from uuid import UUID

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from application.fact_gate_workflow import check_fact_artifact, fact_review_node
from application.runtime_observability import measured_node
from application.schemas.agent_state import NovelAgentState
from service.ports.model_meter import active_model_meter
from tests.test_creative_repository import seed_creative
from tests.test_fact_gate import config, setup_gate


class MeteredJudge:
    async def structured_generate(self, **kwargs):
        await active_model_meter.get().reserve()
        raise AssertionError("Exhausted budget must stop before the provider")


async def check(state: NovelAgentState, config: RunnableConfig) -> Command:
    return await check_fact_artifact(
        state, config, state["current_chapter_content"], "body", Command(goto="done"))


def compiled():
    builder = StateGraph(NovelAgentState)
    builder.add_node("check", measured_node("check", check))
    builder.add_node("fact_review_node", measured_node("fact_review_node", fact_review_node))
    builder.add_node("done", lambda state: {"title": "must not archive"})
    builder.add_edge(START, "check")
    builder.add_edge("done", END)
    return builder.compile(checkpointer=InMemorySaver())


@pytest.mark.asyncio
async def test_database_budget_denial_retains_draft_and_interrupts_without_fact_retries(
    repository, tenant_context, sample_novel, monkeypatch,
):
    creative, tenant, novel = await seed_creative(repository, tenant_context, sample_novel, monkeypatch)
    for _ in range(32):
        await creative.reserve(tenant, novel, "chapter:1", "isolated-budget-fixture")
    session = await creative.get_session(tenant, novel)
    snapshot = setup_gate().model_copy(update={"tenant_id": UUID(tenant), "novel_id": UUID(novel)})
    cfg = config(snapshot, MeteredJudge())
    cfg["configurable"].update(creative_repository=creative, thread_id="budget-pause", auto_mode=True)
    result = await compiled().ainvoke({
        "author_mode": "autonomous_v1", "creative_session_id": session["id"],
        "current_chapter_content": "他推开门。", "current_chapter_index": 0,
    }, cfg)
    assert result["__interrupt__"][0].value["reason"] == "budget_exhausted"
    assert result["current_chapter_content"] == "他推开门。"
    assert not result.get("fact_reports") and not result.get("automatic_recovery")
    assert not result.get("fact_acknowledgements") and not result.get("last_persisted_chapter")
    assert (await creative.get_session(tenant, novel))["counters"] == {"chapter:1": 32}
