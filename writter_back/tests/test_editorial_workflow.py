"""Real reflection/archive boundaries with only the paid provider doubled."""

from types import SimpleNamespace
from importlib import import_module
from unittest.mock import AsyncMock

import pytest

from application.agents.persist_node import _completed_chapter, _writing_command, persist_node
from application.agents.reflection_node import reflection_node
from application.creative.runtime import run_creative_node
from tests.creative_fakes import CreativeRepositoryFake, creative_config
from tests.test_editorial_ledger import BODY
from tests.test_editorial_review import EditorialLLM, review_api


def state_for(body=BODY):
    return {"author_mode": "autonomous_v1", "current_chapter_index": 0,
        "current_chapter_content": body, "chapter_outlines": [{}],
        "total_outline": {}, "revision_attempts": 0}


def literary_report():
    return {"overall_quality_score": .99,
        "word_count_analysis": {"total_count": len(BODY), "effective_density": 95,
            "is_valid_word_count": True}, "issues": []}


async def review_to_command(state, config, invoke=reflection_node):
    for _ in range(3):
        command = await invoke(state, config)
        state = {**state, **(command.update or {})}
        if command.goto != "reflection_node":
            return command
    raise AssertionError("editorial phases did not finish within their fixed boundary")


@pytest.mark.asyncio
async def test_high_literary_score_cannot_archive_hard_source_bound_defects():
    llm = EditorialLLM()
    llm.responses.append(literary_report())
    config = {"configurable": {"auto_mode": True, "llm_config": {"llm_instance": llm}}}
    command = await review_to_command(state_for(), config)
    assert command.goto == "revision_node"
    assert command.update["quality_gate"]["score"] == .99
    assert {i["type"] for i in command.update["reflection_issues"]} == {
        "editorial_unit", "editorial_action_state"}
    assert command.update["creative_editorial_review"]["body_sha256"]


@pytest.mark.asyncio
async def test_editorial_receipt_survives_later_literary_failure():
    llm = EditorialLLM()
    llm.responses += [{}, {}]
    config = {"configurable": {"llm_config": {"llm_instance": llm}}}
    command = await review_to_command(state_for(), config)
    assert command.goto == "reflection_review_node"
    assert command.update["pending_proposal"]["payload"]["status"] == "unavailable"
    receipt = command.update["creative_editorial_review"]
    assert review_api().editorial_receipt_valid(receipt, BODY)
    resumed = {**state_for(), **command.update, "pending_proposal": None}
    llm.responses = [literary_report()]
    second = await reflection_node(resumed, config)
    assert second.update["creative_editorial_review"] == receipt
    assert len(llm.calls) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing", "stale", "blocked", "tampered"])
async def test_archive_rechecks_receipt_before_goal_fact_or_database_work(case, monkeypatch):
    state = state_for()
    if case != "missing":
        receipt = await review_api().review_editorial(EditorialLLM(), BODY, None)
        state["creative_editorial_review"] = receipt
        if case == "stale":
            state["current_chapter_content"] += "\n她翻了下一页。"
        if case == "tampered":
            receipt["report"]["findings"] = []
    facts = AsyncMock(side_effect=AssertionError("must not reach fact gate"))
    monkeypatch.setattr(import_module("application.agents.persist_node"), "check_fact_artifact", facts)
    command = await persist_node(state, {"configurable": {}})
    assert command.goto == "reflection_node"
    assert command.update["pending_proposal"] is None
    facts.assert_not_called()


@pytest.mark.asyncio
async def test_current_receipt_is_saved_in_chapter_and_cleared_after_archive():
    body = "纸页略薄。"
    raw = {"coverage": ["p1"], "ledger": [], "findings": [], "action_checks": []}
    receipt = await review_api().review_editorial(EditorialLLM([
        raw, {"quantity_checks": []}]), body, None)
    state = state_for(body)
    state["creative_editorial_review"] = receipt
    chapter = _completed_chapter(state, body, 0)
    assert chapter["user_decision"]["editorial_review"] == receipt
    command = _writing_command(state, chapter, 100, True)
    assert command.update["creative_editorial_review"] is None


@pytest.mark.asyncio
async def test_real_input_seeder_discards_client_receipt():
    from api.routers.workflow_router import _seed_creative_input
    data = {"creative_editorial_review": {"status": "forged"}, "author_mode": "autonomous_v1"}
    await _seed_creative_input(data, None, SimpleNamespace(), SimpleNamespace(), "unused")
    assert "creative_editorial_review" not in data
    assert "author_mode" not in data


class MeteredEditorialLLM(EditorialLLM):
    async def structured_generate(self, *args, **kwargs):
        from service.ports.model_meter import active_model_meter
        meter = active_model_meter.get()
        request = await meter.reserve()
        try:
            return await super().structured_generate(*args, **kwargs)
        finally:
            await meter.finish(request, {})


@pytest.mark.asyncio
async def test_new_review_calls_remain_in_real_reflection_chapter_bucket():
    repository, llm = CreativeRepositoryFake(), MeteredEditorialLLM()
    config = creative_config(repository, llm)
    state = state_for()
    state["creative_session_id"] = repository.session["id"]
    llm.responses.append(literary_report())
    async def invoke(current, bound_config):
        return await run_creative_node("reflection_node", reflection_node, True, current, bound_config)
    command = await review_to_command(state, config, invoke)
    assert command.goto == "revision_node"
    assert repository.session["counters"] == {"chapter:1": 3}
    assert "review" not in repository.session["counters"]


@pytest.mark.asyncio
async def test_valid_receipt_does_not_replace_existing_goal_acceptance():
    from tests.test_goal_contract import goal_state
    from application.errors import QualityGateReviewRequired
    state = goal_state()
    state["author_mode"] = "autonomous_v1"
    from application.editorial_actions import action_catalog
    raw = {"coverage": ["p1"], "ledger": [], "findings": [], "action_checks": [
        {"id": row["id"], "object": "test action", "state": "performed",
            "previous_id": None, "status": "consistent", "reason": "Single paragraph"}
        for row in action_catalog(state["current_chapter_content"])]}
    state["creative_editorial_review"] = await review_api().review_editorial(
        EditorialLLM([raw, {"quantity_checks": []}]), state["current_chapter_content"], None)
    with pytest.raises(QualityGateReviewRequired, match="目标验收"):
        await persist_node(state, {"configurable": {}})


def reflection_graph(node):
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
    from application.schemas.agent_state import NovelAgentState
    graph = StateGraph(NovelAgentState)
    destinations = ("reflection_node", "revision_node", "persist_node", "reflection_review_node")
    graph.add_node("reflection_node", node, destinations=destinations)
    for destination in destinations[1:]:
        graph.add_node(destination, lambda state: {})
        graph.add_edge(destination, END)
    graph.add_edge(START, "reflection_node")
    return graph.compile(checkpointer=InMemorySaver())


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["provider", "physical_budget"])
async def test_real_graph_keeps_paid_receipt_before_literary_failure(failure):
    from application.runtime_observability import measured_node
    repository, llm = CreativeRepositoryFake(), MeteredEditorialLLM()
    config = creative_config(repository, llm)
    config["configurable"]["thread_id"] = "editorial-" + failure
    state = state_for()
    state["creative_session_id"] = repository.session["id"]
    graph = reflection_graph(measured_node("reflection_node", reflection_node))
    if failure == "physical_budget":
        repository.session["limits"]["chapter"] = 2
        await graph.ainvoke(state, config)
    else:
        with pytest.raises(IndexError):
            await graph.ainvoke(state, config)
    checkpoint = await graph.aget_state(config)
    assert review_api().editorial_receipt_valid(
        checkpoint.values.get("creative_editorial_review"), BODY)
    assert len(llm.calls) == (3 if failure == "provider" else 2)


@pytest.mark.asyncio
async def test_real_graph_keeps_observation_when_quantity_budget_is_unavailable():
    from application.runtime_observability import measured_node
    repository, llm = CreativeRepositoryFake(), MeteredEditorialLLM()
    repository.session["limits"]["chapter"] = 1
    config = creative_config(repository, llm)
    config["configurable"]["thread_id"] = "editorial-partial"
    state = state_for()
    state["creative_session_id"] = repository.session["id"]
    graph = reflection_graph(measured_node("reflection_node", reflection_node))
    await graph.ainvoke(state, config)
    checkpoint = await graph.aget_state(config)
    receipt = checkpoint.values.get("creative_editorial_review")
    assert receipt and receipt.get("observations", {}).get("coverage") == ["p1", "p2", "p3"]
    assert not review_api().editorial_receipt_valid(receipt, BODY)
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_progress_policy_pauses_after_two_invalid_reports_without_whole_review_retries():
    from application.runtime_observability import measured_node

    repository, llm = CreativeRepositoryFake(), MeteredEditorialLLM([{}, {}])
    repository.session["config"]["repair_policy"] = {"version": 1, "mode": "progress_v1"}
    config = creative_config(repository, llm)
    config["configurable"]["thread_id"] = "editorial-progress-invalid"
    state = state_for()
    state["creative_session_id"] = repository.session["id"]
    graph = reflection_graph(measured_node("reflection_node", reflection_node))
    result = await graph.ainvoke(state, config)
    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["reason"] == "editorial_evidence_invalid"
    assert len(llm.calls) == 2
    assert repository.session["counters"] == {"review": 2}
    checkpoint = await graph.aget_state(config)
    assert checkpoint.values["current_chapter_content"] == BODY
    assert not checkpoint.values.get("pending_proposal")
    assert not (checkpoint.values.get("automatic_recovery") or {}).get("attempts")
