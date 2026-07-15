"""Helpers for emitting LangGraph custom stream events from nodes."""
from typing import Any

from langgraph.config import get_stream_writer
from service.ports.llm_service import LLMService


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
    return "".join(parts)
