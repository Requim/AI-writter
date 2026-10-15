"""Citation failure retries the review, never rewrites already-fulfilled prose."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.agents.reflection_node import _apply_goal_gate, _route_quality_result
from application.errors import AutomaticRecoveryExhausted
from application.review_evidence import repair_goal_quotes
from tests.test_goal_contract import goal_state, report_for


def evidence_gate(state, mutation="invalid_quote"):
    raw = report_for(state)
    if mutation == "invalid_quote":
        raw["goal_checks"][0]["evidence"] = "没有这段引文"
    elif mutation == "failed":
        raw["goal_checks"][0]["status"] = "failed"
    elif mutation == "unknown":
        raw["goal_checks"][0]["status"] = "unknown"
    gate = {"decision": "pass", "score": 0.9, "hard_failures": [],
        "word_count_analysis": {"is_valid_word_count": True, "effective_density": 90}}
    _apply_goal_gate(state, raw, state["current_chapter_content"], gate)
    return gate


def test_evidence_format_failure_retries_review_without_modifying_body_or_revision_budget():
    state = {**goal_state(), "revision_attempts": 2}
    original = deepcopy(state)
    command = _route_quality_result(state, {"configurable": {"auto_mode": True}}, evidence_gate(state), [])
    assert command.goto == "reflection_node"
    assert "current_chapter_content" not in command.update
    assert "user_decision" not in command.update
    assert "revision_attempts" not in command.update
    assert command.update["quality_gate"]["goal_acceptance"]["status"] == "blocked"
    assert state == original


def test_evidence_only_review_retries_are_durable_and_finite():
    state = goal_state()
    config = {"configurable": {"auto_mode": True}}
    for _ in range(2):
        command = _route_quality_result(state, config, evidence_gate(state), [])
        state = {**state, **command.update}
    with pytest.raises(AutomaticRecoveryExhausted):
        _route_quality_result(state, config, evidence_gate(state), [])


@pytest.mark.parametrize("mutation", ["failed", "unknown"])
def test_real_goal_failure_is_not_relabelled_as_a_citation_format_problem(mutation):
    state = goal_state()
    command = _route_quality_result(state, {"configurable": {"auto_mode": True}}, evidence_gate(state, mutation), [])
    assert command.goto == "revision_node"
    assert command.update["quality_gate"]["goal_acceptance"]["status"] == "blocked"


@pytest.mark.asyncio
async def test_repair_resolves_model_selected_source_span_without_quote_reconstruction():
    content = "他递交申请。\n\n她盖章，交还回执。"
    row = {"id": "event-1", "status": "passed", "evidence": "他递交……交还回执。"}
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value={"goal_checks": [{
        "id": "event-1", "status": "passed", "evidence_start": "p1", "evidence_end": "p2",
        "reason": "同一次申请的递交与回执均已发生。"}]}))
    result = await repair_goal_quotes(llm, {"goal_checks": [row]}, content,
        {"requirements": [{"id": "event-1", "expected": "递交申请并收到回执"}]})
    assert result["goal_checks"][0]["evidence"] == content
    assert row["evidence"] == "他递交……交还回执。"


@pytest.mark.asyncio
@pytest.mark.parametrize("start,end", [("p2", "p1"), ("p0", "p2"), ("p1", "p999")])
async def test_invalid_source_span_never_becomes_accepted_evidence(start, end):
    row = {"id": "event-1", "status": "passed", "evidence": "不在正文"}
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value={"goal_checks": [{
        "id": "event-1", "status": "passed", "evidence_start": start, "evidence_end": end,
        "reason": "声称通过"}]}))
    result = await repair_goal_quotes(llm, {"goal_checks": [row]}, "申请。\n\n回执。",
        {"requirements": [{"id": "event-1", "expected": "递交申请并收到回执"}]})
    assert result["goal_checks"] == [row]
