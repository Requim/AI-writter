"""Deterministic routing for the per-chapter creation loop."""

import logging
from typing import Any

from langgraph.types import Command

from application.schemas.agent_state import NovelAgentState
from application.streaming import emit_workflow_event

logger = logging.getLogger("uvicorn")


def _outline_for_current_chapter(
    outlines: list[dict[str, Any]], chapter_number: int
) -> dict[str, Any] | None:
    for outline in reversed(outlines):
        if outline.get("chapter_number") == chapter_number:
            return outline
    return None


def _route(state: NovelAgentState) -> tuple[str, str]:
    """Select the next node from trusted state, without another LLM request."""
    total_outline = state.get("total_outline")
    if not isinstance(total_outline, dict) or not total_outline:
        return "outline_node", "缺少宏观总纲，返回总纲节点"

    current_index = state.get("current_chapter_index", 0)
    chapter_number = current_index + 1
    content = state.get("current_chapter_content")
    if content:
        return "reflection_node", f"第{chapter_number}章正文已生成，进入质量审读"

    if current_index > 0 and not state.get("memory_context"):
        return "memory_retrieval_node", f"生成第{chapter_number}章前先检索前文记忆"

    outlines = state.get("chapter_outlines", [])
    if not _outline_for_current_chapter(outlines, chapter_number):
        return "chapter_outline_node", f"为第{chapter_number}章即时生成细纲"

    return "chapter_writer_node", f"第{chapter_number}章细纲就绪，开始生成正文"


async def router_agent(state: NovelAgentState, _config) -> Command:
    """Route the fixed writing process and expose the reason to the SSE timeline."""
    next_tool, reasoning = _route(state)
    logger.info("【确定性路由】%s -> %s", reasoning, next_tool)
    emit_workflow_event(
        "reasoning",
        {"text": reasoning, "next_node": next_tool},
        "router_agent",
    )
    return Command(
        goto=next_tool,
        update={
            "phase": "writing",
            "graph_version": "v3",
            "next_tool": next_tool,
            "router_reasoning": reasoning,
        },
    )
