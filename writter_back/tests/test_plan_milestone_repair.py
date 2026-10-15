"""A failed milestone is repaired without regenerating unrelated plan layers."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from api.routers.workflow_router import WorkflowInvokeRequest, _plan_replan_command, _prepare_request
from application.agents.character_design_node import character_design_node
from application.agents.novel_plan_node import novel_plan_initialize_node, novel_plan_review_node
from application.agents.outline_generator_node import outline_generator_node
from application.creative.artifacts import workspace
from application.creative.errors import CreativeConflict, CreativePause
from application.creative.evidence import content_hash
from application.creative.plan_consistency import _audit_context
from application.proposals import proposal_update
from application.orchestrator import NovelOrchestrator
from application.schemas.agent_state import NovelAgentState
from service.value_objects.novel_plan import NovelPlan
from tests.test_plan_consistency_audit import _fixture
from tests.test_novel_planning_workflow import _tenant_context


async def _repair_fixture(*, metadata=False, completed=0, point_chapter=35, setup=False):
    repo, llm, cfg, plan, state = _fixture()
    plan.version = 1
    plan.chapter_slots[35].must_happen = ["名册编号首次与旧水债直接勾连。"]
    state["novel_plan"] = plan.to_dict()
    state["current_chapter_index"] = completed
    state["current_chapter_content"] = "已有草稿不能改写。"
    plan.arcs[0].escalation_points = [{
        "chapter_number": point_chapter, "change": "名册编号首次与旧水债直接勾连。",
    }]
    if metadata:
        plan.arcs[0].escalation_points[0].update(
            stage="recorded", evidence_id="opaque-evidence-35", condition={"required": True},
        )
    state["plan_generation"] = {"mode": "replan", "expected_version": 1}
    state.update(proposal_update(state, "novel_plan", {"plan": plan.to_dict()}))
    source_id = state["pending_proposal"]["proposal_id"]
    state["plan_replan_request"] = {
        "expected_version": 1, "scope": "future", "instruction": "对齐复审指出的节点，其他计划不变。",
        "repair_proposal_id": source_id,
    }
    if setup:
        state.update(
            workflow_schema_version=5, novel_type="suspense", character_design_return_to="outline_node",
            total_outline={"story_background": "架空水城。", "total_chapters": 80,
                           "main_characters": [{"姓名": "沈秋菊", "性格": "谨慎", "目标": "查案"}]},
        )
    work = await workspace(cfg)
    report = {
        "coverage": "complete", "timeline_pass": True, "single_use_pass": True,
        "cross_layer_pass": False, "ending_causality_pass": True,
        "issues": [{
            "code": "cross_layer", "description": "弧定位35，实际槽位36。", "suggestion": "定位36。",
            "evidence": [
                {"path": "/plan/arcs/0/escalation_points/0/change",
                 "quote": "名册编号首次与旧水债直接勾连。"},
                {"path": "/plan/chapter_slots/35/must_happen/0",
                 "quote": "名册编号首次与旧水债直接勾连。"},
            ],
        }], "summary": "其他判据通过，节点相差一章。",
    }
    context = await _audit_context(work, state, plan, cfg)
    await work.save("decision", "plan_consistency:" + source_id, report,
                    inputs={"context_hash": content_hash(context)}, status="reviewed")
    llm.structured_generate.return_value = {"changes": [{
        "path": "/plan/arcs/0/escalation_points/0/change",
        "before": "名册编号首次与旧水债直接勾连。",
        "after": "名册编号首次与旧水债直接勾连。", "chapter_number": 36,
    }]}
    return repo, llm, cfg, plan, state


@pytest.mark.asyncio
async def test_explicit_patch_changes_only_reported_milestone_and_preserves_draft():
    repo, llm, cfg, plan, state = await _repair_fixture()
    before = deepcopy(state)
    command = await novel_plan_initialize_node(state, cfg)
    assert command.goto == "novel_plan_review_node"
    assert command.update and "pending_proposal" in command.update
    revised = command.update["pending_proposal"]
    assert revised["proposal_id"] != state["pending_proposal"]["proposal_id"]
    expected = plan.to_dict()
    expected["arcs"][0]["escalation_points"][0]["chapter_number"] = 36
    assert revised["payload"]["plan"] == expected
    assert state == before
    assert repo.session["counters"] == {}
    assert len(repo.rows) == 2
    assert llm.structured_generate.await_count == 1


@pytest.mark.asyncio
async def test_same_patch_replay_uses_saved_model_result():
    repo, llm, cfg, _plan, state = await _repair_fixture()
    first = await novel_plan_initialize_node(state, cfg)
    again = await novel_plan_initialize_node(state, cfg)
    assert first.update and again.update
    assert first.update["pending_proposal"]["payload"] == again.update["pending_proposal"]["payload"]
    assert llm.structured_generate.await_count == 1
    assert len(repo.rows) == 2


@pytest.mark.asyncio
async def test_changed_author_context_cannot_reuse_review_for_patch():
    repo, llm, cfg, _plan, state = await _repair_fixture()
    repo.session["config"]["hard_constraints"] = ["新增硬约束。"]
    with pytest.raises(CreativeConflict, match="输入"):
        await novel_plan_initialize_node(state, cfg)
    assert llm.structured_generate.await_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["uncited", "wrong_before", "outside", "empty", "duplicate"])
async def test_invalid_patch_is_retained_and_never_accepted(mutation):
    repo, llm, cfg, _plan, state = await _repair_fixture()
    result = llm.structured_generate.return_value
    change = result["changes"][0]
    operations = {
        "uncited": lambda: change.update(path="/plan/ending_contract/final_state"),
        "wrong_before": lambda: change.update(before="不存在的原文。"),
        "outside": lambda: change.update(chapter_number=81),
        "empty": lambda: result.update(changes=[]),
        "duplicate": lambda: result["changes"].append(deepcopy(change)),
    }
    operations[mutation]()
    before = deepcopy(state)
    for _ in range(2):
        with pytest.raises(CreativePause):
            await novel_plan_initialize_node(state, cfg)
    assert state == before
    assert llm.structured_generate.await_count == 1
    assert repo.rows[-1]["payload"] == result


def test_future_replan_retains_explicit_source_proposal_identity():
    source = "212324be-feff-4228-af5c-179511c6278d"
    result = _plan_replan_command({
        "expected_version": 1, "scope": "future", "instruction": "修复已核实的节点。",
        "repair_proposal_id": source,
    })
    assert result["repair_proposal_id"] == source


@pytest.mark.parametrize("source,scope", [("invalid", "future"), (True, "future"),
                                         ("212324be-feff-4228-af5c-179511c6278d", "scale")])
def test_patch_command_rejects_invalid_or_scale_changing_intent(source, scope):
    with pytest.raises(HTTPException) as error:
        _plan_replan_command({
            "expected_version": 1, "scope": scope, "instruction": "修复。",
            "repair_proposal_id": source,
        })
    assert error.value.status_code == 422


def _service(state):
    plan = NovelPlan.from_dict(state["novel_plan"])
    service = NovelOrchestrator(
        repository=SimpleNamespace(get_latest_plan=AsyncMock(return_value=plan)),
        memory_service=SimpleNamespace(), llm_config={},
    )
    service._workflow = SimpleNamespace(aget_state=AsyncMock(return_value=SimpleNamespace(
        values=state, next=("novel_plan_review_node",), tasks=(),
    )))
    return service


@pytest.mark.asyncio
async def test_api_seeds_named_proposal_from_private_checkpoint_not_client_json(monkeypatch):
    monkeypatch.setattr("api.routers.workflow_router.settings.NOVEL_PLANNING_V1_ENABLED", True)
    _repo, _llm, _cfg, _plan, state = await _repair_fixture()
    state["workflow_schema_version"] = 5
    before = deepcopy(state)
    service = _service(state)
    result, *_ = await _prepare_request(
        WorkflowInvokeRequest(command={"plan_replan": state["plan_replan_request"], "_auto_mode": True}),
        _tenant_context(planning=True), str(uuid4()), service,
        SimpleNamespace(reserve=AsyncMock()), command_id="bounded-patch",
    )
    assert result["pending_proposal"] == state["pending_proposal"]
    assert result["plan_generation"] == state["plan_generation"]
    result["pending_proposal"]["payload"]["plan"]["arcs"][0]["goal"] = "不得回写仓储。"
    assert state == before


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["stale_id", "stale_version", "manual", "custom_input"])
async def test_api_rejects_untrusted_patch_before_quota_and_model(monkeypatch, problem):
    monkeypatch.setattr("api.routers.workflow_router.settings.NOVEL_PLANNING_V1_ENABLED", True)
    _repo, _llm, _cfg, _plan, state = await _repair_fixture()
    state["workflow_schema_version"] = 5
    request = deepcopy(state["plan_replan_request"])
    if problem == "stale_id":
        request["repair_proposal_id"] = str(uuid4())
    elif problem == "stale_version":
        request["expected_version"] = 2
    elif problem == "manual":
        state["author_mode"] = "manual"
    service, quota = _service(state), SimpleNamespace(reserve=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await _prepare_request(
            WorkflowInvokeRequest(
                command={"plan_replan": request, "_auto_mode": True},
                input={"pending_proposal": {"forged": True}} if problem == "custom_input" else None,
            ),
            _tenant_context(planning=True), str(uuid4()), service, quota, command_id="rejected-patch",
        )
    assert error.value.status_code == (422 if problem == "custom_input" else 409)
    quota.reserve.assert_not_awaited()
    assert service._llm_instance is None


@pytest.mark.asyncio
async def test_patched_proposal_requires_fresh_whole_plan_and_replan_audits():
    repo, llm, cfg, _plan, state = await _repair_fixture()
    raw_patch = deepcopy(llm.structured_generate.return_value)
    passed = {
        "coverage": "complete", "timeline_pass": True, "single_use_pass": True,
        "cross_layer_pass": True, "ending_causality_pass": True, "issues": [], "summary": "全量通过。",
    }
    llm.structured_generate.side_effect = [
        raw_patch, passed,
        {"hard_settings_pass": True, "responsibilities_pass": True, "foreshadow_pass": True,
         "reader_promises_pass": True, "reason": "约束未改变。", "change_mapping": []},
    ]
    patched = await novel_plan_initialize_node(state, cfg)
    state.update(patched.update)
    assert state["novel_plan"]["version"] == 1
    accepted = await novel_plan_review_node(state, cfg)
    assert accepted.update["novel_plan"]["version"] == 2
    assert accepted.update["novel_plan"]["arcs"][0]["escalation_points"][0]["chapter_number"] == 36
    assert len([r for r in repo.rows if r["key"].startswith("plan_consistency:")]) == 2
    assert len([r for r in repo.rows if r["key"].startswith("replan_audit:")]) == 1
    assert state["current_chapter_content"] == "已有草稿不能改写。"


@pytest.mark.asyncio
async def test_patch_failure_cannot_reset_consumed_automatic_repair_allowance():
    repo, llm, cfg, _plan, state = await _repair_fixture()
    work = await workspace(cfg)
    original_review = repo.rows[0]["payload"]
    await work.save("decision", "plan_consistency_repair:1", {
        "proposal_id": "earlier-failed-proposal", "report": original_review,
    }, source="system", status="requested")
    patched = await novel_plan_initialize_node(state, cfg)
    state.update(patched.update)
    llm.structured_generate.return_value = original_review
    with pytest.raises(CreativePause, match="修复后"):
        await novel_plan_review_node(state, cfg)
    assert state["novel_plan"]["version"] == 1
    assert len([r for r in repo.rows if r["key"] == "plan_consistency_repair:1"]) == 1


@pytest.mark.asyncio
async def test_repair_preserves_uncited_milestone_metadata():
    _repo, _llm, cfg, plan, state = await _repair_fixture(metadata=True)
    command = await novel_plan_initialize_node(state, cfg)
    expected = plan.to_dict()
    expected["arcs"][0]["escalation_points"][0]["chapter_number"] = 36
    assert command.update["pending_proposal"]["payload"]["plan"] == expected


@pytest.mark.asyncio
async def test_completed_milestone_cannot_be_rewritten_by_future_patch():
    _repo, llm, cfg, _plan, state = await _repair_fixture(completed=40)
    with pytest.raises(CreativePause, match="锁定"):
        await novel_plan_initialize_node(state, cfg)
    assert llm.structured_generate.await_count == 0


@pytest.mark.asyncio
async def test_future_milestone_cannot_move_into_locked_window():
    _repo, llm, cfg, _plan, state = await _repair_fixture(completed=40, point_chapter=50)
    llm.structured_generate.return_value["changes"][0]["chapter_number"] = 45
    with pytest.raises(CreativePause, match="锁定"):
        await novel_plan_initialize_node(state, cfg)
    assert llm.structured_generate.await_count == 1


@pytest.mark.asyncio
async def test_metadata_reuse_keeps_plan_proposal_until_real_repair_node():
    _repo, llm, cfg, _plan, state = await _repair_fixture(setup=True)
    original = deepcopy(state["pending_proposal"])
    character = await character_design_node(state, cfg)
    state.update(character.update)
    assert state["pending_proposal"] == original
    outline = await outline_generator_node(state, cfg)
    assert outline.goto == "novel_plan_initialize_node"
    state.update(outline.update)
    repaired = await novel_plan_initialize_node(state, cfg)
    assert repaired.goto == "novel_plan_review_node"
    assert repaired.update["pending_proposal"]["payload"]["plan"]["arcs"][0]["escalation_points"][0][
        "chapter_number"] == 36
    assert llm.structured_generate.await_count == 1


async def _lost_proposal_service(monkeypatch, *, mutation=None):
    monkeypatch.setattr("application.orchestrator.settings.NOVEL_PLANNING_V1_ENABLED", True)
    _repo, llm, cfg, _plan, state = await _repair_fixture()
    state["workflow_run_id"] = "original-repair-quota"
    service = _service(state)
    service._get_llm_instance = lambda: llm
    context = _tenant_context(planning=True)
    config = service._make_config(context, "lost-repair")
    config["configurable"].update(cfg["configurable"])
    monkeypatch.setattr(service, "_make_config", lambda *_args, **_kwargs: config)

    async def reuse_metadata(values):
        return {"pending_proposal": None}

    async def finish(values):
        return {}

    async def initialize(values):
        return await novel_plan_initialize_node(values, config)

    builder = StateGraph(NovelAgentState)
    builder.add_node("reuse_metadata", reuse_metadata)
    builder.add_node("novel_plan_initialize_node", initialize)
    builder.add_node("novel_plan_review_node", finish)
    builder.add_node("router_agent", finish)
    builder.add_edge(START, "reuse_metadata")
    builder.add_edge("reuse_metadata", "novel_plan_initialize_node")
    builder.add_edge("novel_plan_review_node", END)
    builder.add_conditional_edges("router_agent", lambda values: values["next_tool"])
    service._workflow = builder.compile(checkpointer=InMemorySaver())
    with pytest.raises(CreativeConflict, match="变化"):
        await service._workflow.ainvoke(state, config)
    if mutation:
        await service._workflow.aupdate_state(config, mutation, as_node="reuse_metadata")
    return service, context, config, state, llm


@pytest.mark.asyncio
@pytest.mark.parametrize("cleared_tasks", [False, True])
async def test_normal_retry_recovers_exact_proposal_from_same_run_history(monkeypatch, cleared_tasks):
    service, context, config, original, llm = await _lost_proposal_service(
        monkeypatch, mutation={"phase": "setup"} if cleared_tasks else None,
    )
    await service.prepare_retry_checkpoint(context, "lost-repair")
    resumed = await service._workflow.ainvoke(None, config)
    assert resumed["workflow_run_id"] == "original-repair-quota"
    assert resumed["current_chapter_content"] == original["current_chapter_content"]
    assert resumed["novel_plan"] == original["novel_plan"]
    assert resumed["pending_proposal"]["proposal_id"] != original["pending_proposal"]["proposal_id"]
    assert resumed["pending_proposal"]["payload"]["plan"]["arcs"][0]["escalation_points"][0][
        "chapter_number"] == 36
    assert llm.structured_generate.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    {"workflow_run_id": "another-run"},
    {"current_chapter_content": "作者已更新正文。"},
    {"current_chapter_index": 1},
    {"proposal_versions": {"novel_plan": 99}},
    {"author_mode": "manual"},
    {"novel_plan": {"version": 2}},
    {"plan_generation": {"mode": "replan", "expected_version": 1, "source": "changed"}},
    {"plan_replan_request": {
        "expected_version": 1, "scope": "future", "instruction": "另一条指令。",
        "repair_proposal_id": "212324be-feff-4228-af5c-179511c6278d",
    }},
])
async def test_retry_cannot_resurrect_proposal_after_protected_inputs_change(monkeypatch, mutation):
    from application.errors import StaleWorkflowDecisionError

    service, context, _config, _state, llm = await _lost_proposal_service(monkeypatch, mutation=mutation)
    with pytest.raises(StaleWorkflowDecisionError):
        await service.prepare_retry_checkpoint(context, "lost-repair")
    assert llm.structured_generate.await_count == 0
