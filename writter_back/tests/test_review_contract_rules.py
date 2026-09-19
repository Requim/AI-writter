"""Keep whole-book constraints and precise repair instructions authoritative."""

import json

from application.agents.reflection_node import _direct_rewrite_revision
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
