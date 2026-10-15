"""Exercise the production wrapper stack without paid generation."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from application.creative.runtime import creative_node_scope, run_creative_node
from application.errors import QualityGateReviewRequired
from application.goal_contract import compile_goal_contract, current_goal_contract, goal_prompt
from application.schemas.agent_state import NovelAgentState
from tests.creative_fakes import CreativeRepositoryFake, creative_config
from tests.test_goal_contract import goal_state


def scoped_goal():
    repository = CreativeRepositoryFake()
    repository.session["config"]["hard_constraints"] = ["不增加超自然力量"]
    state = goal_state()
    state.update(author_mode="autonomous_v1", creative_session_id=repository.session["id"],
                 author_config=deepcopy(repository.session["config"]),
                 creative_brief={"core_premise": "未来秘密不可泄漏", "reader_promise": "当章归还失物"})
    state["total_outline"] = {"creative_brief": deepcopy(state["creative_brief"]), "main_characters": []}
    state["chapter_outlines"][0]["goal_contract"] = compile_goal_contract(state)
    return state, repository, creative_config(repository, SimpleNamespace())


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["chapter_writer_node", "revision_node"])
async def test_prose_projection_keeps_server_goal_validation_without_future_prompt_truth(name):
    state, _, config = scoped_goal()
    bound = state["chapter_outlines"][0]["goal_contract"]
    async with creative_node_scope(name, state, config) as (projected, _):
        assert current_goal_contract(projected) == bound
        assert "未来秘密不可泄漏" not in str(projected)
        prompt = goal_prompt(projected["chapter_outlines"][0].get("goal_contract"))
        assert "查出原册页" in prompt and "不增加超自然力量" in prompt
        assert "未来秘密不可泄漏" not in prompt
    assert current_goal_contract(state) == bound


@pytest.mark.asyncio
async def test_changed_accepted_goal_is_rejected_before_prose_node_can_generate():
    state, _, config = scoped_goal()
    state["novel_plan"]["chapter_slots"][0]["must_happen"] = ["不再归还失物"]

    async def writer(projected, config):
        current_goal_contract(projected)
        return Command(goto=END, update={"current_chapter_content": "不能生成"})

    with pytest.raises(QualityGateReviewRequired, match="目标来源已变化"):
        await run_creative_node("chapter_writer_node", writer, True, state, config)
    assert state["current_chapter_content"] != "不能生成"


@pytest.mark.asyncio
async def test_production_material_wrapper_never_persists_projected_author_context(monkeypatch):
    import application.workflow_builder as workflow
    state, _, config = scoped_goal()
    original = deepcopy(state)

    async def writer(projected, config):
        assert "未来秘密不可泄漏" not in str(projected)
        return Command(goto=END, update={"current_chapter_content": "正文保留"})

    monkeypatch.setattr(workflow, "WORKFLOW_NODES", {"chapter_writer_node": writer})
    graph = StateGraph(NovelAgentState)
    workflow._add_nodes(graph)
    graph.add_edge(START, "chapter_writer_node")
    compiled = graph.compile(checkpointer=InMemorySaver())
    config["configurable"]["thread_id"] = "production-projection"
    result = await compiled.ainvoke(state, config)
    assert result["creative_brief"]["core_premise"] == "未来秘密不可泄漏"
    assert result["total_outline"]["creative_brief"]["reader_promise"] == "当章归还失物"
    assert result["current_chapter_content"] == "正文保留"
    assert state == original


@pytest.mark.asyncio
async def test_existing_approved_material_is_not_dropped_or_rebound_for_prose():
    state, _, config = scoped_goal()
    material = {"status": "applied", "digest": "known-digest", "knowledge_version_id": "approved-1",
                "writing_guidance": ["用原件核对编号"]}
    state["total_outline"]["creative_brief"]["research_material"] = material
    state["creative_brief"]["research_material"] = material
    async with creative_node_scope("chapter_writer_node", state, config) as (projected, _):
        assert projected["creative_brief"].get("research_material") == material


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["unchanged", "changed_truth", "wrong_scope"])
async def test_lost_goal_sources_recover_only_from_matching_persisted_novel(mutation):
    state, _, config = scoped_goal()
    original_brief = deepcopy(state["creative_brief"])
    bound = deepcopy(state["chapter_outlines"][0]["goal_contract"])
    state["creative_brief"] = {"tone": "克制"}
    state["total_outline"]["creative_brief"] = {"tone": "克制"}
    values = config["configurable"]
    if mutation == "changed_truth":
        original_brief["reader_promise"] = "不再归还失物"
    saved = SimpleNamespace(id=values["novel_id"], tenant_id=values["tenant_id"],
        total_outline=SimpleNamespace(creative_brief=original_brief))
    if mutation == "wrong_scope":
        saved.tenant_id = "other-tenant"
    values["novel_repository"] = SimpleNamespace(find_by_id=AsyncMock(return_value=saved))

    async def review(projected, config):
        assert current_goal_contract(projected) == bound
        return Command(goto=END, update={"current_chapter_content": "既有正文"})

    if mutation == "unchanged":
        result = await run_creative_node("reflection_node", review, True, state, config)
        restored = {**state, **result.update}
        assert current_goal_contract(restored) == bound
        assert restored["current_chapter_content"] == "既有正文"
        assert restored["creative_brief"]["reader_promise"] == "当章归还失物"
    else:
        with pytest.raises(QualityGateReviewRequired):
            await run_creative_node("reflection_node", review, True, state, config)
    assert state["creative_brief"] == {"tone": "克制"}
