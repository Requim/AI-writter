"""后台时限与请求、节点、依赖超时分离。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from api.routers import workflow_router
from api.workflow_commands import claim_command
from application.runtime_observability import measured_node
from application.errors import WorkflowNodeTimeoutError
from tests.test_workflow_command_idempotency import (
    FakeRedis, RedisWorkflowCommandStore, StreamingOrchestrator, prepared_stream,
    tenant_context,
)


@pytest.mark.asyncio
async def test_background_lease_uses_background_budget():
    redis = FakeRedis()
    store = RedisWorkflowCommandStore("redis://unused", client=redis)
    await claim_command(store, tenant_context(), str(uuid4()), "background", ttl_seconds=86400)
    assert redis.ttl_history == [86520]


@pytest.mark.asyncio
async def test_stream_entry_selects_background_policy(monkeypatch):
    prepare = AsyncMock(return_value=object())
    monkeypatch.setattr(workflow_router, "_prepare_execution", prepare)
    channel = workflow_router.StreamChannel(asyncio.Queue(), asyncio.Event())
    monkeypatch.setattr(workflow_router, "_start_stream_execution", lambda *args: (channel, None))
    prepare.return_value = SimpleNamespace(command=SimpleNamespace(command_id="task"))
    response = await workflow_router._stream_response(
        "novel", workflow_router.WorkflowInvokeRequest(input={}), "task",
        tenant_context(), None, None, None, None,
    )
    assert prepare.await_args.kwargs["background"] is True
    assert response.media_type == "text/event-stream"


@pytest.mark.asyncio
async def test_background_deadline_releases_task_and_reports_own_limit(monkeypatch):
    monkeypatch.setattr(workflow_router.settings, "WORKFLOW_BACKGROUND_TIMEOUT_SECONDS", 0.01)
    context, thread = tenant_context(), str(uuid4())
    store = RedisWorkflowCommandStore("redis://unused", client=FakeRedis())
    prepared = await prepared_stream(store, context, thread)
    service = StreamingOrchestrator()
    channel, task = workflow_router._start_stream_execution(service, store, context, thread, prepared)
    await asyncio.wait_for(task, 1)
    events = []
    while not channel.queue.empty():
        events.append(channel.queue.get_nowait())
    error = next(event for event in events if event is not None and event.type == "error")
    assert error.data["code"] == "workflow_timeout"
    assert error.data["timeout_seconds"] == 0.01
    assert service.finished


@pytest.mark.asyncio
async def test_dependency_timeout_is_not_mislabeled_as_node_timeout():
    async def node(state):
        raise TimeoutError("dependency")
    with pytest.raises(TimeoutError) as caught:
        await measured_node("node", node)({})
    assert not isinstance(caught.value, WorkflowNodeTimeoutError)
    assert workflow_router._public_error_data(caught.value)["code"] == "workflow_dependency_timeout"


@pytest.mark.asyncio
async def test_actual_node_deadline_still_stops_stuck_work(monkeypatch):
    monkeypatch.setattr(workflow_router.settings, "WORKFLOW_NODE_TIMEOUT_SECONDS", 0.01)
    async def node(state):
        await asyncio.Event().wait()
    with pytest.raises(WorkflowNodeTimeoutError):
        await measured_node("node", node)({})
