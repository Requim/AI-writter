"""逐请求计量覆盖结构化重试、流中断和旧模式隔离。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from infrastructure.llm.deepseek_adapter import DeepSeekAdapter
from infrastructure.llm.metering import completion
from service.ports.model_meter import active_model_meter


@pytest.mark.asyncio
async def test_physical_retries_each_count_and_sdk_retries_are_disabled():
    adapter = DeepSeekAdapter(api_key="test-only")
    client = Mock()
    client.with_options.return_value = client
    client.chat.completions.create = AsyncMock(side_effect=[
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=body))])
        for body in ("{}", '{"name":"valid"}')
    ])
    adapter.client = client
    meter = SimpleNamespace(reserve=AsyncMock(side_effect=["1", "2"]), finish=AsyncMock())
    token = active_model_meter.set(meter)
    try:
        assert await adapter.structured_generate("prompt", {"name": "string"}) == {"name": "valid"}
    finally:
        active_model_meter.reset(token)
    assert meter.reserve.await_count == 2
    assert meter.finish.await_count == 2
    assert client.with_options.call_args.kwargs == {"max_retries": 0}


@pytest.mark.asyncio
async def test_unknown_provider_outcome_remains_consumed():
    client = Mock()
    client.with_options.return_value = client
    client.chat.completions.create = AsyncMock(side_effect=TimeoutError())
    meter = SimpleNamespace(reserve=AsyncMock(return_value="1"), finish=AsyncMock())
    token = active_model_meter.set(meter)
    try:
        with pytest.raises(TimeoutError):
            await completion(client, model="test")
    finally:
        active_model_meter.reset(token)
    meter.reserve.assert_awaited_once()
    meter.finish.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_client_is_unchanged():
    client = Mock()
    client.chat.completions.create = AsyncMock(return_value="legacy")
    assert await completion(client, model="test") == "legacy"
    client.with_options.assert_not_called()
