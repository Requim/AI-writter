"""Initial repair stays evidence-bound and cannot substitute for full review."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.routers.workflow_router import WorkflowInvokeRequest, _plan_replan_command, _prepare_request
from application.agents.novel_plan_node import novel_plan_initialize_node, novel_plan_review_node
from application.creative.artifacts import workspace
from application.creative.errors import CreativeConflict, CreativePause
from application.creative.evidence import content_hash
from application.creative.plan_consistency import _audit_context
from application.orchestrator import NovelOrchestrator
from application.proposals import proposal_update
from tests.test_novel_planning_workflow import _tenant_context
from tests.test_plan_consistency_audit import _fixture


async def _initial_fixture():
    repo, llm, cfg, plan, state = _fixture()
    plan.chapter_slots[69].must_happen = ["Father gives the second copy."]
    plan.chapter_slots[79].must_happen = ["Father gives the second copy.", "Debt relabeled."]
    plan.chapter_slots[77].planned_state_delta = "Debt relabeled."
    plan.chapter_slots[79].planned_state_delta = "Debt relabeled."
    plan.volumes[3].ending_state = "Father gives the second copy; limited reconciliation."
    plan.arcs[0].escalation_points = [{"chapter_number": 80, "change": "Debt relabeled."}]
    state.update(novel_plan=None, scale_contract=plan.scale.to_dict(), workflow_schema_version=5)
    state.update(proposal_update(state, "novel_plan", {"plan": plan.to_dict()}))
    source = state["pending_proposal"]["proposal_id"]
    state["plan_replan_request"] = {
        "expected_version": 0, "scope": "future", "instruction": "Preserve first events; refer to their results.",
        "repair_proposal_id": source, "repair_mode": "cross_layer",
    }
    work = await workspace(cfg)
    report = _initial_report()
    context = await _audit_context(work, state, plan, cfg)
    await work.save("decision", "plan_consistency:" + source, report,
                    inputs={"context_hash": content_hash(context)}, status="reviewed")
    await work.save("decision", "plan_consistency_repair:0", {
        "proposal_id": "earlier-proposal", "report": report,
    }, source="system", status="requested")
    llm.structured_generate.return_value = {"changes": [
        {"path": "/plan/chapter_slots/79/must_happen/0", "before": "Father gives the second copy.",
         "after": "The copy already held is sealed; limited reconciliation."},
        {"path": "/plan/chapter_slots/79/must_happen/1", "before": "Debt relabeled.",
         "after": "The debt retains its hearing classification."},
        {"path": "/plan/chapter_slots/79/planned_state_delta", "before": "Debt relabeled.",
         "after": "The completed debt classification remains effective."},
        {"path": "/plan/volumes/3/ending_state",
         "before": "Father gives the second copy; limited reconciliation.",
         "after": "The previously delivered copy is sealed; limited reconciliation."},
        {"path": "/plan/arcs/0/escalation_points/0/change", "before": "Debt relabeled.",
         "after": "The hearing classification remains effective; main arc closes."},
    ]}
    return repo, llm, cfg, plan, state


def _initial_report():
    return {
        "coverage": "complete", "timeline_pass": True, "single_use_pass": True,
        "cross_layer_pass": False, "ending_causality_pass": True, "summary": "Two repeated events.",
        "issues": [
            {"code": "cross_layer", "description": "Handover at 70 and 80.", "suggestion": "Keep 70.",
             "evidence": [
                 {"path": "/plan/chapter_slots/69/must_happen/0", "quote": "Father gives the second copy"},
                 {"path": "/plan/chapter_slots/79/must_happen/0", "quote": "Father gives the second copy"},
                 {"path": "/plan/volumes/3/ending_state", "quote": "Father gives the second copy"},
             ]},
            {"code": "cross_layer", "description": "Relabel at 78 and 80.", "suggestion": "Keep 78.",
             "evidence": [
                 {"path": "/plan/chapter_slots/77/planned_state_delta", "quote": "Debt relabeled"},
                 {"path": "/plan/chapter_slots/79/planned_state_delta", "quote": "Debt relabeled"},
                 {"path": "/plan/arcs/0/escalation_points/0/change", "quote": "Debt relabeled"},
             ]},
        ],
    }


def _initial_service(state, accepted=None):
    service = NovelOrchestrator(
        repository=SimpleNamespace(get_latest_plan=AsyncMock(return_value=accepted)),
        memory_service=SimpleNamespace(), llm_config={},
    )
    service._workflow = SimpleNamespace(aget_state=AsyncMock(return_value=SimpleNamespace(
        values=state, next=("novel_plan_review_node",), tasks=(),
    )))
    return service


@pytest.mark.asyncio
async def test_initial_patch_preserves_every_nonpatched_field_and_requires_review():
    repo, llm, cfg, plan, state = await _initial_fixture()
    original, expected = deepcopy(state), plan.to_dict()
    changes = deepcopy(llm.structured_generate.return_value["changes"])
    command = await novel_plan_initialize_node(state, cfg)
    expected["chapter_slots"][79]["must_happen"] = [changes[0]["after"], changes[1]["after"]]
    expected["chapter_slots"][79]["planned_state_delta"] = changes[2]["after"]
    expected["volumes"][3]["ending_state"] = changes[3]["after"]
    expected["arcs"][0]["escalation_points"][0]["change"] = changes[4]["after"]
    assert command.goto == "novel_plan_review_node"
    assert command.update["pending_proposal"]["payload"]["plan"] == expected
    assert command.update["pending_proposal"]["proposal_id"] != original["pending_proposal"]["proposal_id"]
    assert command.update["plan_generation"]["mode"] == "initial"
    assert command.update["plan_generation"]["expected_version"] == 0
    assert command.update["plan_replan_request"] is None
    assert "novel_plan" not in command.update and state == original
    assert repo.session["counters"] == {}
    assert len(repo.rows) == 3


@pytest.mark.asyncio
async def test_initial_repair_replay_retains_raw_model_patch_without_another_call():
    repo, llm, cfg, _plan, state = await _initial_fixture()
    first = await novel_plan_initialize_node(state, cfg)
    again = await novel_plan_initialize_node(state, cfg)
    assert first.update["pending_proposal"]["payload"] == again.update["pending_proposal"]["payload"]
    assert len(repo.rows) == 3 and repo.rows[-1]["payload"] == llm.structured_generate.return_value
    assert llm.structured_generate.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["uncited", "earlier", "wrong_before", "duplicate", "extra", "empty"])
async def test_initial_patch_protocol_failure_cannot_change_candidate_or_reset_allowance(problem):
    repo, llm, cfg, _plan, state = await _initial_fixture()
    result = llm.structured_generate.return_value
    change = result["changes"][0]
    mutations = {
        "uncited": lambda: change.update(path="/plan/ending_contract/final_state"),
        "earlier": lambda: change.update(path="/plan/chapter_slots/69/must_happen/0"),
        "wrong_before": lambda: change.update(before="Not the original."),
        "duplicate": lambda: result["changes"].append(deepcopy(change)),
        "extra": lambda: change.update(chapter_number=71),
        "empty": lambda: result.update(changes=[]),
    }
    mutations[problem]()
    before = deepcopy(state)
    with pytest.raises(CreativePause):
        await novel_plan_initialize_node(state, cfg)
    assert state == before and len(repo.rows) == 3
    assert len([r for r in repo.rows if r["key"] == "plan_consistency_repair:0"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["context", "completed", "proposal", "accepted", "scale"])
async def test_initial_patch_preconditions_reject_before_provider(problem):
    repo, llm, cfg, plan, state = await _initial_fixture()
    mutations = {
        "context": lambda: repo.session["config"].update(hard_constraints=["Changed author constraint."]),
        "completed": lambda: state.update(current_chapter_index=1),
        "proposal": lambda: state["plan_replan_request"].update(repair_proposal_id=str(uuid4())),
        "accepted": lambda: state.update(novel_plan={**plan.to_dict(), "version": 1}),
        "scale": lambda: state["scale_contract"].update(target_total_words=400000),
    }
    mutations[problem]()
    with pytest.raises(CreativeConflict):
        await novel_plan_initialize_node(state, cfg)
    assert llm.structured_generate.await_count == 0 and len(repo.rows) == 2


@pytest.mark.asyncio
async def test_initial_patch_must_pass_fresh_full_review_before_first_acceptance():
    repo, llm, cfg, _plan, state = await _initial_fixture()
    patched = await novel_plan_initialize_node(state, cfg)
    state.update(patched.update)
    llm.structured_generate.return_value = {
        "coverage": "complete", "timeline_pass": True, "single_use_pass": True,
        "cross_layer_pass": True, "ending_causality_pass": True, "issues": [], "summary": "Passed.",
    }
    assert state["novel_plan"] is None
    accepted = await novel_plan_review_node(state, cfg)
    assert accepted.update["novel_plan"]["version"] == 1
    assert accepted.goto == "persist_node"
    assert len([r for r in repo.rows if r["key"].startswith("plan_consistency:")]) == 2
    assert not [r for r in repo.rows if r["kind"] == "replan"]


@pytest.mark.asyncio
async def test_initial_patch_failed_fresh_review_keeps_consumed_auto_repair():
    repo, llm, cfg, _plan, state = await _initial_fixture()
    command = await novel_plan_initialize_node(state, cfg)
    state.update(command.update)
    state["pending_proposal"]["payload"]["plan"]["chapter_slots"][79]["must_happen"][0] = (
        "Father gives the second copy."
    )
    state["pending_proposal"]["payload"]["plan"]["volumes"][3]["ending_state"] = (
        "Father gives the second copy; limited reconciliation."
    )
    state["pending_proposal"]["payload"]["plan"]["chapter_slots"][79]["planned_state_delta"] = "Debt relabeled."
    state["pending_proposal"]["payload"]["plan"]["arcs"][0]["escalation_points"][0]["change"] = "Debt relabeled."
    llm.structured_generate.return_value = _initial_report()
    with pytest.raises(CreativePause, match="修复后"):
        await novel_plan_review_node(state, cfg)
    assert state["novel_plan"] is None
    assert len([r for r in repo.rows if r["key"] == "plan_consistency_repair:0"]) == 1


@pytest.mark.asyncio
async def test_api_initial_named_repair_uses_private_candidate_and_scale(monkeypatch):
    monkeypatch.setattr("api.routers.workflow_router.settings.NOVEL_PLANNING_V1_ENABLED", True)
    _repo, _llm, _cfg, _plan, state = await _initial_fixture()
    original = deepcopy(state)
    result, *_ = await _prepare_request(
        WorkflowInvokeRequest(command={"plan_replan": state["plan_replan_request"], "_auto_mode": True}),
        _tenant_context(planning=True), str(uuid4()), _initial_service(state),
        SimpleNamespace(reserve=AsyncMock()), command_id="initial-cross-layer",
    )
    assert result["pending_proposal"] == state["pending_proposal"]
    assert result["novel_plan"] == {} and result["scale_contract"] == state["scale_contract"]
    result["pending_proposal"]["payload"]["plan"]["chapter_slots"][79]["must_happen"][0] = "Client mutation."
    assert state == original


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["stale_id", "completed", "manual", "custom_input", "accepted"])
async def test_api_initial_repair_rejects_untrusted_state_before_quota(monkeypatch, problem):
    monkeypatch.setattr("api.routers.workflow_router.settings.NOVEL_PLANNING_V1_ENABLED", True)
    _repo, _llm, _cfg, plan, state = await _initial_fixture()
    request = deepcopy(state["plan_replan_request"])
    if problem == "stale_id":
        request["repair_proposal_id"] = str(uuid4())
    elif problem == "completed":
        state["current_chapter_index"] = 1
    elif problem == "manual":
        state["author_mode"] = "manual"
    service = _initial_service(state, plan if problem == "accepted" else None)
    quota = SimpleNamespace(reserve=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await _prepare_request(
            WorkflowInvokeRequest(command={"plan_replan": request, "_auto_mode": True},
                                  input={"pending_proposal": {}} if problem == "custom_input" else None),
            _tenant_context(planning=True), str(uuid4()), service, quota, command_id="untrusted-initial",
        )
    assert error.value.status_code == (422 if problem == "custom_input" else 409)
    quota.reserve.assert_not_awaited()
    assert service._llm_instance is None


@pytest.mark.parametrize("patch", [
    {"repair_mode": "cross_layer"}, {"repair_mode": "unknown", "repair_proposal_id": str(uuid4())},
    {"repair_proposal_id": str(uuid4())}, {},
])
def test_ordinary_or_unsupported_replan_cannot_use_version_zero(patch):
    with pytest.raises(HTTPException) as error:
        _plan_replan_command({"expected_version": 0, "scope": "future", "instruction": "Repair.", **patch})
    assert error.value.status_code == 422


@pytest.mark.parametrize("mode", [{}, [], True, 1])
@pytest.mark.parametrize("version", [0, 1])
def test_api_invalid_repair_mode_is_a_client_error_not_server_exception(mode, version):
    with pytest.raises(HTTPException) as error:
        _plan_replan_command({
            "expected_version": version, "scope": "future", "instruction": "Repair.",
            "repair_proposal_id": str(uuid4()), "repair_mode": mode,
        })
    assert error.value.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["quote", "partial", "other_gate", "one_chapter", "unsupported"])
async def test_initial_patch_rejects_unsupported_review_before_provider(problem):
    repo, llm, cfg, _plan, state = await _initial_fixture()
    report = repo.rows[0]["payload"]
    mutations = {
        "quote": lambda: report["issues"][0]["evidence"][0].update(quote="Absent evidence."),
        "partial": lambda: report.update(coverage="partial"),
        "other_gate": lambda: report.update(timeline_pass=False),
        "one_chapter": lambda: report["issues"][0].update(evidence=[report["issues"][0]["evidence"][1]]),
        "unsupported": lambda: report["issues"][0]["evidence"].append({
            "path": "/plan/scale/preset", "quote": "long",
        }),
    }
    mutations[problem]()
    with pytest.raises(CreativePause):
        await novel_plan_initialize_node(state, cfg)
    assert llm.structured_generate.await_count == 0 and len(repo.rows) == 2
