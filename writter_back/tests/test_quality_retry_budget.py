"""显式重试开启新预算，普通恢复不能重置预算。"""

import pytest

from application.agents.reflection_node import _route_quality_result
from application.automatic_recovery import recovery_update
from application.errors import AutomaticRecoveryExhausted
from application.orchestrator import NovelOrchestrator


def test_explicit_quality_retry_preserves_cumulative_history_and_fact_budget():
    state = {
        "current_chapter_index": 1, "revision_attempts": 5,
        "automatic_recovery": {"chapter": 1, "attempts": {
            "质量审读": 5, "审读重试": 2, "事实审校:body": 1}},
    }
    update = NovelOrchestrator._reset_fact_retry_budget(state, "reflection_review_node")
    assert update["automatic_recovery"]["attempts"] == {"事实审校:body": 1}
    assert update["automatic_recovery"]["quality_revision_baseline"] == 5
    current = {**state, **update}
    gate = {"decision": "patch", "score": 0.7}
    config = {"configurable": {"auto_mode": True}}
    for count in range(5):
        result = _route_quality_result(current, config, gate, [])
        assert result.goto == "revision_node"
        current.update(result.update)
        current["revision_attempts"] = 6 + count
    with pytest.raises(AutomaticRecoveryExhausted):
        _route_quality_result(current, config, gate, [])
    assert state["revision_attempts"] == 5


def test_unrelated_recovery_preserves_retry_baseline():
    state = {"current_chapter_index": 1, "automatic_recovery": {
        "chapter": 1, "quality_revision_baseline": 5, "attempts": {}}}
    assert recovery_update(state, "审读重试")["automatic_recovery"]["quality_revision_baseline"] == 5
    assert "quality_revision_baseline" not in recovery_update(
        {**state, "current_chapter_index": 2}, "审读重试"
    )["automatic_recovery"]


def test_replayed_dispatch_does_not_spend_an_uncompleted_revision():
    state = {"current_chapter_index": 1, "revision_attempts": 9,
             "automatic_recovery": {"chapter": 1, "quality_revision_baseline": 5,
                                    "attempts": {"质量审读": 5, "事实审校:body": 1}}}
    config = {"configurable": {"auto_mode": True}}
    gate = {"decision": "patch", "score": 0.7}
    for _ in range(3):
        result = _route_quality_result(state, config, gate, [])
        assert result.goto == "revision_node"
        state.update(result.update)
        assert state["automatic_recovery"]["attempts"] == {
            "质量审读": 5, "事实审校:body": 1}
    state["revision_attempts"] = 10
    with pytest.raises(AutomaticRecoveryExhausted):
        _route_quality_result(state, config, gate, [])


def test_next_chapter_has_own_budget_without_erasing_cumulative_count():
    state = {"current_chapter_index": 2, "revision_attempts": 14,
             "automatic_recovery": {"chapter": 1, "quality_revision_baseline": 9,
                                    "attempts": {"质量审读": 5}}}
    config = {"configurable": {"auto_mode": True}}
    gate = {"decision": "patch", "score": 0.7}
    state.update(recovery_update(state, "事实审校:body"))
    assert state["automatic_recovery"]["quality_revision_baseline"] == 14
    for count in range(5):
        command = _route_quality_result(state, config, gate, [])
        state.update(command.update)
        assert state["automatic_recovery"]["quality_revision_baseline"] == 14
        state["revision_attempts"] = 15 + count
    with pytest.raises(AutomaticRecoveryExhausted):
        _route_quality_result(state, config, gate, [])


def test_outline_counter_reset_does_not_leave_a_stale_high_baseline():
    state = {"current_chapter_index": 2, "revision_attempts": 0,
             "automatic_recovery": {"chapter": 2, "quality_revision_baseline": 14,
                                    "attempts": {"事实审校:body": 1}}}
    config = {"configurable": {"auto_mode": True}}
    gate = {"decision": "patch", "score": 0.7}
    for count in range(5):
        command = _route_quality_result(state, config, gate, [])
        state.update(command.update)
        assert state["automatic_recovery"]["quality_revision_baseline"] == 0
        state["revision_attempts"] = count + 1
    with pytest.raises(AutomaticRecoveryExhausted):
        _route_quality_result(state, config, gate, [])
