"""Keep whole-book constraints and precise repair instructions authoritative."""

import json
import pytest

from application.agents.reflection_node import _direct_rewrite_revision, _quality_gate
from application.agents.reflection_node import _allow_nonblocking_auto_fulfillment
from application.review_contract_rules import review_contract_rules


def test_contract_rules_do_not_apply_to_legacy_review():
    assert review_contract_rules({"issues": "array"}) == ""


def test_contract_review_distinguishes_advisory_and_binding_constraints():
    rules = review_contract_rules({"goal_checks": "array"})
    assert "不是分章硬上限" in rules
    assert "不得擅自套用到每章平均字数" in rules
    assert "必须发生而实际未发生" in rules
    assert "低密度、核心场景遗漏" in rules


def test_revision_gets_blockers_outside_issue_list():
    gate = {
        "decision": "human_review", "rubric_scores": {},
        "word_count_analysis": {"is_valid_word_count": False},
        "plan_fulfillment": {"missing_required_events": ["交付原件"]},
        "goal_acceptance": {"checks": [
            {"id": "a", "status": "failed", "reason": "没有完成交付"},
            {"id": "b", "status": "passed", "reason": "已满足"},
        ]},
    }
    command = _direct_rewrite_revision(gate, [])
    instruction = command.update["user_decision"]["instructions"]
    assert "交付原件" in instruction
    assert "没有完成交付" in instruction
    assert json.dumps({"id": "b", "status": "passed", "reason": "已满足"}, ensure_ascii=False) not in instruction
    assert "不得把验收报告写入小说正文" in instruction


def test_local_consistency_blocker_uses_patch_without_passing_gate():
    content = "卷宗已经合上，她却看见夹在里面的附页。"
    result = {
        "overall_quality_score": 0.9,
        "word_count_analysis": {
            "total_count": len(content), "effective_density": 85,
            "is_valid_word_count": True},
        "issues": [{"issue_id": "local", "type": "consistency", "severity": "medium",
                    "priority_action": "must_fix", "evidence": content}],
        "hard_failures": ["local"],
    }
    gate, _ = _quality_gate(result, content)
    assert gate["decision"] == "patch"
    assert gate["hard_failures"] == ["local"]
    result["issues"][0]["type"] = "logic"
    assert _quality_gate(result, content)[0]["decision"] == "refactor"
    result["issues"][0]["type"] = "consistency"
    result["overall_quality_score"] = 0.4
    assert _quality_gate(result, content)[0]["decision"] == "refactor"


@pytest.mark.parametrize("score,valid,density", [(0.7, True, 85), (0.9, False, 85), (0.9, True, 60)])
def test_fulfillment_exception_cannot_override_quality_failure(score, valid, density):
    gate = {
        "decision": "human_review", "score": score,
        "word_count_analysis": {"is_valid_word_count": valid, "effective_density": density},
        "fulfillment_review_required": True, "hard_failures": [],
        "plan_fulfillment": {"status": "reviewed"},
        "tactical_fulfillment": {"status": "reviewed", "tactical_goal_fulfilled": True,
                                "approach_followed": True, "exit_hook_established": True},
    }
    _allow_nonblocking_auto_fulfillment(gate, {"configurable": {"auto_mode": True}})
    assert gate["decision"] == "human_review"
    assert gate["fulfillment_review_required"] is True
