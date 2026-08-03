"""Generate and select premise-grounded title candidates."""

import logging
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, interrupt

from application.prompts.title_prompts import (
    TITLE_CANDIDATES_SCHEMA,
    TITLE_TEMPERATURE,
    TITLE_TOP_P,
    build_title_prompt,
)
from application.schemas.agent_state import NovelAgentState

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


async def title_generator_node(
    state: NovelAgentState, config: RunnableConfig
) -> Command[Literal["summary_node", "title_node"]]:
    """使用用户书名，或生成并按明确评分选择候选书名。"""
    if state.get("title"):
        return Command(goto="summary_node")
    llm = config["configurable"].get("llm_config", {}).get("llm_instance")
    if not llm:
        raise RuntimeError("书名生成失败：LLM 不可用")
    result = await llm.structured_generate(
        build_title_prompt(state.get("novel_type", ""), state.get("creative_brief")),
        TITLE_CANDIDATES_SCHEMA,
        temperature=TITLE_TEMPERATURE,
        top_p=TITLE_TOP_P,
    )
    candidates = _normalize_candidates(result)
    if not candidates:
        raise RuntimeError("书名生成失败：模型未返回有效候选")
    if config["configurable"].get("auto_mode", False):
        choice = candidates[0]
    else:
        choice = interrupt(
            {
                "action": "confirm_or_provide_title",
                "message": "AI 已生成并评估书名候选，请选择或输入自定义书名",
                "ai_suggestions": candidates,
            }
        )
        if choice == "regenerate":
            return Command(goto="title_node")
    selected = _resolve_choice(choice, candidates)
    logger.info("【书名生成节点】选择书名=%s, 评分=%s", selected["title"], _score(candidates[0]))
    return Command(
        goto="summary_node",
        update={"title": selected["title"], "title_story_hint": selected["hint"]},
    )
