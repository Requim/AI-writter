"""Generate and select premise-grounded title candidates."""

import logging
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from application.prompts.title_prompts import (
    TITLE_CANDIDATES_SCHEMA,
    TITLE_TEMPERATURE,
    TITLE_TOP_P,
    build_title_prompt,
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

logger = logging.getLogger("uvicorn")


def _score(candidate: dict[str, Any]) -> float:
    try:
        return float(candidate.get("total_score", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _normalize_candidates(value: Any) -> list[dict[str, Any]]:
    raw = value.get("candidates", []) if isinstance(value, dict) else []
    candidates = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "") or "").strip()
        if len(title) < 4:
            continue
        candidates.append({**item, "title": title, "hint": str(item.get("hint", "") or "").strip()})
    return sorted(candidates, key=_score, reverse=True)[:8]


def _resolve_choice(choice: Any, candidates: list[dict[str, Any]]) -> dict[str, str]:
    fallback = candidates[0]
    if isinstance(choice, dict):
        return {"title": str(choice.get("title", fallback["title"])), "hint": str(choice.get("hint", ""))}
    if isinstance(choice, int) and 0 <= choice < len(candidates):
        return {"title": candidates[choice]["title"], "hint": str(candidates[choice].get("hint", ""))}
    if isinstance(choice, str) and choice not in {"accept", "regenerate"}:
        return {"title": choice.strip() or fallback["title"], "hint": ""}
    return {"title": fallback["title"], "hint": str(fallback.get("hint", ""))}


def _confirmed_characters(state: NovelAgentState) -> list[dict[str, Any]]:
    design = state.get("character_design")
    characters = design.get("characters") if isinstance(design, dict) else []
    return characters if isinstance(characters, list) else []


async def title_generator_node(
    state: NovelAgentState, config: RunnableConfig
) -> Command[Literal["summary_node", "title_review_node", "metadata_persist_node"]]:
    """使用用户书名，或生成候选并保存为待审核提案。"""
    if state.get("title"):
        return Command(goto="summary_node")
    if proposal_matches(state, "title"):
        return Command(goto="title_review_node")
    llm = config["configurable"].get("llm_config", {}).get("llm_instance")
    if not llm:
        raise RuntimeError("书名生成失败：LLM 不可用")
    emit_workflow_event(
        "status", {"status": "started", "message": "正在生成书名候选"},
        "title_node",
    )
    prompt = build_title_prompt(
            state.get("novel_type", ""),
            state.get("creative_brief"),
            _confirmed_characters(state),
        )
    result = await llm.structured_generate(
        append_review_feedback(prompt, state.get("title_feedback")),
        TITLE_CANDIDATES_SCHEMA,
        temperature=TITLE_TEMPERATURE,
        top_p=TITLE_TOP_P,
    )
    candidates = _normalize_candidates(result)
    if not candidates:
        raise RuntimeError("书名生成失败：模型未返回有效候选")
    return Command(
        goto="title_review_node",
        update={**proposal_update(state, "title", candidates), "title_feedback": None},
    )


def _accept_title(selected: dict[str, str]) -> Command:
    logger.info("【书名审核节点】选择书名=%s", selected["title"])
    return Command(
        goto="metadata_persist_node",
        update={
            "title": selected["title"],
            "generated_title": selected["title"],
            "title_story_hint": selected["hint"],
            "title_feedback": None,
            "pending_proposal": None,
            "pending_proposal_decision": None,
            "__next_node__": "summary_node",
        },
    )


async def title_review_node(
    state: NovelAgentState, config: RunnableConfig
) -> Command[Literal["metadata_persist_node", "title_node"]]:
    """审核已保存的书名候选，本节点不得调用 LLM。"""
    proposal = require_proposal(state, "title")
    candidates = proposal["payload"]
    decision = decide_proposal(
        state,
        proposal,
        config,
        action="confirm_or_provide_title",
        message="AI 已生成并评估书名候选，请选择或输入自定义书名",
        ai_suggestions=candidates,
    )
    if decision.action == "accept":
        return _accept_title(_resolve_choice(candidates[0], candidates))
    if decision.action == "replace":
        return _accept_title(_resolve_choice(decision.value, candidates))
    feedback = (
        decision.instruction if decision.action == "revise" else decision.feedback
    )
    return _regenerate_title(feedback)


def _regenerate_title(feedback: str) -> Command:
    return Command(
        goto="title_node",
        update={
            "pending_proposal": None,
            "pending_proposal_decision": None,
            "title_feedback": feedback or None,
        },
    )
