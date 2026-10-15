"""Fact confirmations are not prose repairs; cumulative history is immutable."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.agents.revision_node import _generate_patch
from application.automatic_recovery import quality_revision_update
from application.errors import AutomaticRecoveryExhausted, RetryableWorkflowError
from tests.test_goal_contract import goal_state


def staged_quality_state():
    state = goal_state()
    goal = state["chapter_outlines"][-1]["goal_contract"]["id"]
    state.update(author_mode="autonomous_v1", revision_attempts=5,
        automatic_recovery={"chapter": 0, "quality_revision_baseline": 0,
            "attempts": {"质量审读": 5, "事实审校:body": 2, "事实提取:body": 2}})
    state["revision_history"] = [{
        "attempt": 1, "issues_before": [], "goal_contract_id": goal,
        "before_hash": "a" * 64, "after_hash": "a" * 64,
        "fact_staging_rebind": {"proposal_id": "11111111-1111-4111-8111-111111111111",
            "source_hash": "b" * 64, "fact_report_digest": "c" * 64},
    }, *[{"attempt": n, "issues_before": [{"priority_action": "must_fix"}],
          "goal_contract_id": goal} for n in range(2, 6)]]
    return state


def test_fact_confirmation_does_not_spend_a_quality_repair_or_reset_counters():
    state = staged_quality_state()
    original = deepcopy(state)
    update = quality_revision_update(state, maximum=5)
    recovery = update["automatic_recovery"]
    assert recovery["attempts"] == original["automatic_recovery"]["attempts"]
    assert recovery["quality_accounting"]["completed"] == 4
    assert recovery["quality_accounting"]["requested"] == 5
    assert recovery["quality_accounting"]["fact_confirmation_attempts"] == [1]
    assert state == original
    state["revision_attempts"] = 6
    with pytest.raises(AutomaticRecoveryExhausted):
        quality_revision_update(state, maximum=5)


@pytest.mark.parametrize("mutation", [
    "changed_body", "different_goal", "has_quality_issue", "invalid_digest",
    "invalid_proposal", "duplicate_attempt", "unclassified", "manual",
])
def test_unproven_history_never_grants_a_quality_offset(mutation):
    state = staged_quality_state()
    entry = state["revision_history"][0]
    actions = {
        "changed_body": lambda: entry.update(after_hash="d" * 64),
        "different_goal": lambda: entry.update(goal_contract_id="d" * 64),
        "has_quality_issue": lambda: entry.update(issues_before=[{"priority_action": "must_fix"}]),
        "invalid_digest": lambda: entry["fact_staging_rebind"].update(fact_report_digest="invalid"),
        "invalid_proposal": lambda: entry["fact_staging_rebind"].update(proposal_id="invalid"),
        "duplicate_attempt": lambda: state["revision_history"].append(deepcopy(entry)),
        "unclassified": lambda: entry.pop("fact_staging_rebind"),
        "manual": lambda: state.update(author_mode="manual"),
    }
    actions[mutation]()
    with pytest.raises(AutomaticRecoveryExhausted):
        quality_revision_update(state, maximum=5)


@pytest.mark.asyncio
async def test_autonomous_patch_cannot_edit_a_nonblocking_suggestion():
    body = "Blocking unique anchor. Nonblocking unique anchor. " + "Prose. " * 40
    state = {"author_mode": "autonomous_v1", "current_chapter_content": body,
        "reflection_issues": [
            {"issue_id": "block", "evidence": "Blocking unique anchor.",
             "evidence_valid": True, "priority_action": "must_fix"},
            {"issue_id": "optional", "evidence": "Nonblocking unique anchor.",
             "evidence_valid": True, "priority_action": "should_fix"},
        ]}
    llm = SimpleNamespace(structured_generate=AsyncMock(return_value={
        "edits": [{"issue_id": "optional", "anchor": "Nonblocking unique anchor.",
            "replacement": "Changed optional prose."}], "unresolved_issue_ids": [],
    }))
    with pytest.raises(RetryableWorkflowError, match="未对应审读问题"):
        await _generate_patch(llm, state, body, {}, "", "")
