"""Unit tests for the public streaming contracts without network calls."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from application.agents.chapter_outline_node import chapter_outline_node
from application.events import WorkflowEvent
from application.orchestrator import NovelOrchestrator
from infrastructure.llm.anthropic_adapter import AnthropicAdapter
from infrastructure.llm.deepseek_adapter import DeepSeekAdapter
from infrastructure.llm.openai_adapter import OpenAIAdapter
from service.entities.identity import TenantContext
from uuid import uuid4


class AsyncChunks:
    def __init__(self, values):
        self.values = values

    def __aiter__(self):
        self.iterator = iter(self.values)
        return self

    async def __anext__(self):
        try:
            return next(self.iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class OpenAICompletions:
    async def create(self, **kwargs):
        assert kwargs["stream"] is True
        return AsyncChunks([
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="第一"))]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="章"))]),
        ])


class AnthropicStream:
    text_stream = AsyncChunks(["第一", "章"])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_class", [DeepSeekAdapter, OpenAIAdapter])
async def test_openai_compatible_stream_contract(adapter_class):
    adapter = adapter_class("test-key", "test-model", 1.0)
    adapter.client = SimpleNamespace(chat=SimpleNamespace(completions=OpenAICompletions()))
    result = [part async for part in adapter.stream_text("prompt")]
    assert "".join(result) == "第一章"


def test_openai_adapter_accepts_compatible_base_url():
    adapter = OpenAIAdapter(
        "test-key",
        "test-model",
        1.0,
        base_url="https://example.com/v1",
    )
    assert str(adapter.client.base_url) == "https://example.com/v1/"


@pytest.mark.asyncio
async def test_anthropic_stream_contract():
    adapter = AnthropicAdapter("test-key", "test-model", 1.0)
    adapter.client = SimpleNamespace(messages=SimpleNamespace(stream=lambda **_kwargs: AnthropicStream()))
    result = [part async for part in adapter.stream_text("prompt")]
    assert "".join(result) == "第一章"


def test_workflow_event_sse_does_not_embed_large_state():
    event = WorkflowEvent(
        id=7,
        type="progress",
        thread_id="thread-1",
        data={"percentage": 50},
    )
    frame = event.to_sse()
    payload = json.loads(next(line[6:] for line in frame.splitlines() if line.startswith("data: ")))
    assert payload["data"] == {"percentage": 50}
    assert "current_chapter_content" not in frame


@pytest.mark.asyncio
async def test_empty_chapter_outline_fails_explicitly():
    llm = SimpleNamespace(structured_generate=lambda **_kwargs: asyncio.sleep(0, result={}))
    state = {
        "novel_type": "suspense",
        "title": "测试",
        "total_outline": {"chapters": []},
        "current_chapter_index": 0,
        "memory_context": "",
    }
    config = {"configurable": {"llm_config": {"llm_instance": llm}, "auto_mode": True}}
    with pytest.raises(RuntimeError, match="细纲生成失败"):
        await chapter_outline_node(state, config)


@pytest.mark.asyncio
async def test_thread_lock_and_cancel():
    orchestrator = NovelOrchestrator(None, None, {})
    context = TenantContext(
        tenant_id=uuid4(),
        tenant_name="测试租户",
        user_id=uuid4(),
        role="owner",
        is_platform_admin=False,
        ai_enabled=True,
        monthly_generation_limit=30,
    )
    other_context = TenantContext(
        tenant_id=uuid4(),
        tenant_name="其他租户",
        user_id=uuid4(),
        role="owner",
        is_platform_admin=False,
        ai_enabled=True,
        monthly_generation_limit=30,
    )
    assert await orchestrator.try_start(context, "thread-1") is True
    assert await orchestrator.try_start(context, "thread-1") is False
    assert await orchestrator.try_start(other_context, "thread-1") is True
    task = asyncio.create_task(asyncio.sleep(30))
    orchestrator.register_task(context, "thread-1", task)
    assert await orchestrator.cancel(context, "thread-1") is True
    with pytest.raises(asyncio.CancelledError):
        await task
    orchestrator.finish(context, "thread-1")
    orchestrator.finish(other_context, "thread-1")
    assert orchestrator.is_executing(context, "thread-1") is False
