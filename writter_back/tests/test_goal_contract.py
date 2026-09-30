"""目标验收预期先于生成结果：用固定反例检验每层边界。"""

from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest

from application.agents.chapter_outline_node import _accept_outline_update
from application.agents.reflection_node import _choice_command, reflection_node
from application.agents.revision_node import _accept_revision, revision_node, revision_review_node, _next_after_revision, _check_goal_patch_scope
from application.agents.persist_node import persist_node
from application.errors import InvalidReviewDecisionError, QualityGateReviewRequired, RetryableWorkflowError
from application.goal_contract import compile_goal_contract, current_goal_contract, evaluate_goals, require_goal_acceptance
from application.proposals import ReviewDecision


def goal_state() -> dict:
    state = {
        "current_chapter_index": 0, "total_outline": {}, "completed_chapters": [],
        "novel_plan": {
            "version": 1, "scale": {"target_chapters": 1, "target_total_words": 3000, "tolerance_ratio": 0.1},
            "ending_contract": {"final_state": "归还失物，当章闭合"},
            "chapter_slots": [{"chapter_number": 1, "target_words": 3000,
                               "must_happen": ["查出原册页", "归还失物"],
                               "planned_state_delta": "失物已归还"}],
        },
        "current_chapter_content": "找出原册页，归还失物。" + "正文" * 1495,
    }
    state["chapter_outlines"] = [{"title": "雨夜", "goal_contract": compile_goal_contract(state)}]
    return state


def report_for(state: dict) -> dict:
    contract = state["chapter_outlines"][-1]["goal_contract"]
    return {
        "goal_checks": [{"id": item["id"], "status": "passed", "evidence": "找出原册页，归还失物。",
                         "reason": "明确查到原页后核对并归还，承接责任并收束"}
                        for item in contract["requirements"]],
        "plan_fulfillment": {"deferred_items": []},
    }


def test_contract_comes_from_accepted_plan_not_model_outline():
    state = goal_state()
    model_outline = {"title": "模型篡改", "goal_contract": {"id": "forged"}}
    result = _accept_outline_update(state, model_outline)["chapter_outlines"][0]
    assert result["goal_contract"] == compile_goal_contract(state)
    assert model_outline["goal_contract"] == {"id": "forged"}


def test_acceptance_has_stable_source_and_exact_body_receipt():
    state = goal_state()
    contract = current_goal_contract(state)
    assert contract == compile_goal_contract(deepcopy(state))
    report = evaluate_goals(state, report_for(state), state["current_chapter_content"])
    assert report["status"] == "passed"
    state["quality_gate"] = {"goal_acceptance": report}
    assert require_goal_acceptance(state, state["current_chapter_content"])
    assert not require_goal_acceptance(state, state["current_chapter_content"] + "改变正文")
    state["novel_plan"]["chapter_slots"][0]["must_happen"] = ["不再归还失物"]
    with pytest.raises(QualityGateReviewRequired, match="目标来源已变化"):
        current_goal_contract(state)


@pytest.mark.parametrize("mutation", ["missing", "invented_evidence", "duplicate", "failed", "no_reason"])
def test_semantic_acceptance_requires_each_goal_and_real_evidence(mutation):
    state = goal_state()
    raw = report_for(state)
    rows = raw["goal_checks"]
    actions = {
        "missing": lambda: rows.pop(),
        "invented_evidence": lambda: rows[0].update(evidence="正文不存在的证据"),
        "duplicate": lambda: rows.append(deepcopy(rows[0])),
        "failed": lambda: rows[0].update(status="failed"),
        "no_reason": lambda: rows[0].update(reason=""),
    }
    actions[mutation]()
    assert evaluate_goals(state, raw, state["current_chapter_content"])["status"] == "blocked"


def test_model_score_and_word_claim_cannot_override_real_scale():
    state = goal_state()
    content = "找出原册页，归还失物。".ljust(4656, "文")
    assert len(content) == 4656
    raw = {**report_for(state), "overall_quality_score": 1, "passed": True,
           "word_count_analysis": {"total_count": 3000, "is_valid_word_count": True}}
    result = evaluate_goals(state, raw, content)
    assert result["status"] == "blocked"
    scale = next(c for c in result["checks"] if c["id"] == "scale")
    assert scale["actual_chapter_words"] == 4656
    assert scale["range"] == [2700, 3300]


def test_final_chapter_cannot_defer_to_nonexistent_next_chapter():
    state = goal_state()
    raw = report_for(state)
    raw["plan_fulfillment"]["deferred_items"] = ["下章再归还失物"]
    result = evaluate_goals(state, raw, state["current_chapter_content"])
    assert result["status"] == "blocked"
    assert result["checks"][-1]["id"] == "no_final_deferral"


def test_legacy_chapter_is_not_relabelled_as_new_goal_verified():
    state = {"chapter_outlines": [{}]}
    assert current_goal_contract(state) is None
    assert evaluate_goals(state, {}, "旧正文") is None
    assert require_goal_acceptance(state, "旧正文")


def test_accepting_revision_always_rechecks_goals_even_in_manual_mode():
    state = goal_state()
    command = _accept_revision(state, "新正文", auto_mode=False)
    assert command.goto == "reflection_node"
    assert command.update["current_chapter_content"] == "新正文"
    audit = command.update["revision_history"][-1]
    assert audit["goal_contract_id"] == state["chapter_outlines"][0]["goal_contract"]["id"]
    assert audit["before_hash"] != audit["after_hash"]


def test_accepting_quality_defects_does_not_waive_goals():
    with pytest.raises(InvalidReviewDecisionError, match="目标验收未通过"):
        _choice_command(ReviewDecision("accept"), [], {"goal_review_required": True})


@pytest.mark.asyncio
async def test_persist_blocks_before_any_database_or_fact_side_effect():
    state = goal_state()
    with patch("application.agents.persist_node.check_fact_artifact", new_callable=AsyncMock) as facts:
        with pytest.raises(QualityGateReviewRequired, match="目标验收未通过"):
            await persist_node(state, {"configurable": {}})
        facts.assert_not_called()


@pytest.mark.asyncio
async def test_revision_proposal_cannot_overwrite_newer_body():
    state = goal_state()
    update = _next_after_revision(state, "修订正文").update
    changed = {**state, **update, "current_chapter_content": "别人更新的正文"}
    with pytest.raises(RetryableWorkflowError, match="旧正文"):
        await revision_review_node(changed, {"configurable": {}})


@pytest.mark.asyncio
async def test_patch_failure_does_not_silently_expand_scope():
    state = {**goal_state(), "quality_gate": {"decision": "patch"}, "reflection_issues": []}
    config = {"configurable": {"llm_config": {"llm_instance": object()}}}
    with patch("application.agents.revision_node.bind_chapter_fact_input", new_callable=AsyncMock, return_value=(config, {})), \
         patch("application.agents.revision_node._generate_patch", new_callable=AsyncMock, side_effect=RetryableWorkflowError("bad anchor")), \
         patch("application.agents.revision_node._generate_refactor", new_callable=AsyncMock) as refactor:
        with pytest.raises(RetryableWorkflowError, match="原稿已保留"):
            await revision_node(state, config)
        refactor.assert_not_called()


@pytest.mark.asyncio
async def test_high_quality_review_still_enters_goal_gate():
    state = goal_state()
    raw = {**report_for(state), "overall_quality_score": 1,
           "word_count_analysis": {"total_count": 3000, "is_valid_word_count": True, "effective_density": 100},
           "issues": []}
    raw["goal_checks"].pop()
    with patch("application.agents.reflection_node._review_content", new_callable=AsyncMock, return_value=raw):
        command = await reflection_node(state, {"configurable": {"llm_config": {"llm_instance": object()}}})
    gate = command.update["pending_proposal"]["payload"]["gate"]
    assert command.goto == "reflection_review_node"
    assert gate["goal_review_required"]
    assert gate["score"] == 1


def test_book_constraints_and_original_user_summary_are_bound_separately():
    state = goal_state()
    state["author_config"] = {"hard_constraints": ["不新增超自然力量", "主角不得换人"]}
    state["summary"] = "通过真实票据解决误会"
    state["chapter_outlines"][0]["goal_contract"] = compile_goal_contract(state)
    contract = current_goal_contract(state)
    assert len([g for g in contract["requirements"] if g["source"] == "author_config"]) == 2
    assert any(g["id"] == "user:summary" and g["expected"] == state["summary"] for g in contract["requirements"])
    state["author_config"]["hard_constraints"].pop()
    with pytest.raises(QualityGateReviewRequired):
        current_goal_contract(state)


@pytest.mark.parametrize("length,status", [(2699, "blocked"), (2700, "passed"), (3300, "passed"), (3301, "blocked")])
def test_scale_boundary_examples_are_independent_of_model(length, status):
    state = goal_state()
    content = "找出原册页，归还失物。".ljust(length, "文")
    assert evaluate_goals(state, report_for(state), content)["status"] == status


def test_missing_prior_word_count_is_unknown_not_assumed_zero():
    state = goal_state()
    state["current_chapter_index"] = 1
    state["novel_plan"]["scale"].update(target_chapters=2, target_total_words=6000)
    state["novel_plan"]["chapter_slots"][0]["chapter_number"] = 2
    state["completed_chapters"] = [{"chapter_index": 0, "word_count": "3000"}]
    state["chapter_outlines"][0]["goal_contract"] = compile_goal_contract(state)
    result = evaluate_goals(state, report_for(state), state["current_chapter_content"])
    assert result["status"] == "blocked"
    assert result["checks"][-1]["status"] == "unknown"


def test_real_deferral_and_structural_breaches_cannot_be_hidden_by_positive_checks():
    state = goal_state()
    result = report_for(state)
    result["plan_fulfillment"]["ending_contract_breached"] = True
    assert evaluate_goals(state, result, state["current_chapter_content"])["status"] == "blocked"


def test_patch_scope_is_evidence_bound_and_cannot_be_whole_chapter():
    content = "查出原册页的证据。".ljust(3000, "文")
    issues = [{"issue_id": "e-1", "evidence": "查出原册页"}]
    valid = {"edits": [{"issue_id": "e-1", "anchor": "查出原册页的证据。", "replacement": "查到原册页并核对来源。"}]}
    _check_goal_patch_scope(valid, issues, content)
    valid["edits"][0]["anchor"] = content
    with pytest.raises(RetryableWorkflowError, match="范围"):
        _check_goal_patch_scope(valid, issues, content)
    valid["edits"][0]["anchor"] = "完全不相关的另外一段"
    with pytest.raises(RetryableWorkflowError, match="原文证据"):
        _check_goal_patch_scope(valid, issues, content)


@pytest.mark.asyncio
async def test_verified_content_reaches_persistence_without_an_extra_model_call():
    state = goal_state()
    state["total_outline"]["total_chapters"] = 1
    acceptance = evaluate_goals(state, report_for(state), state["current_chapter_content"])
    state["quality_gate"] = {"decision": "pass", "goal_acceptance": acceptance}
    from langgraph.types import Command
    with patch("application.agents.persist_node.check_fact_artifact", new_callable=AsyncMock, return_value=Command(goto="persist_node")), \
         patch("application.agents.persist_node._persist_chapter", new_callable=AsyncMock) as store:
        command = await persist_node(state, {"configurable": {}})
    store.assert_awaited_once()
    assert command.update["completed_chapters"][0]["word_count"] == len(state["current_chapter_content"])


def test_writer_projection_includes_fixed_goals_not_only_outline_actions():
    from application.prompts.chapter_writer_prompts import _build_contract_block

    state = goal_state()
    prompt = _build_contract_block(state["chapter_outlines"][0])
    assert "固定目标契约" in prompt
    assert "查出原册页" in prompt and "归还失物" in prompt
    assert "target_total_words" in prompt


@pytest.mark.asyncio
async def test_writer_does_not_pad_valid_goal_length_to_old_global_minimum():
    from application.agents.chapter_writer_node import chapter_writer_node

    state = goal_state()
    content = "找出原册页，归还失物。".ljust(2800, "文")
    config = {"configurable": {"llm_config": {"llm_instance": object()}}}
    with patch("application.agents.chapter_writer_node.bind_chapter_fact_input", new_callable=AsyncMock, return_value=(config, {})), \
         patch("application.agents.chapter_writer_node._generate_draft", new_callable=AsyncMock, return_value=(content, [])), \
         patch("application.agents.chapter_writer_node._final_word_check", new_callable=AsyncMock) as expansion, \
         patch("application.agents.chapter_writer_node.check_fact_artifact", new_callable=AsyncMock, side_effect=lambda s, c, text, kind, command: command):
        command = await chapter_writer_node(state, config)
    expansion.assert_not_called()
    assert command.update["current_chapter_content"] == content
