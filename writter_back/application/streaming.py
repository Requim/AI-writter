"""Helpers for emitting LangGraph custom stream events from nodes."""
from typing import Any

from langgraph.config import get_stream_writer
from service.ports.llm_service import LLMService
from application.prose_output import strip_trailing_goal_report


def emit_workflow_event(event_type: str, data: dict[str, Any], node: str) -> None:
    try:
        writer = get_stream_writer()
    except RuntimeError:
        return
    writer({"type": event_type, "node": node, "data": data})


async def collect_streamed_text(
    llm: LLMService,
    prompt: str,
    *,
    node: str,
    chapter_index: int,
    system_prompt: str | None = None,
    temperature: float = 0.7,
    prefix: str = "",
) -> str:
    if node in {"chapter_writer_node", "revision_node"}:
        system_prompt = (system_prompt or "") + (
            "\n【正文输出边界】本次只输出小说正文。目标契约约束情节，不是输出格式。"
            "不要输出 goal_checks、JSON 验收报告、自我评分或修改说明。"
            "提示中的“审读时返回”仅适用于后续独立审读，本次不是审读。"
        )
    parts: list[str] = []
    if prefix:
        parts.append(prefix)
        emit_workflow_event(
            "content_delta",
            {"chapter_index": chapter_index, "operation": "append", "text": prefix},
            node,
        )
    async for fragment in llm.stream_text(
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=temperature,
    ):
        parts.append(fragment)
        emit_workflow_event(
            "content_delta",
            {"chapter_index": chapter_index, "operation": "append", "text": fragment},
            node,
        )
    content = "".join(parts)
    return strip_trailing_goal_report(content) if node in {"chapter_writer_node", "revision_node"} else content
