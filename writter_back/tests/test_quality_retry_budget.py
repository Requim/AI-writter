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
