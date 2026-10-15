"""Whole-plan semantic review must precede autonomous plan acceptance."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.agents.novel_plan_node import novel_plan_review_node, plan_reconciliation_node
from application.creative.errors import CreativePause
from application.creative.artifacts import json_text, workspace
from application.creative.evidence import content_hash
from application.creative.replanning import validate_autonomous_plan
from application.creative.runtime import budget_bucket
from application.proposals import proposal_update
from tests.creative_fakes import CreativeRepositoryFake, creative_config
from tests.test_novel_plan import _plan


def _fixture():
    repository = CreativeRepositoryFake(chapters=80)
    report = {
        "coverage": "complete",
        "timeline_pass": True,
        "single_use_pass": True,
        "cross_layer_pass": True,
        "ending_causality_pass": True,
        "issues": [],
        "summary": "No supported contradiction.",
    }
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value=report))
    config = creative_config(repository, llm)
    config["configurable"].update(auto_mode=True, novel_planning_v1_enabled=True)
    plan = _plan(80, 336_000)
    template = plan.volumes[0]
    plan.volumes = [
        replace(template, volume_id=f"vol-{number}", title=f"第{number}卷",
                start_chapter=start, end_chapter=start + 19, target_words=84_000)
        for number, start in enumerate(range(1, 81, 20), 1)
    ]
    for slot in plan.chapter_slots:
        slot.volume_id = f"vol-{(slot.chapter_number - 1) // 20 + 1}"
    plan.assert_valid()
    state = {
        "author_mode": "autonomous_v1", "current_chapter_index": 0,
        "total_outline": {"main_characters": []},
        "plan_generation": {"mode": "initial", "expected_version": 0},
    }
    return repository, llm, config, plan, state


def _conflict(plan):
    plan.chapter_slots[27].must_happen = ["七日鉴定完成，提交潮位结论。"]
    plan.chapter_slots[62].must_happen = ["最终期限当天重新启动七日鉴定。"]
    return {
        "coverage": "complete",
        "timeline_pass": False,
        "single_use_pass": True,
        "cross_layer_pass": True,
        "ending_causality_pass": True,
        "issues": [{
            "code": "timeline", "description": "Completed appraisal restarts on deadline.",
            "suggestion": "Reuse the completed report; do not restart its seven-day wait.",
            "evidence": [
                {"path": "/plan/chapter_slots/27/must_happen/0",
                 "quote": "七日鉴定完成"},
                {"path": "/plan/chapter_slots/62/must_happen/0",
                 "quote": "最终期限当天重新启动七日鉴定"},
            ],
        }],
        "summary": "Deadline is incompatible with the repeated waiting period.",
    }


@pytest.mark.asyncio
async def test_initial_autonomous_plan_is_reviewed_in_full_and_cached():
    repo, llm, cfg, plan, state = _fixture()
    await validate_autonomous_plan(state, cfg, plan, "proposal-1")
    await validate_autonomous_plan(state, cfg, plan, "proposal-1")
    llm.structured_generate.assert_awaited_once()
    kwargs = llm.structured_generate.await_args.kwargs
    assert kwargs["max_attempts"] == 1
    assert '"chapter_number":80' in kwargs["prompt"]
    assert "timeline_pass" in kwargs["prompt"]
    assert len(await repo.records("", "", "decision")) == 1
    assert not await repo.records("", "", "replan")


@pytest.mark.asyncio
async def test_initial_conflict_routes_once_to_generation_without_accepting():
    repo, llm, cfg, plan, state = _fixture()
    llm.structured_generate.return_value = _conflict(plan)
    accept = AsyncMock()
    cfg["configurable"]["novel_repository"] = SimpleNamespace(accept_plan=accept)
    state.update(proposal_update(state, "novel_plan", {"plan": plan.to_dict()}))
    original = deepcopy(state)
    command = await novel_plan_review_node(state, cfg)
    assert command.goto == "novel_plan_initialize_node"
    assert command.update["pending_proposal"] is None
    assert "七日鉴定" in command.update["plan_feedback"]
    assert state == original
    accept.assert_not_awaited()
    assert len(await repo.records("", "", "decision")) == 2


@pytest.mark.asyncio
async def test_failed_repair_is_bounded_and_replay_does_not_call_model():
    repo, llm, cfg, plan, state = _fixture()
    llm.structured_generate.return_value = _conflict(plan)
    state.update(proposal_update(state, "novel_plan", {"plan": plan.to_dict()}))
    first = await novel_plan_review_node(state, cfg)
    state.update(first.update)
    state["plan_generation"] = {"mode": "initial", "expected_version": 0}
    state.update(proposal_update(state, "novel_plan", {"plan": plan.to_dict()}))
    for _ in range(2):
        with pytest.raises(CreativePause, match="修复后"):
            await novel_plan_review_node(state, cfg)
    assert llm.structured_generate.await_count == 2
    assert len([r for r in repo.rows if r["key"].startswith("plan_consistency_repair:")]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["bad_quote", "bad_path", "partial", "string_bool", "missing_issues"])
async def test_invalid_semantic_report_is_retained_but_cannot_trigger_rewrite(mutation):
    repo, llm, cfg, plan, state = _fixture()
    report = _conflict(plan)
    operations = {
        "bad_quote": lambda: report["issues"][0]["evidence"][1].update(quote="不存在的原文"),
        "bad_path": lambda: report["issues"][0]["evidence"][1].update(
            path="/plan/chapter_slots/999/must_happen/0"),
        "partial": lambda: report.update(coverage="partial"),
        "string_bool": lambda: report.update(timeline_pass="false"),
        "missing_issues": lambda: report.pop("issues"),
    }
    operations[mutation]()
    llm.structured_generate.return_value = report
    for _ in range(2):
        with pytest.raises(CreativePause):
            await validate_autonomous_plan(state, cfg, plan, "invalid")
    assert llm.structured_generate.await_count == 1
    rows = await repo.records("", "", "decision")
    assert len(rows) == 1 and rows[0]["payload"] == report


@pytest.mark.asyncio
async def test_new_book_corrects_invalid_plan_evidence_once_and_retains_failure():
    repo, llm, cfg, plan, state = _fixture()
    state["reader_quality_version"] = 1
    invalid = _conflict(plan)
    invalid["issues"][0]["evidence"][0]["path"] = "/invented/path"
    corrected = deepcopy(invalid)
    corrected["issues"][0]["evidence"][0]["path"] = "/plan/chapter_slots/27/must_happen/0"
    llm.structured_generate.side_effect = [invalid, corrected]
    state.update(proposal_update(state, "novel_plan", {"plan": plan.to_dict()}))
    command = await novel_plan_review_node(state, cfg)
    assert command.goto == "novel_plan_initialize_node"
    assert llm.structured_generate.await_count == 2
    saved = await repo.records("", "", "decision")
    assert any(row["payload"] == invalid for row in saved)
    assert "原文叶子目录" in llm.structured_generate.await_args.kwargs["prompt"]


@pytest.mark.asyncio
async def test_new_book_invalid_plan_correction_is_bounded_across_resume():
    _repo, llm, cfg, plan, state = _fixture()
    state["reader_quality_version"] = 1
    invalid = _conflict(plan)
    invalid["issues"][0]["evidence"][0]["quote"] = "不存在的原文"
    llm.structured_generate.return_value = invalid
    for _ in range(2):
        with pytest.raises(CreativePause):
            await validate_autonomous_plan(state, cfg, plan, "bounded-format")
    assert llm.structured_generate.await_count == 2


@pytest.mark.asyncio
async def test_proposal_replay_rejects_changed_plan_input_without_new_model_call():
    _repo, llm, cfg, plan, state = _fixture()
    await validate_autonomous_plan(state, cfg, plan, "proposal-1")
    plan.chapter_slots[1].must_happen = ["改变后的事件"]
    with pytest.raises(ValueError, match="输入"):
        await validate_autonomous_plan(state, cfg, plan, "proposal-1")
    assert llm.structured_generate.await_count == 1


@pytest.mark.asyncio
async def test_legacy_manual_mode_has_no_new_review_or_workspace_requirement():
    cfg = {"configurable": {}}
    await validate_autonomous_plan({}, cfg, _plan(), "legacy")


@pytest.mark.asyncio
async def test_same_rejected_proposal_replay_resumes_the_recorded_repair():
    repo, llm, cfg, plan, state = _fixture()
    llm.structured_generate.return_value = _conflict(plan)
    state.update(proposal_update(state, "novel_plan", {"plan": plan.to_dict()}))
    first = await novel_plan_review_node(state, cfg)
    replay = await novel_plan_review_node(state, cfg)
    assert replay.update == first.update
    assert llm.structured_generate.await_count == 1
    assert len(await repo.records("", "", "decision")) == 2


@pytest.mark.asyncio
async def test_repaired_candidate_is_independently_reviewed_before_acceptance():
    repo, llm, cfg, plan, state = _fixture()
    failure = _conflict(plan)
    passed = deepcopy(llm.structured_generate.return_value)
    passed.update(timeline_pass=True, issues=[], summary="The completed report is reused.")
    llm.structured_generate.side_effect = [failure, passed]
    state.update(proposal_update(state, "novel_plan", {"plan": plan.to_dict()}))
    first = await novel_plan_review_node(state, cfg)
    state.update(first.update)
    state["plan_generation"] = {"mode": "initial", "expected_version": 0}
    plan.chapter_slots[62].must_happen = ["听证会核验已完成的七日鉴定结论。"]
    state.update(proposal_update(state, "novel_plan", {"plan": plan.to_dict()}))
    accepted = await novel_plan_review_node(state, cfg)
    assert accepted.goto == "persist_node"
    assert accepted.update["novel_plan"]["version"] == 1
    assert llm.structured_generate.await_count == 2
    assert len([r for r in repo.rows if r["key"].startswith("plan_consistency:")]) == 2


@pytest.mark.asyncio
async def test_changed_author_constraints_invalidate_cached_review():
    repo, llm, cfg, plan, state = _fixture()
    await validate_autonomous_plan(state, cfg, plan, "proposal-1")
    repo.session["config"]["hard_constraints"] = ["No replacement witness."]
    with pytest.raises(ValueError, match="输入"):
        await validate_autonomous_plan(state, cfg, plan, "proposal-1")
    assert llm.structured_generate.await_count == 1


@pytest.mark.asyncio
async def test_automatic_volume_detail_repair_preserves_current_plan_version_and_lock():
    _repo, llm, cfg, plan, state = _fixture()
    previous = deepcopy(plan.to_dict())
    previous["version"] = 3
    state["novel_plan"] = previous
    state["current_chapter_index"] = 20
    state["plan_generation"] = {"mode": "volume_detail", "expected_version": 3}
    llm.structured_generate.return_value = _conflict(plan)
    state.update(proposal_update(state, "novel_plan", {"plan": plan.to_dict()}))
    result = await novel_plan_review_node(state, cfg)
    assert result.goto == "novel_plan_initialize_node"
    request = result.update["plan_replan_request"]
    assert request["expected_version"] == 3 and request["scope"] == "future"
    assert request["trigger"] == "consistency"
    assert state["novel_plan"] == previous


@pytest.mark.asyncio
async def test_autonomous_minor_drift_cannot_accept_without_durable_plan_review():
    _repo, llm, cfg, plan, state = _fixture()
    plan.version = 1
    state.update(
        novel_plan=plan.to_dict(), current_chapter_index=1,
        last_persisted_chapter={"word_count": 4200},
        quality_gate={"plan_fulfillment": {"deferred_items": ["延后的线索"]}},
        plan_generation=None,
    )
    accept = AsyncMock(side_effect=lambda _tenant, _novel, candidate, expected, **_kwargs:
                       replace(candidate, version=expected + 1))
    cfg["configurable"]["novel_repository"] = SimpleNamespace(
        accept_plan=accept, upsert_plan_execution=AsyncMock(),
    )
    pending = await plan_reconciliation_node(state, cfg)
    assert pending.goto == "novel_plan_review_node"
    accept.assert_not_awaited()
    llm.structured_generate.assert_not_awaited()
    candidate = pending.update["pending_proposal"]["payload"]["plan"]
    assert "延后的线索" in candidate["chapter_slots"][6]["must_happen"]
    assert candidate["chapter_slots"][:6] == plan.to_dict()["chapter_slots"][:6]
    state.update(pending.update)
    reviewed = await novel_plan_review_node(state, cfg)
    assert reviewed.goto == "progress_check_node"
    assert reviewed.update["novel_plan"]["version"] == 2
    assert "延后的线索" in reviewed.update["novel_plan"]["chapter_slots"][6]["must_happen"]
    llm.structured_generate.assert_awaited_once()
    accept.assert_awaited_once()
    assert not await _repo.records("", "", "replan")


@pytest.mark.asyncio
async def test_failed_minor_drift_review_routes_bounded_future_replan():
    _repo, llm, cfg, plan, state = _fixture()
    llm.structured_generate.return_value = _conflict(plan)
    plan.version = 1
    state.update(
        novel_plan=plan.to_dict(), current_chapter_index=1,
        last_persisted_chapter={"word_count": 4200},
        quality_gate={"plan_fulfillment": {"deferred_items": ["延后的线索"]}},
        plan_generation=None,
    )
    accept = AsyncMock()
    cfg["configurable"]["novel_repository"] = SimpleNamespace(
        accept_plan=accept, upsert_plan_execution=AsyncMock(),
    )
    pending = await plan_reconciliation_node(state, cfg)
    state.update(pending.update)
    rejected = await novel_plan_review_node(state, cfg)
    assert rejected.goto == "novel_plan_initialize_node"
    assert rejected.update["plan_replan_request"]["expected_version"] == 1
    assert rejected.update["plan_replan_request"]["scope"] == "future"
    accept.assert_not_awaited()
    assert state["novel_plan"] == plan.to_dict()


@pytest.mark.parametrize(
    ("node", "state", "bucket"),
    [
        ("novel_plan_review_node", {}, "preparation"),
        ("novel_plan_review_node", {"novel_plan": {"version": 1}}, "review"),
        ("novel_plan_volume_node", {"plan_replan_request": {"scope": "future"}}, "review"),
        ("reflection_node", {"current_chapter_index": 2}, "chapter:3"),
    ],
)
def test_plan_review_is_not_charged_to_next_chapter(node, state, bucket):
    assert budget_bucket(node, state) == bucket


@pytest.mark.asyncio
async def test_wrong_parent_path_for_unique_complete_leaf_is_located_without_model_rerun():
    repo, llm, cfg, plan, state = _fixture()
    report = _conflict(plan)
    quote = "七日鉴定只在第21至28章消耗一次，后续核验不得重启等待。"
    plan.ending_contract["immutable_facts"] = [quote]
    report["issues"][0]["evidence"].append({"path": "/plan/immutable_facts/0", "quote": quote})
    original = deepcopy(report)
    llm.structured_generate.return_value = report
    state.update(proposal_update(state, "novel_plan", {"plan": plan.to_dict()}))
    command = await novel_plan_review_node(state, cfg)
    assert command.goto == "novel_plan_initialize_node"
    assert llm.structured_generate.await_count == 1 and report == original
    reviews = [r for r in repo.rows if r["key"].startswith("plan_consistency:")]
    assert len(reviews) == 2
    assert reviews[0]["payload"] == original and reviews[0]["source"] == "model"
    located = reviews[1]
    assert located["source"] == "system" and located["version"] == 2
    proof = located["payload"]["issues"][0]["evidence"][-1]
    assert proof == {"path": "/plan/ending_contract/immutable_facts/0", "quote": quote}
    assert located["payload"]["timeline_pass"] is False
    assert located["input_versions"] == reviews[0]["input_versions"]
    replay = await novel_plan_review_node(state, cfg)
    assert replay.update == command.update and len(repo.rows) == 3
    assert llm.structured_generate.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    "duplicate", "fragment", "existing_wrong_leaf",
    "existing_object", "existing_number", "malformed_pointer", "bad_escape",
])
async def test_evidence_locator_cannot_guess_ambiguous_fragment_or_existing_path(case):
    repo, llm, cfg, plan, state = _fixture()
    report = _conflict(plan)
    quote = "七日鉴定必须只消耗一次。"
    plan.ending_contract["immutable_facts"] = [quote]
    if case == "duplicate":
        plan.ending_contract["immutable_facts"].append(quote)
    proof = {"path": "/plan/immutable_facts/0", "quote": quote}
    if case == "fragment":
        proof["quote"] = "七日鉴定必须只消耗一次"
    if case == "existing_wrong_leaf":
        proof["path"] = "/plan/chapter_slots/1/must_happen/0"
    paths = {
        "existing_object": "/plan/ending_contract",
        "existing_number": "/plan/version",
        "malformed_pointer": "plan/ending_contract/immutable_facts/0",
        "bad_escape": "/plan/missing/~2",
    }
    if case in paths:
        proof["path"] = paths[case]
    report["issues"][0]["evidence"].append(proof)
    llm.structured_generate.return_value = report
    with pytest.raises(CreativePause, match="精确"):
        await validate_autonomous_plan(state, cfg, plan, "unsupported-locator")
    assert llm.structured_generate.await_count == 1
    assert len(repo.rows) == 1


def _execution(chapter, deferred):
    return SimpleNamespace(to_dict=lambda: {
        "chapter_number": chapter, "plan_version": 1, "status": "deferred" if deferred else "fulfilled",
        "actual_words": 4200, "fulfillment": {"deferred_items": deferred, "state_delta_fulfilled": True},
        "drift_severity": "minor" if deferred else "none", "updated_at": "not-a-semantic-input",
    })


@pytest.mark.asyncio
async def test_durable_earlier_deferral_survives_later_plan_review_context():
    _repo, llm, cfg, plan, state = _fixture()
    receipts = [_execution(1, ["尚未交出的备忘录"]), _execution(2, []), _execution(8, ["未来回执不可用"])]
    loader = AsyncMock(return_value=receipts)
    cfg["configurable"]["novel_repository"] = SimpleNamespace(list_plan_executions=loader)
    state["current_chapter_index"] = 2
    await validate_autonomous_plan(state, cfg, plan, "with-executions")
    prompt = llm.structured_generate.await_args.kwargs["prompt"]
    assert "尚未交出的备忘录" in prompt and "execution_receipts" in prompt
    assert "未来回执不可用" not in prompt and "not-a-semantic-input" not in prompt
    assert "计划要求不等于实际发生" in prompt
    loader.assert_awaited_once()


@pytest.mark.asyncio
async def test_changed_execution_assessment_invalidates_saved_plan_review():
    _repo, llm, cfg, plan, state = _fixture()
    loader = AsyncMock(return_value=[_execution(1, ["未完成鉴定"])])
    cfg["configurable"]["novel_repository"] = SimpleNamespace(list_plan_executions=loader)
    state["current_chapter_index"] = 1
    await validate_autonomous_plan(state, cfg, plan, "receipt-bound")
    loader.return_value = [_execution(1, [])]
    with pytest.raises(ValueError, match="输入"):
        await validate_autonomous_plan(state, cfg, plan, "receipt-bound")
    assert llm.structured_generate.await_count == 1


@pytest.mark.asyncio
async def test_deferral_receipt_cannot_override_future_prerequisite_failure():
    _repo, llm, cfg, plan, state = _fixture()
    report = _conflict(plan)
    llm.structured_generate.return_value = report
    cfg["configurable"]["novel_repository"] = SimpleNamespace(
        list_plan_executions=AsyncMock(return_value=[_execution(1, ["尚未交出的备忘录"])]))
    state["current_chapter_index"] = 1
    with pytest.raises(CreativePause):
        await validate_autonomous_plan(state, cfg, plan, "actual-prerequisite-failure")
    assert llm.structured_generate.await_count == 1


@pytest.mark.asyncio
async def test_zero_chapter_existing_review_hash_is_not_changed_by_execution_context_rollout():
    _repo, llm, cfg, plan, state = _fixture()
    work = await workspace(cfg)
    legacy_context = json_text({
        "plan": plan.to_dict(), "previous_plan": {}, "completed_chapters": 0,
        "author_constraints": {key: value for key, value in work.session["config"].items()
                               if key not in {"budget", "research_queries", "sources"}},
        "characters": [], "story_engine": {},
    })
    await work.save("decision", "plan_consistency:old-proposal",
                    llm.structured_generate.return_value, status="reviewed",
                    inputs={"context_hash": content_hash(legacy_context)})
    await validate_autonomous_plan(state, cfg, plan, "old-proposal")
    llm.structured_generate.assert_not_awaited()
