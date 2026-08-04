"""逐章细纲的生成节点与人工审核节点。"""

import json
import logging
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from application.continuity import normalize_chapter_contract, validate_chapter_contract
from application.reserved_names import (
    consume_reserved_introductions,
    hydrate_reserved_introductions,
)
from application.prompts.chapter_outline_prompts import (
    CHAPTER_OUTLINE_SCHEMA,
    build_chapter_outline_prompt,
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

logger = logging.getLogger("uvicorn")


def _total_outline(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _validated_outline(
    generated: Any, chapter_number: int, total_outline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(generated, dict) or not generated:
        raise RuntimeError("章节细纲生成失败：模型未返回有效 JSON")
    outline = normalize_chapter_contract(generated, chapter_number)
    outline = hydrate_reserved_introductions(outline, total_outline or {})
    issues = validate_chapter_contract(outline, chapter_number)
    if issues:
        raise RuntimeError(f"第 {chapter_number} 章细纲生成失败：" + "；".join(issues))
    word_count = outline.get("estimated_word_count", 5000)
    outline["estimated_word_count"] = max(3000, min(7000, int(word_count)))
    return outline


async def _generate_outline(
    state: NovelAgentState, config: RunnableConfig, chapter_number: int
) -> dict[str, Any]:
    llm = config["configurable"].get("llm_config", {}).get("llm_instance")
    if not llm:
        raise RuntimeError("章节细纲生成失败：LLM 不可用")
    emit_workflow_event(
        "status", {"status": "started", "message": f"正在生成第{chapter_number}章细纲"},
        "chapter_outline_node",
    )
    generated = await llm.structured_generate(
        prompt=build_chapter_outline_prompt(
            chapter_index=chapter_number,
            novel_type=state.get("novel_type", ""),
            title=state.get("title", ""),
            total_outline=_total_outline(state.get("total_outline")),
            memory_context=state.get("memory_context", ""),
        ),
        schema=CHAPTER_OUTLINE_SCHEMA,
        temperature=0.45,
    )
    return _validated_outline(
        generated, chapter_number, _total_outline(state.get("total_outline")),
    )


def _accept_outline_update(
    state: NovelAgentState, outline: dict[str, Any], *, clear_proposal: bool = False,
) -> dict[str, Any]:
    total = _total_outline(state.get("total_outline"))
    update: dict[str, Any] = {
        "chapter_outlines": [outline],
        "total_outline": consume_reserved_introductions(total, outline),
    }
    if clear_proposal:
        update.update({"pending_proposal": None, "pending_proposal_decision": None})
    return update


async def chapter_outline_node(
    state: NovelAgentState,
    config: RunnableConfig,
) -> Command[Literal["router_agent", "chapter_outline_review_node"]]:
    """生成当前章节细纲并保存提案，不执行人工审核。"""
    chapter_number = int(state.get("current_chapter_index", 0) or 0) + 1
    if proposal_matches(state, "chapter_outline", chapter_number):
        return Command(goto="chapter_outline_review_node")
    if state.get("chapter_outlines_input"):
        outline = _validated_outline(
            state["chapter_outlines_input"], chapter_number,
            _total_outline(state.get("total_outline")),
        )
        return Command(
            goto="router_agent",
            update={
                **_accept_outline_update(state, outline),
                "chapter_outlines_input": None,
            },
        )
    outline = await _generate_outline(state, config, chapter_number)
    if config["configurable"].get("auto_mode", False):
        return Command(goto="router_agent", update=_accept_outline_update(state, outline))
    return Command(
        goto="chapter_outline_review_node",
        update=proposal_update(state, "chapter_outline", outline, chapter_number),
    )


async def chapter_outline_review_node(
    state: NovelAgentState,
    config: RunnableConfig,
) -> Command[Literal["router_agent", "chapter_outline_node"]]:
    """审核已保存的章节细纲，本节点不得调用 LLM。"""
    del config
    chapter_number = int(state.get("current_chapter_index", 0) or 0) + 1
    proposal = require_proposal(state, "chapter_outline", chapter_number)
    raw_decision = request_decision(
        state,
        proposal,
        action="review_or_provide_chapter_outline",
        message=f"第{chapter_number}章细纲已生成，请审阅或修改",
        ai_generated_outline=proposal["payload"],
    )
    decision = unpack_decision(raw_decision, proposal)
    if decision == "regenerate":
        return Command(
            goto="chapter_outline_node",
            update={
                "pending_proposal": None,
                "pending_proposal_decision": None,
            },
        )
    selected = proposal["payload"] if decision == "accept" else decision
    outline = _validated_outline(
        selected, chapter_number, _total_outline(state.get("total_outline")),
    )
    return Command(
        goto="router_agent",
        update=_accept_outline_update(state, outline, clear_proposal=True),
    )
