"""生成提案的 checkpoint 协议与决策兼容层。"""

from typing import Any, cast
from uuid import uuid4

from langgraph.types import interrupt

from application.errors import StaleWorkflowDecisionError
from application.prompts.version import PROMPT_VERSION
from application.schemas.agent_state import NovelAgentState, PendingProposal

PROPOSAL_KINDS = {
    "creative_brief",
    "title",
    "summary",
    "outline",
    "chapter_outline",
    "reflection",
    "revision",
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
    schema_version = int(state.get("workflow_schema_version") or 3)
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


def unpack_decision(raw: Any, proposal: PendingProposal) -> Any:
    """解析 v3 决策信封，同时兼容旧版原始字符串或字典。"""
    if not isinstance(raw, dict) or "decision" not in raw:
        return raw
    proposal_id = raw.get("proposal_id")
    if proposal_id != proposal["proposal_id"]:
        raise StaleWorkflowDecisionError("提案已更新，本次决定未执行")
    decision = raw.get("decision")
    if decision == "modify":
        return raw.get("value")
    return decision


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
    if int(state.get("workflow_schema_version") or 3) < 3:
        return interrupt(
            {
                **legacy_fields,
                "chapter_number": proposal.get("chapter_number"),
            }
        )
    return interrupt(review_payload(proposal, **legacy_fields))
