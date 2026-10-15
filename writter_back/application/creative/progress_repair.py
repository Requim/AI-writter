"""Evidence-led local repair progression under unchanged physical ceilings."""

from copy import deepcopy

from langgraph.types import Command

from application.automatic_recovery import quality_progress_update
from application.creative.errors import CreativePause
from application.goal_contract import current_goal_contract, fingerprint, require_goal_acceptance
from service.value_objects.creative_budget import ProgressRepairPolicy


def blocking_issues(gate: dict) -> list[dict]:
    return [row for row in gate.get("issues") or [] if row.get("priority_action") == "must_fix"
        and not row.get("issue_resolved")]


def issue_fingerprints(issues: list[dict]) -> list[str]:
    return sorted({fingerprint({"type": row.get("type"), "evidence": row.get("evidence")}) for row in issues})


def repair_gate_eligible(gate: dict, body: str, contract: dict) -> bool:
    report = gate.get("goal_acceptance") or {}
    words = gate.get("word_count_analysis") or {}
    issues = blocking_issues(gate)
    return (0 < len(body) <= 6000 and gate.get("decision") == "patch"
        and gate.get("score", 0) >= 0.8 and words.get("is_valid_word_count") is True
        and words.get("effective_density", 0) >= 70 and 0 < len(issues) <= 8
        and report.get("status") == "passed" and report.get("contract_id") == contract["id"]
        and report.get("content_hash") == fingerprint(body)
        and all(row.get("evidence_valid") is True and isinstance(row.get("evidence"), str)
            and 8 <= len(row["evidence"]) <= min(1500, len(body) * 0.3)
            and row["evidence"] in body for row in issues))


def _require_progress(state, gate, contract):
    current = set(issue_fingerprints(blocking_issues(gate)))
    history = [row for row in state.get("revision_history") or []
        if row.get("goal_contract_id") == contract["id"] and row.get("issues_before")]
    if history and history[-1].get("before_hash") == history[-1].get("after_hash") and history[-1].get("before_hash"):
        raise CreativePause("repair_no_progress", "上次修订未改变正文，不能重复领取修复额度")
    previous = {value for row in history for value in issue_fingerprints(row.get("issues_before") or [])}
    if current & previous:
        raise CreativePause("repair_no_progress", "既有问题仍未解决或再次出现，不能盲目追加修订")


def progress_repair_command(state, gate, policy, *, available):
    if policy is None:
        raise CreativePause("repair_policy_missing", "未授权按进展分配修订额度")
    policy = ProgressRepairPolicy.model_validate(policy)
    body = state.get("current_chapter_content") or ""
    contract = current_goal_contract(state)
    if (state.get("author_mode") != "autonomous_v1" or not contract
        or not repair_gate_eligible(gate, body, contract)
        or not require_goal_acceptance({**state, "quality_gate": gate}, body)):
        raise CreativePause("repair_evidence_invalid", "定向修订缺少当前正文的完整目标验收和问题证据")
    if available < policy.local_minimum:
        raise CreativePause("budget_exhausted", "剩余额度不足最小局部修订与独立验收周期")
    _require_progress(state, gate, contract)
    proof = {"mode": policy.mode, "body_hash": fingerprint(body), "contract_id": contract["id"],
        "issue_fingerprints": issue_fingerprints(blocking_issues(gate))}
    proof["id"] = fingerprint(proof)
    revised_gate = deepcopy(gate)
    revised_gate.pop("scoped_goal_repair", None)
    revised_gate["repair_progress"] = proof
    return Command(goto="revision_node", update={
        "quality_gate": revised_gate, "reflection_issues": gate["issues"],
        **quality_progress_update(state, proof),
        "user_decision": {"action": "revise", "instructions": None},
        "pending_proposal": None, "pending_proposal_decision": None,
    })


def progress_review_replay(state, initial, policy, available):
    if not initial or int(state.get("current_chapter_index") or 0) + 1 != initial["chapter"]:
        return None
    if fingerprint(state.get("current_chapter_content") or "") != initial["content_hash"]:
        return None
    return progress_repair_command(state, initial["gate"], policy, available=available)


def editorial_legacy_replay(state, policy):
    if policy is None:
        return None
    ProgressRepairPolicy.model_validate(policy)
    proposal = state.get("pending_proposal") or {}
    payload = proposal.get("payload") or {}
    chapter = int(state.get("current_chapter_index") or 0) + 1
    if (proposal.get("kind") != "reflection" or proposal.get("chapter_number") != chapter
        or payload.get("status") != "unavailable"
        or not str(payload.get("reason") or "").startswith("Editorial ")
        or not state.get("current_chapter_content")):
        return None
    from application.editorial_review import PROTOCOL, _binding, _templates

    binding = _binding(state["current_chapter_content"], _templates())
    identity = fingerprint(binding)
    recovery = deepcopy(state.get("automatic_recovery") or {})
    replays = list(recovery.get("editorial_protocol_replays") or [])
    if any(row["id"] == identity for row in replays):
        return None
    replays.append({"id": identity, "protocol": PROTOCOL,
        "body_sha256": binding["body_sha256"], "prompt_sha256": binding["prompt_sha256"],
        "source_proposal_id": proposal["proposal_id"], "reason": payload["reason"]})
    recovery["editorial_protocol_replays"] = replays
    return Command(goto="reflection_node", update={
        "automatic_recovery": recovery, "pending_proposal": None, "pending_proposal_decision": None,
    })
