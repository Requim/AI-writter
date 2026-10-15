"""Replay a persisted failed goal review, never a fabricated acceptance."""

from copy import deepcopy

from langgraph.types import Command

from application.automatic_recovery import quality_revision_update
from application.goal_contract import current_goal_contract, fingerprint


def failed_repair_goal(gate: dict, control: dict) -> dict | None:
    report = gate.get("goal_acceptance") or {}
    failures = [row for row in report.get("checks", []) if row.get("status") != "passed"]
    words = gate.get("word_count_analysis") or {}
    blocking = [row for row in gate.get("issues", []) if row.get("priority_action") == "must_fix"
        and not row.get("issue_resolved")]
    if (gate.get("chapter_number") != 1 or gate.get("decision") != "human_review"
        or gate.get("goal_review_required") is not True or gate.get("score", 0) < 0.8
        or words.get("is_valid_word_count") is not True or words.get("effective_density", 0) < 70
        or blocking or gate.get("hard_failures") or report.get("status") != "blocked"
        or report.get("contract_id") != control.get("contract_id")
        or report.get("content_hash") != control.get("content_hash") or len(failures) != 1):
        return None
    row = failures[0]
    if (row.get("id") != control.get("goal_id") or row.get("status") != "failed"
        or not str(row.get("id", "")).startswith("ch1:must:")
        or row.get("evidence_valid") is not True or row.get("evidence_format_only") is True
        or not isinstance(row.get("expected"), str) or not row.get("reason")):
        return None
    return row


def applicable_goal_repair(state: dict, control: dict | None) -> bool:
    if not control or state.get("author_mode") != "autonomous_v1" or state.get("current_chapter_index", 0) != 0:
        return False
    body = state.get("current_chapter_content") or ""
    if not body or len(body) > 6000 or fingerprint(body) != control.get("content_hash"):
        return False
    if any(entry.get("scoped_goal_repair") == control.get("id") for entry in state.get("revision_history") or []):
        return False
    contract = current_goal_contract(state)
    finding = failed_repair_goal(control.get("gate") or {}, control)
    if not contract or contract["id"] != control.get("contract_id") or not finding:
        return False
    expected = next((row for row in contract["requirements"] if row["id"] == control.get("goal_id")), None)
    return bool(expected and expected["source"] == "accepted_plan" and expected["expected"] == finding["expected"]
        and isinstance(finding.get("evidence"), str) and finding["evidence"] in body
        and 8 <= len(finding["evidence"]) <= min(1500, len(body) * 0.3))


def goal_repair_command(state: dict, control: dict | None) -> Command | None:
    if not applicable_goal_repair(state, control):
        return None
    assert control is not None
    # A grant extends only an already exhausted five-repair cycle, not a fresh cycle.
    budget = quality_revision_update(state, maximum=6)
    accounting = budget["automatic_recovery"].get("quality_accounting") or {}
    if accounting.get("completed") != 5 or accounting.get("requested") != 6:
        return None
    gate = deepcopy(control["gate"])
    finding = failed_repair_goal(gate, control)
    assert finding is not None
    issue = {"issue_id": finding["id"], "type": "goal_coverage", "severity": "high",
        "priority_action": "must_fix", "issue_resolved": False, "evidence_valid": True,
        "evidence": finding["evidence"], "location": "已审读的必达事件原文",
        "description": finding["reason"], "suggestion": "局部补足原始必达事件：" + finding["expected"]}
    gate.update(decision="patch", source_decision="human_review", scoped_goal_repair=control["id"])
    return Command(goto="revision_node", update={
        "quality_gate": gate, "reflection_issues": [issue], **budget,
        "user_decision": {"action": "revise", "instructions": None},
        "pending_proposal": None, "pending_proposal_decision": None,
    })
