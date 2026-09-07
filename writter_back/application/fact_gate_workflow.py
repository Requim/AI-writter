"""事实审校路由与可恢复人工确认，独立于质量接受。"""

from typing import Any
from uuid import UUID

from langgraph.types import Command
from langchain_core.runnables import RunnableConfig

from application.errors import InvalidReviewDecisionError, QualityGateReviewRequired, StaleWorkflowDecisionError
from application.fact_archive_guard import verify_fact_receipt
from application.fact_evaluation import evaluate_facts
from application.fact_workflow import _repository
from application.proposals import decide_proposal, proposal_update, require_proposal
from application.story_facts import source_digest
from service.value_objects.fact_gate import FactGateReport


def _cached(state: Any, snapshot: Any, content: str, kind: str) -> FactGateReport | None:
    try:
        report = FactGateReport.model_validate((state.get("fact_reports") or {}).get(kind))
        if (report.snapshot_digest, report.artifact_hash, report.tenant_id, report.novel_id,
            report.chapter_number, report.artifact_kind) == (snapshot.digest, source_digest(content),
            snapshot.tenant_id, snapshot.novel_id, snapshot.chapter_number, kind):
            return report
    except (ValueError, TypeError):
        pass
    return None


async def check_fact_artifact(state: Any, config: Any, content: str, kind: str, continuation: Command) -> Command:
    """检查全部新稿件；受限内部旧调用无仓储配置时保留兼容，不生成通过回执。"""
    store = _repository(config)
    if store is None:
        return continuation
    values = config["configurable"]
    snapshot = await store.capture_constraints(values["tenant_id"], values["novel_id"], state.get("current_chapter_index", 0) + 1)
    if (snapshot.tenant_id, snapshot.novel_id, snapshot.chapter_number) != (
        UUID(values["tenant_id"]), UUID(values["novel_id"]), state.get("current_chapter_index", 0) + 1,
    ):
        raise StaleWorkflowDecisionError("事实快照归属不匹配，未执行审校")
    report = _cached(state, snapshot, content, kind)
    if report is None:
        report = await evaluate_facts(snapshot, content, kind, values.get("llm_config", {}).get("llm_instance"))
    acknowledgements = dict(state.get("fact_acknowledgements") or {})
    update = {**{key: value for key, value in (continuation.update or {}).items() if key in {"chapter_constraints", "chapter_fact_input"}},
        "fact_reports": {**(state.get("fact_reports") or {}), kind: report.model_dump(mode="json")},
        "fact_gate_snapshot": snapshot.model_dump(mode="json"), "fact_acknowledgements": acknowledgements}
    ack = acknowledgements.get(kind)
    allowed = report.status == "pass" or (report.status == "unknown" and ack and ack.get("report_digest") == report.digest)
    if allowed:
        verify_fact_receipt(snapshot, report, content, ack)
        return Command(goto=continuation.goto, update={**(continuation.update or {}), **update})
    if values.get("direct_rewrite"):
        raise QualityGateReviewRequired("事实审校存在冲突或未知证据，重写结果未归档，请在创作工作流中审阅")
    pending = proposal_update(state, "fact_review", {"report": report.model_dump(mode="json")}, snapshot.chapter_number)
    return Command(goto="fact_review_node", update={**update, **pending,
        "fact_continuation": {"goto": continuation.goto, "update": continuation.update or {}},
        "fact_artifact": {"content": content, "kind": kind},
        **({"current_chapter_content": content} if kind == "body" else {})})


def _fact_retry(state: Any, decision: Any) -> Command:
    artifact = state.get("fact_artifact") or {}
    outline = artifact.get("kind") == "outline"
    instruction = decision.instruction or decision.feedback or "请依据已确认事实修复冲突，不得改写事实台账"
    update = {"pending_proposal": None, "pending_proposal_decision": None,
        "fact_continuation": None, "fact_artifact": None}
    if outline:
        return Command(goto="chapter_outline_node", update={**update, "chapter_outline_feedback": instruction, "chapter_outlines_input": None})
    if decision.action == "regenerate":
        return Command(goto="chapter_writer_node", update=update)
    return Command(goto="revision_node", update={**update, "current_chapter_content": artifact["content"],
        "user_decision": {"action": "revise", "instructions": instruction}})


async def _recheck_fact(state: Any, config: RunnableConfig, artifact: dict, continuation: dict) -> Command:
    reports = dict(state.get("fact_reports") or {})
    reports.pop(artifact["kind"], None)
    acknowledgements = dict(state.get("fact_acknowledgements") or {})
    acknowledgements.pop(artifact["kind"], None)
    next_state = {**state, "fact_reports": reports, "fact_acknowledgements": acknowledgements}
    command = Command(goto=continuation["goto"], update={"pending_proposal": None, "pending_proposal_decision": None,
        "fact_continuation": None, "fact_artifact": None, **continuation["update"]})
    return await check_fact_artifact(next_state, config, artifact["content"], artifact["kind"], command)


async def fact_review_node(state: Any, config: RunnableConfig) -> Command:
    """人工必须对当前事实提案确认，自动模式和质量接受不能替代。"""
    proposal = require_proposal(state, "fact_review", state.get("current_chapter_index", 0) + 1)
    report = FactGateReport.model_validate(proposal["payload"]["report"])
    artifact, continuation = state.get("fact_artifact"), state.get("fact_continuation")
    if not isinstance(artifact, dict) or not isinstance(continuation, dict):
        raise StaleWorkflowDecisionError("事实审核恢复信息缺失，请同步创作现场")
    if artifact.get("kind") != report.artifact_kind or source_digest(artifact["content"]) != report.artifact_hash:
        raise StaleWorkflowDecisionError("稿件已变化，旧确认不能复用")
    if artifact["kind"] == "body" and state.get("current_chapter_content") != artifact["content"]:
        raise StaleWorkflowDecisionError("稿件已变化，旧确认不能复用")
    decision = decide_proposal({**state, "workflow_schema_version": max(3, int(state.get("workflow_schema_version") or 2))},
        proposal, config, force_human=True, action="fact_review_required",
        message="发现明确事实冲突，必须修订后才能继续" if report.status == "blocked" else "事实证据尚未完整确认，请核对后决定",
        fact_report=report.model_dump(mode="json"), artifact_content=artifact["content"])
    if decision.action in {"regenerate", "revise"}:
        return _fact_retry(state, decision)
    if decision.action == "recheck":
        return await _recheck_fact(state, config, artifact, continuation)
    if decision.action != "accept" or report.status == "blocked":
        raise InvalidReviewDecisionError("明确事实冲突不可直接接受，请修订或重新生成")
    actor = getattr(config["configurable"].get("tenant_context"), "user_id", None)
    if actor is None:
        raise InvalidReviewDecisionError("缺少事实审核者身份")
    ack = {"report_digest": report.digest, "proposal_id": proposal["proposal_id"], "reviewed_by": str(actor)}
    next_state = {**state, "fact_acknowledgements": {**(state.get("fact_acknowledgements") or {}), artifact["kind"]: ack}}
    command = Command(goto=continuation["goto"], update={"pending_proposal": None, "pending_proposal_decision": None,
        "fact_continuation": None, "fact_artifact": None, **continuation["update"]})
    return await check_fact_artifact(next_state, config, artifact["content"], artifact["kind"], command)
