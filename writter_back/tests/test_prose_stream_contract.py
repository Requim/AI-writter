"""正文生成、场景续写与全文修订共享明确的输出边界。"""
from types import SimpleNamespace

import pytest

from application.streaming import collect_streamed_text


@pytest.mark.asyncio
@pytest.mark.parametrize("node", ["chapter_writer_node", "revision_node"])
@pytest.mark.parametrize("system", [None, "保留角色视角"])
async def test_prose_boundary_covers_initial_and_continuation_calls(node, system):
    calls = []

    async def stream_text(**kwargs):
        calls.append(kwargs)
        yield "正文"

    llm = SimpleNamespace(stream_text=stream_text)
    text = await collect_streamed_text(
        llm, "目标要求", node=node, chapter_index=0, system_prompt=system,
    )
    assert text == "正文"
    assert "本次不是审读" in calls[0]["system_prompt"]
    if system:
        assert calls[0]["system_prompt"].startswith(system)
