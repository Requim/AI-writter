"""Apply evidence-scoped patches or full structural revisions."""

import logging
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from application.continuity import build_story_bible
from application.errors import RetryableWorkflowError
from application.prompts.revision_prompts import (
    PATCH_SCHEMA,
    PATCH_TEMPERATURE,
    REFACTOR_TEMPERATURE,
    build_expansion_prompt,
    build_patch_revision_prompt,
    build_refactor_revision_prompt,
    build_revision_system_prompt,
    build_user_instruction_revision_prompt,
    classify_revision_mode,
    format_issues_for_prompt,
)
from application.proposals import (
    ReviewDecision,
    decide_proposal,
    proposal_update,
    proposal_matches,
    require_proposal,
)
from application.schemas.agent_state import NovelAgentState
from application.streaming import collect_streamed_text, emit_workflow_event
from service.ports.llm_service import LLMService

logger = logging.getLogger("uvicorn")


def _patch_ranges(content: str, edits: list[dict], allowed_ids: set[str]) -> list[tuple[int, int, str]]:
    ranges = []
    for edit in edits:
        if not isinstance(edit, dict) or str(edit.get("issue_id", "")) not in allowed_ids:
            raise RetryableWorkflowError("章节局部修订失败：修改项未对应审读问题")
        anchor = edit.get("anchor")
        replacement = edit.get("replacement")
        if not isinstance(anchor, str) or not isinstance(replacement, str) or len(anchor) < 8:
            raise RetryableWorkflowError("章节局部修订失败：原文锚点无效")
        if content.count(anchor) != 1:
            raise RetryableWorkflowError("章节局部修订失败：原文锚点不唯一")
        start = content.index(anchor)
        ranges.append((start, start + len(anchor), replacement))
    ranges.sort(key=lambda item: item[0])
    if any(current[0] < previous[1] for previous, current in zip(ranges, ranges[1:])):
        raise RetryableWorkflowError("章节局部修订失败：修改范围重叠")
    return ranges


def apply_structured_patch(content: str, payload: Any, allowed_ids: set[str]) -> str:
    """校验并原子应用结构化局部修改，任何一项无效则不改正文。"""
    if not isinstance(payload, dict):
        raise RetryableWorkflowError("章节局部修订失败：模型未返回有效 JSON")
    unresolved = payload.get("unresolved_issue_ids", [])
    if not isinstance(unresolved, list):
        raise RetryableWorkflowError("章节局部修订失败：未解决问题列表格式无效")
    if any(str(item) in allowed_ids for item in unresolved):
        raise RetryableWorkflowError("章节局部修订失败：存在无法安全处理的问题")
    edits = payload.get("edits", [])
    if not isinstance(edits, list) or not edits:
        raise RetryableWorkflowError("章节局部修订失败：没有可应用的修改")
    if len(edits) > 12:
        raise RetryableWorkflowError("章节局部修订失败：修改项超过安全上限")
    ranges = _patch_ranges(content, edits, allowed_ids)
    revised = content
    for start, end, replacement in reversed(ranges):
        revised = revised[:start] + replacement + revised[end:]
    if not revised.strip() or len(revised) < len(content) * 0.8:
        raise RetryableWorkflowError("章节局部修订失败：修改范围过大")
    return revised


def _history_text(state: NovelAgentState) -> str:
    parts = []
    for entry in state.get("revision_history", []) or []:
        summary = "; ".join(
            f"{issue.get('issue_id', '?')}:{issue.get('type', '?')}"
            for issue in entry.get("issues_before", [])[:5]
        )
        parts.append(f"第{entry.get('attempt', 0)}次修订：{summary}")
    return "\n".join(parts)


def _full_revision_prompt(
    state: NovelAgentState, content: str, outline: dict, context: str, bible: str
) -> tuple[str, float, str]:
    decision = state.get("user_decision", {}) or {}
    instructions = decision.get("instructions")
    if instructions:
        prompt = build_user_instruction_revision_prompt(instructions, content, outline, context, bible)
        return prompt, 0.5, "user_instruction"
    issues = state.get("reflection_issues", []) or []
    prompt = build_refactor_revision_prompt(
        format_issues_for_prompt(issues), content, outline, _history_text(state), context, bible
    )
    return prompt, REFACTOR_TEMPERATURE, "refactor"


async def _generate_full(
    llm: LLMService, prompt: str, temperature: float, chapter_index: int
) -> str:
    emit_workflow_event(
        "content_delta", {"chapter_index": chapter_index, "operation": "reset", "text": ""}, "revision_node"
    )
    revised = await collect_streamed_text(
        llm, prompt, node="revision_node", chapter_index=chapter_index,
        system_prompt=build_revision_system_prompt(), temperature=temperature,
    )
    if not revised.strip():
        raise RetryableWorkflowError("章节修订失败：模型未返回正文")
    return revised


async def _generate_patch(
    llm: LLMService,
    state: NovelAgentState,
    content: str,
    outline: dict,
    context: str,
    bible: str,
) -> str:
    issues = [
        issue for issue in state.get("reflection_issues", []) or []
        if issue.get("priority_action") != "can_ignore" and issue.get("evidence_valid") is True
    ]
    allowed_ids = {str(issue.get("issue_id", "")) for issue in issues if issue.get("issue_id")}
    prompt = build_patch_revision_prompt(
        format_issues_for_prompt(issues), content, outline, _history_text(state), context, bible
    )
    payload = await llm.structured_generate(
        prompt=prompt, schema=PATCH_SCHEMA, system_prompt=build_revision_system_prompt(),
        temperature=PATCH_TEMPERATURE,
    )
    revised = apply_structured_patch(content, payload, allowed_ids)
    chapter_index = state.get("current_chapter_index", 0)
    emit_workflow_event(
        "content_delta", {"chapter_index": chapter_index, "operation": "reset", "text": ""}, "revision_node"
    )
    emit_workflow_event(
        "content_delta", {"chapter_index": chapter_index, "operation": "append", "text": revised}, "revision_node"
    )
    return revised


async def _expand_if_needed(
    llm: LLMService,
    revised: str,
    original: str,
    outline: dict,
    context: str,
    bible: str,
    index: int,
) -> str:
    if len(revised) >= len(original) * 0.8:
        return revised
    prompt = build_expansion_prompt(revised, outline, min(len(original), 7000), context, bible)
    return await _generate_full(llm, prompt, REFACTOR_TEMPERATURE + 0.1, index)


async def _generate_refactor(
    llm: LLMService,
    state: NovelAgentState,
    content: str,
    outline: dict,
    context: str,
    bible: str,
) -> str:
    index = state.get("current_chapter_index", 0)
    prompt, temperature, _ = _full_revision_prompt(state, content, outline, context, bible)
    revised = await _generate_full(llm, prompt, temperature, index)
    return await _expand_if_needed(llm, revised, content, outline, context, bible, index)


def _next_after_revision(state: NovelAgentState, revised: str) -> Command:
    chapter_number = state.get("current_chapter_index", 0) + 1
    update = proposal_update(
        state,
        "revision",
        {"revised_content": revised, "preview": revised[:500]},
        chapter_number,
    )
    return Command(goto="revision_review_node", update=update)


def _revision_review_fields(proposal: dict[str, Any]) -> dict[str, Any]:
    payload = proposal.get("payload") or {}
    preview = str(payload.get("preview") or "") if isinstance(payload, dict) else ""
    return {
        "action": "confirm_revision",
        "message": "内容已修订，请确认是否满意",
        "revised_content_preview": preview,
    }


async def revision_review_node(
    state: NovelAgentState, config: RunnableConfig
) -> Command[Literal["persist_node", "reflection_node", "revision_node"]]:
    """审核 checkpoint 中的修订提案，不再次调用模型。"""
    chapter_number = state.get("current_chapter_index", 0) + 1
    proposal = require_proposal(state, "revision", chapter_number)
    decision = decide_proposal(
        state, proposal, config, **_revision_review_fields(proposal)
    )
    payload = proposal.get("payload") or {}
    revised = str(payload.get("revised_content") or "")
    auto_mode = bool(config.get("configurable", {}).get("auto_mode", False))
    if decision.action == "accept":
        return _accept_revision(state, revised, auto_mode=auto_mode)
    if decision.action == "replace":
        return _accept_revision(state, str(decision.value), auto_mode=auto_mode)
    return _retry_revision(revised, decision)


def _revision_audit(state: NovelAgentState) -> dict[str, Any]:
    attempts = int(state.get("revision_attempts", 0) or 0) + 1
    issues = [
        dict(item) for item in state.get("reflection_issues", []) or []
        if isinstance(item, dict)
    ]
    history = list(state.get("revision_history", []) or [])
    history.append({"attempt": attempts, "issues_before": issues})
    return {"revision_attempts": attempts, "revision_history": history}


def _accept_revision(
    state: NovelAgentState, revised: str, *, auto_mode: bool = False,
) -> Command:
    common = {
        "current_chapter_content": revised,
        "pending_proposal": None,
        "pending_proposal_decision": None,
        **_revision_audit(state),
    }
    if auto_mode:
        return Command(goto="reflection_node", update=common)
    gate = {
        **(state.get("quality_gate") or {}),
        "decision": "user_accepted_revision",
    }
    return Command(
        goto="persist_node",
        update={
            **common,
            "quality_gate": gate,
            "quality_results": [gate],
        },
    )


def _retry_revision(revised: str, decision: ReviewDecision) -> Command:
    instructions = (
        decision.instruction if decision.action == "revise" else decision.feedback
    )
    update: dict[str, Any] = {
        "pending_proposal": None,
        "pending_proposal_decision": None,
        "user_decision": {
            "action": "revise",
            "instructions": instructions or None,
        },
    }
    if decision.action == "revise":
        update.update({
            "current_chapter_content": revised,
        })
    return Command(goto="revision_node", update=update)


async def revision_node(
    state: NovelAgentState, config: RunnableConfig
) -> Command[
    Literal[
        "chapter_writer_node",
        "persist_node",
        "reflection_node",
        "revision_node",
        "revision_review_node",
    ]
]:
    """根据服务端质量决策执行局部 Patch 或全文重构。"""
    chapter = state.get("current_chapter_index", 0) + 1
    if proposal_matches(state, "revision", chapter):
        return Command(goto="revision_review_node")
    decision = state.get("user_decision", {}) or {}
    if decision.get("action") == "accept":
        return Command(goto="persist_node")
    if decision.get("action") == "regenerate":
        return Command(goto="chapter_writer_node")
    llm = config["configurable"].get("llm_config", {}).get("llm_instance")
    if not llm:
        raise RetryableWorkflowError("章节修订失败：LLM 不可用")
    emit_workflow_event(
        "status", {"status": "started", "message": "正在生成正文修订提案"},
        "revision_node",
    )
    content = state.get("current_chapter_content", "")
    outline = state.get("chapter_outlines", [{}])[-1] if state.get("chapter_outlines") else {}
    total = state.get("total_outline", {})
    total = total if isinstance(total, dict) else {}
    context = state.get("memory_context", "")
    related = {"chapter_outline": outline, "chapter_content": content}
    bible = build_story_bible(total, related_context=related)
    gate_mode = (state.get("quality_gate", {}) or {}).get("decision")
    mode = gate_mode if gate_mode in {"patch", "refactor"} else classify_revision_mode(state.get("reflection_issues", []))
    if mode == "patch" and not decision.get("instructions"):
        try:
            revised = await _generate_patch(llm, state, content, outline, context, bible)
        except RetryableWorkflowError as exc:
            logger.warning("【修正节点】局部 Patch 无法安全应用，降级全文重构 | 原因=%s", exc)
            revised = await _generate_refactor(llm, state, content, outline, context, bible)
    else:
        revised = await _generate_refactor(llm, state, content, outline, context, bible)
    return _next_after_revision(state, revised)
