"""Unit tests for the public streaming contracts without network calls."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import openai
import pytest

from application.agents.chapter_outline_node import chapter_outline_node
from application.events import WorkflowEvent
from application.orchestrator import NovelOrchestrator
from infrastructure.llm.anthropic_adapter import AnthropicAdapter
from infrastructure.llm.base import safe_json_parse
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


class OpenAIStructuredCompletions:
    async def create(self, **kwargs):
        assert kwargs["stream"] is True
        assert kwargs["response_format"] == {"type": "json_object"}
        return AsyncChunks([
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='{"title":"第'))]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='一章"}'))]),
        ])


class OpenAIRetryStructuredCompletions:
    def __init__(self):
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return AsyncChunks([
                SimpleNamespace(choices=[SimpleNamespace(
                    delta=SimpleNamespace(content='{\"unexpected\":true}'),
                    finish_reason="stop",
                )]),
            ])
        return AsyncChunks([
            SimpleNamespace(choices=[SimpleNamespace(
                delta=SimpleNamespace(content='{\"title\":\"第一章\"}'),
                finish_reason="stop",
            )]),
        ])


class InterruptedChunks:
    def __init__(self):
        self.sent_partial = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.sent_partial:
            self.sent_partial = True
            return SimpleNamespace(choices=[SimpleNamespace(
                delta=SimpleNamespace(content='{\"title\":'),
                finish_reason=None,
            )])
        raise openai.APIError(
            "Upstream response stream was interrupted",
            request=httpx.Request("POST", "https://example.com/v1/chat/completions"),
            body=None,
        )


class OpenAIInterruptedStructuredCompletions:
    def __init__(self):
        self.calls = 0

    async def create(self, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            return InterruptedChunks()
        return AsyncChunks([
            SimpleNamespace(choices=[SimpleNamespace(
                delta=SimpleNamespace(content='{\"title\":\"第一章\"}'),
                finish_reason="stop",
            )]),
        ])


class OpenAIAlwaysInterruptedStructuredCompletions:
    def __init__(self):
        self.calls = 0

    async def create(self, **_kwargs):
        self.calls += 1
        return InterruptedChunks()


class OpenAINonRetryableStructuredCompletions:
    def __init__(self):
        self.calls = 0

    async def create(self, **_kwargs):
        self.calls += 1
        raise openai.APIError(
            "Invalid compatible gateway response",
            request=httpx.Request("POST", "https://example.com/v1/chat/completions"),
            body=None,
        )


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
async def test_openai_structured_generation_streams_json():
    adapter = OpenAIAdapter("test-key", "test-model", 1.0)
    adapter.client = SimpleNamespace(
        chat=SimpleNamespace(completions=OpenAIStructuredCompletions())
    )
    result = await adapter.structured_generate("prompt", {"title": "string"})
    assert result == {"title": "第一章"}


@pytest.mark.asyncio
async def test_openai_structured_generation_retries_missing_schema_keys():
    completions = OpenAIRetryStructuredCompletions()
    adapter = OpenAIAdapter("test-key", "test-model", 1.0)
    adapter.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = await adapter.structured_generate("prompt", {"title": "string"})

    assert result == {"title": "第一章"}
    assert completions.calls == 2


@pytest.mark.asyncio
async def test_openai_structured_generation_retries_interrupted_stream():
    completions = OpenAIInterruptedStructuredCompletions()
    adapter = OpenAIAdapter("test-key", "test-model", 1.0)
    adapter.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = await adapter.structured_generate("prompt", {"title": "string"})

    assert result == {"title": "第一章"}
    assert completions.calls == 2


@pytest.mark.asyncio
async def test_openai_structured_generation_stops_after_second_interruption():
    completions = OpenAIAlwaysInterruptedStructuredCompletions()
    adapter = OpenAIAdapter("test-key", "test-model", 1.0)
    adapter.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    with pytest.raises(openai.APIError, match="stream was interrupted"):
        await adapter.structured_generate("prompt", {"title": "string"})

    assert completions.calls == 2


@pytest.mark.asyncio
async def test_openai_structured_generation_does_not_retry_other_api_errors():
    completions = OpenAINonRetryableStructuredCompletions()
    adapter = OpenAIAdapter("test-key", "test-model", 1.0)
    adapter.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    with pytest.raises(openai.APIError, match="Invalid compatible gateway response"):
        await adapter.structured_generate("prompt", {"title": "string"})

    assert completions.calls == 1


def test_safe_json_parse_repairs_truncated_reflection_output():
    result = safe_json_parse(
        '{"passed":false,"overall_quality_score":0.74,'
        '"word_count_analysis":{"total_count":6030,"effective_density":78,'
        '"is_valid_word_count":true},"issues":[{"type":"pacing",'
        '"severity":"medium","description":"节奏略慢'
    )

    assert result["passed"] is False
    assert result["overall_quality_score"] == 0.74
    assert result["issues"][0]["type"] == "pacing"


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
