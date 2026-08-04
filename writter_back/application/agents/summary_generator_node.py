"""生成并审核双视图小说简介。"""

from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from application.errors import InvalidReviewDecisionError
from application.prompts.summary_prompts import (
    SUMMARY_SCHEMA,
    SUMMARY_TEMPERATURE,
    SUMMARY_TOP_P,
    build_summary_prompt,
)
from application.prompts.review_feedback import append_review_feedback
from application.proposals import (
    decide_proposal,
    proposal_update,
    proposal_matches,
    require_proposal,
)
from application.schemas.agent_state import NovelAgentState
from application.streaming import emit_workflow_event


def _normalize_summary(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    summary: dict[str, Any] = {
        "reader_blurb": str(raw.get("reader_blurb") or "").strip(),
        "editorial_brief": str(raw.get("editorial_brief") or "").strip(),
    }
    if raw.get("legacy_single_view") is True:
        summary["legacy_single_view"] = True
    if raw.get("human_review_required") is True:
        summary["human_review_required"] = True
    errors = raw.get("validation_errors")
    if isinstance(errors, list):
        summary["validation_errors"] = [str(item) for item in errors]
    return summary


def _canonical_summary_text(value: Any) -> str:
    return "".join(str(value or "").split())


def _summary_errors(summary: dict[str, Any]) -> list[str]:
    errors = []
    reader = summary.get("reader_blurb", "")
    editorial = summary.get("editorial_brief", "")
    if not reader:
        errors.append("reader_blurb 不能为空")
    if not editorial:
        errors.append("editorial_brief 不能为空")
    same = _canonical_summary_text(reader) == _canonical_summary_text(editorial)
    if reader and editorial and same and not summary.get("legacy_single_view"):
        errors.append("reader_blurb 与 editorial_brief 必须分别面向读者和创作规划")
    return errors


def _correction_prompt(prompt: str, errors: list[str]) -> str:
    details = "；".join(errors)
    return (
        f"{prompt}\n\n上一次结构化输出不合法：{details}。"
        "请仅重新输出完整 JSON；两个字段都必须非空、去除所有空白字符后不得相同。"
    )


def _confirmed_characters(state: NovelAgentState) -> list[dict[str, Any]]:
    design = state.get("character_design")
    characters = design.get("characters") if isinstance(design, dict) else []
    return characters if isinstance(characters, list) else []


def _accept_summary(summary: dict[str, Any]) -> Command:
    errors = _summary_errors(summary)
    if errors:
        raise InvalidReviewDecisionError("简介提案无效：" + "；".join(errors))
    return Command(
        goto="metadata_persist_node",
        update={
            "summary": summary["reader_blurb"],
            "generated_summary": summary["reader_blurb"],
            "editorial_summary": summary["editorial_brief"],
            "summary_feedback": None,
            "pending_proposal": None,
            "pending_proposal_decision": None,
            "__next_node__": "outline_node",
        },
    )


async def _generate_summary_candidate(
    llm: Any, prompt: str, feedback: Any,
) -> dict[str, Any]:
    current_prompt = append_review_feedback(prompt, feedback)
    summary: dict[str, Any] = {}
    errors: list[str] = []
    for attempt in range(2):
        generated = await llm.structured_generate(
            current_prompt, SUMMARY_SCHEMA,
            temperature=SUMMARY_TEMPERATURE, top_p=SUMMARY_TOP_P,
        )
        summary = _normalize_summary(generated)
        errors = _summary_errors(summary)
        if not errors:
            return summary
        if attempt == 0:
            current_prompt = _correction_prompt(current_prompt, errors)
    return {
        **summary, "human_review_required": True,
        "validation_errors": errors,
    }


async def summary_generator_node(
    state: NovelAgentState,
    config: RunnableConfig,
) -> Command[Literal["outline_node", "summary_review_node", "metadata_persist_node"]]:
    """生成结构化简介并保存提案，不执行人工审核。"""
    if state.get("summary"):
        return Command(goto="outline_node")
    if proposal_matches(state, "summary"):
        return Command(goto="summary_review_node")
    llm = config["configurable"].get("llm_config", {}).get("llm_instance")
    if not llm:
        raise RuntimeError("简介生成失败：LLM 不可用")
    emit_workflow_event(
        "status", {"status": "started", "message": "正在生成双视图简介"},
        "summary_node",
    )
    prompt = build_summary_prompt(
            state.get("novel_type", ""),
            state.get("title") or "",
            state.get("title_story_hint") or "",
            state.get("creative_brief"),
            _confirmed_characters(state),
        )
    summary = await _generate_summary_candidate(
        llm, prompt, state.get("summary_feedback"),
    )
    return Command(
        goto="summary_review_node",
        update={**proposal_update(state, "summary", summary), "summary_feedback": None},
    )


async def summary_review_node(
    state: NovelAgentState,
    config: RunnableConfig,
) -> Command[Literal["metadata_persist_node", "summary_node"]]:
    """审核已保存的简介提案，本节点不得调用 LLM。"""
    proposal = require_proposal(state, "summary")
    summary = _normalize_summary(proposal["payload"])
    force_human = bool(summary.get("human_review_required"))
    action = "summary_review_required" if force_human else "confirm_or_provide_summary"
    decision = decide_proposal(
        state,
        proposal,
        config,
        force_human=force_human,
        action=action,
        message="AI 已生成小说简介，请确认或修改",
        ai_generated_summary=summary["reader_blurb"],
        ai_generated_summary_proposal=summary,
    )
    if decision.action == "accept":
        return _accept_summary(summary)
    if decision.action == "replace":
        return _accept_summary(_replacement_summary(state, decision.value))
    feedback = (
        decision.instruction if decision.action == "revise" else decision.feedback
    )
    return _regenerate_summary(feedback)


def _replacement_summary(state: NovelAgentState, value: Any) -> dict[str, Any]:
    if isinstance(value, str) and int(state.get("workflow_schema_version") or 2) < 3:
        text = value.strip()
        return {
            "reader_blurb": text, "editorial_brief": text,
            "legacy_single_view": True,
        }
    return _normalize_summary(value)


def _regenerate_summary(feedback: str) -> Command:
    return Command(
        goto="summary_node",
        update={
            "pending_proposal": None,
            "pending_proposal_decision": None,
            "summary_feedback": feedback or None,
        },
    )
