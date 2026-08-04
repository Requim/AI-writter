"""生成提案的 checkpoint 协议与决策兼容层。"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast
from uuid import uuid4

from langgraph.types import interrupt

from application.errors import InvalidReviewDecisionError, StaleWorkflowDecisionError
from application.prompts.version import PROMPT_VERSION
from application.schemas.agent_state import NovelAgentState, PendingProposal

PROPOSAL_KINDS = {
    "creative_brief",
    "character_design",
    "title",
    "summary",
    "outline",
    "chapter_outline",
    "reflection",
    "revision",
}
LEGACY_WORKFLOW_SCHEMA_VERSION = 2
CURRENT_WORKFLOW_SCHEMA_VERSION = 4
ReviewAction = Literal["accept", "regenerate", "revise", "replace"]


@dataclass(frozen=True)
class ReviewDecision:
    """审核节点唯一允许消费的结构化决定。"""

    action: ReviewAction
    value: Any = None
    instruction: str = ""
    feedback: str = ""


_REPLACEMENT_TYPES: dict[str, tuple[type, ...]] = {
    "creative_brief": (Mapping,),
    "character_design": (Mapping,),
    "title": (str, Mapping),
    "summary": (str, Mapping),
    "outline": (Mapping,),
    "chapter_outline": (Mapping,),
    "reflection": (str,),
    "revision": (str,),
}


def _version_key(kind: str, chapter_number: int | None) -> str:
    return f"{kind}:{chapter_number}" if chapter_number is not None else kind


def create_proposal(
    state: NovelAgentState,
    kind: str,
    payload: Any,
    chapter_number: int | None = None,
) -> tuple[PendingProposal, dict[str, int]]:
    """创建提案并推进对应类型的版本号。"""
    versions = dict(state.get("proposal_versions") or {})
    key = _version_key(kind, chapter_number)
    version = int(versions.get(key, 0) or 0) + 1
    versions[key] = version
    if kind not in PROPOSAL_KINDS:
        raise ValueError(f"未知提案类型: {kind}")
    proposal = cast(PendingProposal, {
        "proposal_id": str(uuid4()),
        "kind": kind,
        "version": version,
        "payload": payload,
        "chapter_number": chapter_number,
        "prompt_version": PROMPT_VERSION,
    })
    return proposal, versions


def proposal_update(
    state: NovelAgentState,
    kind: str,
    payload: Any,
    chapter_number: int | None = None,
) -> dict[str, Any]:
    """返回写入 checkpoint 所需的标准状态更新。"""
    proposal, versions = create_proposal(state, kind, payload, chapter_number)
    schema_version = int(
        state.get("workflow_schema_version") or LEGACY_WORKFLOW_SCHEMA_VERSION
    )
    return {
        "pending_proposal": proposal,
        "proposal_versions": versions,
        "workflow_schema_version": schema_version,
        "prompt_version": PROMPT_VERSION,
    }


def require_proposal(
    state: NovelAgentState,
    kind: str,
    chapter_number: int | None = None,
) -> PendingProposal:
    """读取并校验当前提案，阻止跨阶段决定被错误应用。"""
    proposal = state.get("pending_proposal")
    if not isinstance(proposal, dict) or proposal.get("kind") != kind:
        raise StaleWorkflowDecisionError("当前待审核提案已经变化，请同步最新创作现场")
    if chapter_number is not None and proposal.get("chapter_number") != chapter_number:
        raise StaleWorkflowDecisionError("当前章节提案已经变化，请同步最新创作现场")
    return proposal


def proposal_matches(
    state: NovelAgentState, kind: str, chapter_number: int | None = None
) -> bool:
    """判断 checkpoint 中是否已有当前节点需要的提案。"""
    proposal = state.get("pending_proposal")
    if not isinstance(proposal, dict) or proposal.get("kind") != kind:
        return False
    return chapter_number is None or proposal.get("chapter_number") == chapter_number


def _replacement_decision(kind: str, value: Any) -> ReviewDecision:
    expected = _REPLACEMENT_TYPES.get(kind, (object,))
    if value is None or not isinstance(value, expected):
        raise InvalidReviewDecisionError("replace 必须提供当前审核类型的完整值")
    if isinstance(value, str) and not value.strip():
        raise InvalidReviewDecisionError("replace 不能提交空文本")
    if isinstance(value, Mapping) and not value:
        raise InvalidReviewDecisionError("replace 不能提交空对象")
    return ReviewDecision("replace", value=value)


def _feedback(raw: Mapping[str, Any]) -> str:
    value = raw.get("feedback")
    return value.strip() if isinstance(value, str) else ""


def _instruction(raw: Mapping[str, Any]) -> str:
    value = raw.get("instruction")
    return value.strip() if isinstance(value, str) else ""


def _modify_decision(
    raw: Mapping[str, Any], proposal: PendingProposal
) -> ReviewDecision:
    value = raw.get("value")
    if not isinstance(value, str):
        return _replacement_decision(proposal["kind"], value)
    instruction = _instruction(raw) or _feedback(raw) or value.strip()
    if instruction == "revise":
        instruction = ""
    if not instruction and value.strip() != "revise":
        raise InvalidReviewDecisionError("modify 必须提供修改要求")
    return ReviewDecision("revise", instruction=instruction)


def _envelope_decision(
    raw: Mapping[str, Any], proposal: PendingProposal
) -> ReviewDecision:
    if raw.get("proposal_id") != proposal["proposal_id"]:
        raise StaleWorkflowDecisionError("提案已更新，本次决定未执行")
    action = raw.get("decision")
    if action == "modify":
        return _modify_decision(raw, proposal)
    if action == "accept":
        return ReviewDecision("accept")
    if action == "regenerate":
        return ReviewDecision("regenerate", feedback=_feedback(raw))
    if action == "revise":
        instruction = _instruction(raw)
        if not instruction:
            raise InvalidReviewDecisionError("revise 必须提供 instruction")
        return ReviewDecision("revise", instruction=instruction)
    if action == "replace":
        return _replacement_decision(proposal["kind"], raw.get("value"))
    raise InvalidReviewDecisionError("未知审核决定")


def _legacy_decision(raw: Any, proposal: PendingProposal) -> ReviewDecision:
    if isinstance(raw, str):
        text = raw.strip()
        if text in {"accept", "regenerate"}:
            return ReviewDecision(cast(ReviewAction, text))
        if not text:
            raise InvalidReviewDecisionError("审核决定不能为空")
        if proposal["kind"] in {"title", "summary"}:
            return _replacement_decision(proposal["kind"], text)
        return ReviewDecision("revise", instruction=text)
    return _replacement_decision(proposal["kind"], raw)


def parse_review_decision(
    raw: Any, proposal: PendingProposal, *, allow_legacy: bool = False
) -> ReviewDecision:
    """校验并归一化审核决定；新协议必须携带当前提案标识。"""
    if isinstance(raw, Mapping) and "decision" in raw:
        return _envelope_decision(raw, proposal)
    if not allow_legacy:
        raise StaleWorkflowDecisionError("审核决定缺少当前提案标识")
    return _legacy_decision(raw, proposal)


def resolve_review_decision(
    state: NovelAgentState, raw: Any, proposal: PendingProposal
) -> ReviewDecision:
    """按 checkpoint 版本解析决定，仅旧 schema 接受无提案标识值。"""
    schema_version = int(state.get("workflow_schema_version") or 2)
    return parse_review_decision(raw, proposal, allow_legacy=schema_version < 3)


def unpack_decision(raw: Any, proposal: PendingProposal) -> Any:
    """兼容旧调用方；新审核节点应直接使用 ``ReviewDecision``。"""
    decision = parse_review_decision(raw, proposal)
    if decision.action in {"accept", "regenerate"}:
        return decision.action
    if decision.action == "revise":
        return decision.instruction or "revise"
    return decision.value


def review_payload(proposal: PendingProposal, **legacy_fields: Any) -> dict[str, Any]:
    """构造带 v3 元数据且兼容旧前端字段的 interrupt 数据。"""
    return {
        **legacy_fields,
        "proposal": dict(proposal),
        "proposal_id": proposal["proposal_id"],
        "proposal_kind": proposal["kind"],
        "proposal_version": proposal["version"],
        "prompt_version": proposal["prompt_version"],
        "chapter_number": proposal.get("chapter_number"),
    }


def request_decision(
    state: NovelAgentState,
    proposal: PendingProposal,
    **legacy_fields: Any,
) -> Any:
    """请求人工决定；旧 checkpoint 恢复时消费已注入的一次性决定。"""
    legacy_decision = state.get("pending_proposal_decision")
    if legacy_decision is not None:
        return legacy_decision
    return interrupt(review_payload(proposal, **legacy_fields))


def decide_proposal(
    state: NovelAgentState,
    proposal: PendingProposal,
    config: Mapping[str, Any],
    *,
    force_human: bool = False,
    **legacy_fields: Any,
) -> ReviewDecision:
    """自动模式直接接受已落盘提案，人工必需场景仍发出中断。"""
    configurable = config.get("configurable")
    values = configurable if isinstance(configurable, Mapping) else {}
    if values.get("auto_mode", False) and not force_human:
        return ReviewDecision("accept")
    raw = request_decision(state, proposal, **legacy_fields)
    return resolve_review_decision(state, raw, proposal)
