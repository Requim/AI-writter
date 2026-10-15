"""Planning requests must receive admitted author intent and all volume boundaries."""

from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from application.agents.novel_plan_node import (
    novel_plan_initialize_node,
    novel_plan_volume_node,
)
from application.creative.artifacts import workspace
from application.creative.errors import CreativePause
from application.prompts.template_loader import reset_prompt_snapshot, set_prompt_snapshot
from application.proposals import proposal_update
from api.routers.workflow_router import WorkflowInvokeRequest, _prepare_request
from tests.creative_fakes import CreativeRepositoryFake, creative_config
from tests.test_novel_planning_workflow import (
    PlanningLLM, PlanRepository, _generated_plan, _state, _tenant_context,
)


class CapturingPlanner(PlanningLLM):
    def __init__(self):
        super().__init__(80, 336_000)
        self.prompts = []

    async def structured_generate(self, prompt, schema, **kwargs):
        self.prompts.append(prompt)
        return await super().structured_generate(prompt, schema, **kwargs)


async def _fixture():
    repo, llm = CreativeRepositoryFake(chapters=80), CapturingPlanner()
    repo.session["config"]["hard_constraints"] = ["故事关闭主线，不恢复全部名誉。"]
    cfg = creative_config(repo, llm)
    cfg["configurable"].update(
        novel_repository=PlanRepository(), auto_mode=True, novel_planning_v1_enabled=True,
    )
    work = await workspace(cfg)
    await work.save("selection", "accepted", {
        "brief": {
            "core_premise": "恢复水权需要公开陆守潮的程序过失。",
            "research_material": [{"text": "父亲陆守潮承担责任。"}],
        },
        "engine": {
            "conflict_nodes": [{
                "choice": "保水权或完全保名誉", "consequence": "陆守潮留过失，水权恢复。",
            }],
            "sources": [{"text": "父亲陆守潮承担责任。"}],
        },
    }, status="accepted")
    state = _state(80, 336_000)
    state.update(author_mode="autonomous_v1", total_outline={
        **state["total_outline"],
        "main_plot": {"false_dilemma": "更正与水权互斥"},
        "main_characters": [{
            "character_id": "father", "name": "贺兰亭",
            "source_name_binding": {"name": "陆守潮", "quote": "父亲陆守潮承担责任。"},
        }],
    })
    return repo, llm, cfg, state


def _context(prompt):
    section = prompt.split("\n【规划来源与全局边界数据】\n", 1)[1]
    return json.JSONDecoder().raw_decode(section)[0]


@pytest.mark.asyncio
async def test_initial_blueprint_receives_admitted_source_not_old_generated_dilemma():
    repo, llm, cfg, state = await _fixture()
    original = deepcopy(state)
    command = await novel_plan_initialize_node(state, cfg)
    context = _context(llm.prompts[0])
    truth = context["author_truth"]
    assert truth["engine"]["conflict_nodes"][0] == {
        "choice": "保水权或完全保名誉", "consequence": "贺兰亭留过失，水权恢复。",
    }
    assert truth["engine"]["sources"] == [{"text": "父亲陆守潮承担责任。"}]
    assert truth["author_constraints"]["hard_constraints"] == ["故事关闭主线，不恢复全部名誉。"]
    assert "false_dilemma" not in json.dumps(truth)
    assert command.update["plan_generation"]["author_truth"] == truth
    assert state == original
    assert len(repo.rows) == 1


@pytest.mark.asyncio
async def test_every_volume_receives_full_blueprint_and_same_author_truth_after_resume():
    repo, llm, cfg, state = await _fixture()
    initialized = await novel_plan_initialize_node(state, cfg)
    state.update(initialized.update)
    blueprint = state["plan_generation"]["blueprint"]
    blueprint["volumes"][-1]["opening_state"] = "第61章引用第28章已完成的鉴定，不重新等待。"
    baseline = deepcopy(blueprint)
    for volume in baseline["volumes"]:
        volume.pop("setup_ids")
        volume.pop("payoff_ids")
    first = await novel_plan_volume_node(state, cfg)
    first_context = _context(llm.prompts[-1])
    assert first_context["blueprint"] == baseline
    assert len(first_context["blueprint"]["volumes"]) == 4
    assert first_context["blueprint"]["volumes"][-1]["opening_state"] == (
        "第61章引用第28章已完成的鉴定，不重新等待。"
    )
    state.update(first.update)
    # Older checkpoints lack the derived context; resolve it from admitted records.
    state["plan_generation"].pop("author_truth")
    resumed = await novel_plan_volume_node(state, cfg)
    resumed_context = _context(llm.prompts[-1])
    assert resumed_context["author_truth"] == first_context["author_truth"]
    assert resumed_context["blueprint"] == first_context["blueprint"]
    assert len(resumed_context["prior_planned_events"]) == 25
    assert resumed.update["plan_generation"]["author_truth"] == first_context["author_truth"]
    assert len(repo.rows) == 1


@pytest.mark.asyncio
async def test_legacy_prompt_snapshot_does_not_drop_current_planning_context():
    _repo, llm, cfg, state = await _fixture()
    token = set_prompt_snapshot({
        "outline/plan_blueprint.txt": "OLD BLUEPRINT $scale $outline $existing_plan $instruction $legacy_chapters $validation_errors",
        "outline/plan_volume_slots.txt": "OLD VOLUME $volume",
    })
    try:
        initialized = await novel_plan_initialize_node(state, cfg)
        state.update(initialized.update)
        await novel_plan_volume_node(state, cfg)
    finally:
        reset_prompt_snapshot(token)
    assert llm.prompts[0].startswith("OLD BLUEPRINT")
    assert _context(llm.prompts[0])["author_truth"]["selection_version"] == 1
    assert llm.prompts[1].startswith("OLD VOLUME")
    assert len(_context(llm.prompts[1])["blueprint"]["volumes"]) == 4


@pytest.mark.asyncio
async def test_missing_admitted_selection_pauses_without_model_call():
    repo, llm, cfg, state = await _fixture()
    repo.rows.clear()
    with pytest.raises(CreativePause, match="立项"):
        await novel_plan_initialize_node(state, cfg)
    assert not llm.prompts


@pytest.mark.asyncio
async def test_legacy_manual_planning_does_not_require_author_workspace():
    llm = CapturingPlanner()
    cfg = {"configurable": {
        "llm_config": {"llm_instance": llm}, "novel_repository": PlanRepository(),
        "auto_mode": True, "novel_planning_v1_enabled": True,
    }}
    command = await novel_plan_initialize_node(_state(80, 336_000), cfg)
    assert command.goto == "novel_plan_volume_node"
    assert "规划来源与全局边界数据" not in llm.prompts[0]


@pytest.mark.asyncio
async def test_planning_brief_projects_admitted_names_but_retains_original_sources():
    repo, llm, cfg, state = await _fixture()
    before = deepcopy(repo.rows)
    await novel_plan_initialize_node(state, cfg)
    brief = _context(llm.prompts[0])["author_truth"]["brief"]
    assert brief["core_premise"] == "恢复水权需要公开贺兰亭的程序过失。"
    assert brief["research_material"] == [{"text": "父亲陆守潮承担责任。"}]
    assert repo.rows == before


@pytest.mark.asyncio
async def test_explicit_replan_starts_fresh_batch_instead_of_reusing_rejected_proposal(monkeypatch):
    monkeypatch.setattr("api.routers.workflow_router.settings.NOVEL_PLANNING_V1_ENABLED", True)
    repo, llm, cfg, state = await _fixture()
    plan, *_ = await _generated_plan(80, 336_000)
    state.update(novel_plan=plan.to_dict(), current_chapter_content="已有首章草稿",
                 plan_generation={"expected_version": 1, "mode": "replan"},
                 plan_feedback="旧反馈")
    state.update(proposal_update(state, "novel_plan", {"plan": plan.to_dict()}))
    repo.session["counters"] = {"preparation": 27, "chapter:1": 13, "review": 12}
    before = deepcopy(state)
    service = SimpleNamespace(
        repository=SimpleNamespace(get_latest_plan=AsyncMock(return_value=plan)),
        get_workflow_run_id=AsyncMock(return_value="old-run"),
        set_auto_mode=lambda *_args: None,
    )
    fresh, *_ = await _prepare_request(
        WorkflowInvokeRequest(command={"plan_replan": {
            "expected_version": 1, "scope": "future", "instruction": "修复全局时间与取舍矛盾",
        }, "_auto_mode": True}),
        _tenant_context(planning=True), str(uuid4()), service,
        SimpleNamespace(reserve=AsyncMock()), command_id="fresh-replan-command",
    )
    resumed = {**state, **fresh}
    command = await novel_plan_initialize_node(resumed, cfg)
    assert command.goto == "novel_plan_volume_node"
    assert command.update["plan_generation"]["instruction"] == "修复全局时间与取舍矛盾"
    assert command.update["plan_generation"]["expected_version"] == 1
    assert resumed["pending_proposal"] is None
    assert resumed["pending_proposal_decision"] is None
    assert resumed["current_chapter_content"] == "已有首章草稿"
    assert resumed["novel_plan"] == before["novel_plan"]
    assert repo.session["counters"] == {"preparation": 27, "chapter:1": 13, "review": 12}
    assert state == before


@pytest.mark.asyncio
async def test_later_volume_retains_earlier_resource_and_completed_event_history():
    _repo, llm, cfg, state = await _fixture()
    state.update((await novel_plan_initialize_node(state, cfg)).update)
    state.update((await novel_plan_volume_node(state, cfg)).update)
    generation = state["plan_generation"]
    generation["chapter_slots"][8]["must_happen"] = ["一次合规人情在第9章消耗，不再授予。"]
    generation["chapter_slots"][13]["planned_state_delta"] = "第14章证人唯一证词已录入，后章仅引用。"
    generation["chapter_slots"].append({
        "chapter_number": 80, "volume_id": "volume-4",
        "must_happen": ["未来章保留的事件，不得当作前卷既有状态。"],
    })
    before = deepcopy(generation)
    await novel_plan_volume_node(state, cfg)
    history = _context(llm.prompts[-1])["prior_planned_events"]
    assert len(history) == 25
    assert history[8]["must_happen"] == ["一次合规人情在第9章消耗，不再授予。"]
    assert history[13]["planned_state_delta"] == "第14章证人唯一证词已录入，后章仅引用。"
    assert all(slot["chapter_number"] < 26 for slot in history)
    assert history[8]["chapter_number"] == 9
    assert "target_words" not in history[8]
    assert generation == before
