from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.agents.reflection_node import _quality_gate, reflection_node
from application.fulfillment import PlanFulfillment, normalize_fulfillment


def reviewed_result():
    return {
        "overall_quality_score": 0.95, "passed": True,
        "word_count_analysis": {"total_count": 4000, "effective_density": 90, "is_valid_word_count": True},
        "issues": [],
        "plan_fulfillment": {
            "must_happen_covered": [], "missing_required_events": [],
            "state_delta_fulfilled": True, "deferred_items": [],
            "volume_boundary_breached": False, "core_arc_breached": False,
            "ending_contract_breached": False, "scale_change_required": False,
        },
        "tactical_fulfillment": {
            "tactical_goal_fulfilled": True, "approach_followed": True,
            "exit_hook_established": True, "deviations": [],
        },
    }


@pytest.mark.parametrize("value", [None, {}, [], {"state_delta_fulfilled": True}])
def test_missing_report_never_invents_success(value):
    report = normalize_fulfillment(value, PlanFulfillment)
    assert report["status"] == "unknown"
    assert report.get("state_delta_fulfilled") is not True


@pytest.mark.parametrize("field", ["plan_fulfillment", "tactical_fulfillment"])
def test_missing_report_blocks_automatic_acceptance(field):
    result = reviewed_result()
    del result[field]
    gate, _ = _quality_gate(result, "正文", require_fulfillment=True)
    assert gate["decision"] == "human_review"
    assert gate["fulfillment_review_required"] is True


@pytest.mark.parametrize("value", ["false", "true", 0, 1, None])
def test_boolean_fields_are_strict(value):
    result = reviewed_result()
    result["plan_fulfillment"]["state_delta_fulfilled"] = value
    gate, _ = _quality_gate(result, "正文", require_fulfillment=True)
    assert gate["plan_fulfillment"]["status"] == "unknown"
    assert gate["decision"] != "pass"


@pytest.mark.parametrize(("report", "field", "value"), [
    ("plan_fulfillment", "state_delta_fulfilled", False),
    ("plan_fulfillment", "core_arc_breached", True),
    ("plan_fulfillment", "missing_required_events", ["尚未揭示身份"]),
    ("tactical_fulfillment", "approach_followed", False),
    ("tactical_fulfillment", "deviations", ["未按计划推进"]),
])
def test_reported_deviation_cannot_be_overruled_by_high_score(report, field, value):
    result = deepcopy(reviewed_result())
    result[report][field] = value
    gate, _ = _quality_gate(result, "正文", require_fulfillment=True)
    assert gate["decision"] == "human_review"


def test_complete_reports_can_pass_and_legacy_remains_compatible():
    result = reviewed_result()
    gate, _ = _quality_gate(result, "正文", require_fulfillment=True)
    assert gate["decision"] == "pass"
    del result["plan_fulfillment"]
    legacy, _ = _quality_gate(result, "正文")
    assert legacy["decision"] == "pass"
    assert legacy["plan_fulfillment"]["status"] == "unknown"


@pytest.mark.asyncio
async def test_schema_five_routes_missing_fulfillment_to_review(monkeypatch):
    module = reflection_node.__globals__
    monkeypatch.setitem(module, "require_planning_v1", AsyncMock())
    monkeypatch.setitem(module, "emit_workflow_event", lambda *_args: None)
    result = reviewed_result()
    del result["tactical_fulfillment"]
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value=result))
    command = await reflection_node(
        {"workflow_schema_version": 5, "current_chapter_content": "正文", "current_chapter_index": 0},
        {"configurable": {"auto_mode": True, "llm_config": {"llm_instance": llm}}},
    )
    assert command.goto == "reflection_review_node"
    assert command.update["pending_proposal"]["payload"]["gate"]["decision"] == "human_review"
