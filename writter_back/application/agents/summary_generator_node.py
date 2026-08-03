"""生成并审核双视图小说简介。"""

from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from application.prompts.summary_prompts import (
    SUMMARY_SCHEMA,
    SUMMARY_TEMPERATURE,
    SUMMARY_TOP_P,
    build_summary_prompt,
)
from application.proposals import (
    proposal_update,
    proposal_matches,
    require_proposal,
    request_decision,
    unpack_decision,
)
from application.schemas.agent_state import NovelAgentState
from application.streaming import emit_workflow_event


def _normalize_summary(value: Any) -> dict[str, str]:
    if isinstance(value, str):
        text = value.strip()
        return {"reader_blurb": text, "editorial_brief": text}
    if not isinstance(value, dict):
        return {"reader_blurb": "", "editorial_brief": ""}
    reader = str(value.get("reader_blurb", "") or "").strip()
    editorial = str(value.get("editorial_brief", "") or "").strip()
    return {"reader_blurb": reader, "editorial_brief": editorial or reader}


def _accept_summary(summary: dict[str, str]) -> Command:
    if not summary["reader_blurb"] or not summary["editorial_brief"]:
        raise RuntimeError("简介生成失败：简介内容不完整")
    return Command(
        goto="metadata_persist_node",
        update={
            "summary": summary["reader_blurb"],
            "generated_summary": summary["reader_blurb"],
            "editorial_summary": summary["editorial_brief"],
            "pending_proposal": None,
            "pending_proposal_decision": None,
            "__next_node__": "outline_node",
        },
    )


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
    generated = await llm.structured_generate(
        build_summary_prompt(
            state.get("novel_type", ""),
            state.get("title") or "",
            state.get("title_story_hint") or "",
            state.get("creative_brief"),
        ),
        SUMMARY_SCHEMA,
        temperature=SUMMARY_TEMPERATURE,
        top_p=SUMMARY_TOP_P,
    )
    summary = _normalize_summary(generated)
    if config["configurable"].get("auto_mode", False):
        return _accept_summary(summary)
    return Command(
        goto="summary_review_node",
        update=proposal_update(state, "summary", summary),
    )


async def summary_review_node(
    state: NovelAgentState,
    config: RunnableConfig,
) -> Command[Literal["metadata_persist_node", "summary_node"]]:
    """审核已保存的简介提案，本节点不得调用 LLM。"""
    del config
    proposal = require_proposal(state, "summary")
    summary = _normalize_summary(proposal["payload"])
    raw_decision = request_decision(
        state,
        proposal,
        action="confirm_or_provide_summary",
        message="AI 已生成小说简介，请确认或修改",
        ai_generated_summary=summary["reader_blurb"],
        ai_generated_summary_proposal=summary,
    )
    decision = unpack_decision(raw_decision, proposal)
    if decision == "regenerate":
        return Command(
            goto="summary_node",
            update={
                "pending_proposal": None,
                "pending_proposal_decision": None,
            },
        )
    selected = summary if decision == "accept" else _normalize_summary(decision)
    return _accept_summary(selected)
