"""工作流命令幂等与路由前置保护测试。"""

import asyncio
import math
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from redis.exceptions import RedisError

from api.routers import workflow_router
from api.routers.workflow_router import (
    ClaimedWorkflowCommand,
    PreparedWorkflow,
    WorkflowInvokeRequest,
)
from application.events import WorkflowEvent
from application.errors import (
    InvalidReviewDecisionError,
    StaleWorkflowDecisionError,
)
from infrastructure.command_store import RedisWorkflowCommandStore
from infrastructure.database.identity_repository import QuotaExceededError
from service.entities.identity import TenantContext
from service.entities.novel import Novel
from service.ports.workflow_command_store import (
    WorkflowCommandClaim,
    WorkflowCommandClaimStatus,
    WorkflowCommandStoreUnavailable,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.ttl_history: list[int] = []
        self.closed = False

    async def set(self, key, value, ex, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.ttls[key] = ex
        self.ttl_history.append(ex)
        return True

    async def get(self, key):
        return self.values.get(key)

    async def eval(self, _script, _count, key, expected, *arguments):
        if self.values.get(key) != expected:
            return 0
        if not arguments:
            del self.values[key]
            self.ttls.pop(key, None)
            return 1
        value, ttl = arguments
        self.values[key] = value
        self.ttls[key] = ttl
        self.ttl_history.append(ttl)
        return 1

    async def ping(self):
        return True

    async def aclose(self):
        self.closed = True


class BrokenRedis(FakeRedis):
    async def set(self, key, value, ex, nx=False):
        raise RedisError("redis unavailable")


class BrokenSettlementRedis(FakeRedis):
    async def eval(self, _script, _count, key, expected, *arguments):
        raise RedisError("redis unavailable")


class StreamingOrchestrator:
    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.task: asyncio.Task | None = None
        self.finished = False

    async def stream_events(self, *_args, **_kwargs):
        yield WorkflowEvent(
            id=1, type="status", thread_id="novel", data={"status": "started"}
        )
        await self.gate.wait()
        yield WorkflowEvent(
            id=2, type="completed", thread_id="novel", data={"status": "idle"}
        )

    def register_task(self, _context, _thread_id, task):
        self.task = task

    def finish(self, _context, _thread_id, task=None):
        assert task is self.task
        self.finished = True

    def get_execution_snapshot(self, *_args):
        return {"active_node": "outline_node"}


class FailingStreamingOrchestrator(StreamingOrchestrator):
    async def stream_events(self, *_args, **_kwargs):
        yield WorkflowEvent(
            id=1, type="status", thread_id="novel", data={"status": "started"}
        )
        raise RuntimeError("provider failed")


class ProviderUnavailableError(RuntimeError):
    status_code = 503

    def __init__(self, message: str, retry_after=None) -> None:
        super().__init__(message)
        self.body = {"retry_after": retry_after} if retry_after is not None else {}


class ProviderStatusError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"provider status {status_code}")
        self.status_code = status_code
        self.body: dict = {}


class APIConnectionError(RuntimeError):
    pass


class AutoRetryStreamingOrchestrator:
    def __init__(self, failures: int = 1, retry_after=None) -> None:
        self.calls: list[dict] = []
        self.retry_attempts: list[int] = []
        self.prepare_retry_checkpoint = AsyncMock()
        self.failures = failures
        self.error = ProviderUnavailableError(
            "provider unavailable", retry_after=retry_after
        )

    async def stream_events(self, context, thread_id, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("is_retry"):
            await self.prepare_retry_checkpoint(context, thread_id)
        if len(self.calls) <= self.failures:
            raise self.error
        yield WorkflowEvent(
            id=1, type="completed", thread_id=thread_id, data={"status": "idle"}
        )

    def record_retry_attempt(self, _context, _thread_id, attempt: int) -> None:
        self.retry_attempts.append(attempt)

    def finish(self, *_args, **_kwargs) -> None:
        return None


def tenant_context() -> TenantContext:
    return TenantContext(
        tenant_id=uuid4(),
        tenant_name="测试租户",
        user_id=uuid4(),
        role="owner",
        is_platform_admin=False,
        ai_enabled=True,
        monthly_generation_limit=30,
    )


@pytest.mark.parametrize(
    "error",
    [
        ProviderStatusError(408),
        ProviderStatusError(429),
        ProviderStatusError(500),
        ProviderStatusError(524),
        APIConnectionError("connection failed"),
    ],
)
def test_transient_provider_errors_are_auto_retryable(error) -> None:
    assert workflow_router._is_retryable_provider_error(error) is True


def test_non_transient_provider_error_is_not_auto_retryable() -> None:
    assert workflow_router._is_retryable_provider_error(
        ProviderStatusError(400)
    ) is False


@pytest.mark.asyncio
async def test_redis_store_claim_finalize_and_terminal_ttl():
    redis = FakeRedis()
    store = RedisWorkflowCommandStore("redis://unused", client=redis)
    identifiers = (str(uuid4()), str(uuid4()), "command-1")

    first = await store.claim(*identifiers, ttl_seconds=720.1)
    duplicate = await store.claim(*identifiers, ttl_seconds=720.1)
    finalized = await store.finalize(
        *identifiers, first.lease_token or "", ttl_seconds=86_400
    )
    applied = await store.claim(*identifiers, ttl_seconds=720.1)

    assert first.status is WorkflowCommandClaimStatus.ACQUIRED
    assert duplicate.status is WorkflowCommandClaimStatus.IN_PROGRESS
    assert finalized is True
    assert applied.status is WorkflowCommandClaimStatus.ALREADY_APPLIED
    assert redis.ttl_history == [721, 86_400]


@pytest.mark.asyncio
async def test_redis_store_release_allows_same_command_to_replay():
    redis = FakeRedis()
    store = RedisWorkflowCommandStore("redis://unused", client=redis)
    identifiers = (str(uuid4()), str(uuid4()), "command-1")

    first = await store.claim(*identifiers, ttl_seconds=720)
    released = await store.release(*identifiers, first.lease_token or "")
    replay = await store.claim(*identifiers, ttl_seconds=720)
    stale = await store.release(*identifiers, first.lease_token or "")

    assert released is True
    assert replay.status is WorkflowCommandClaimStatus.ACQUIRED
    assert replay.lease_token != first.lease_token
    assert stale is False


@pytest.mark.asyncio
async def test_redis_store_isolates_tenants_and_rejects_stale_lease():
    redis = FakeRedis()
    store = RedisWorkflowCommandStore("redis://unused", client=redis)
    novel_id = str(uuid4())

    first = await store.claim("tenant-a", novel_id, "same", 720)
    second = await store.claim("tenant-b", novel_id, "same", 720)
    stale = await store.finalize("tenant-a", novel_id, "same", "stale", 86_400)

    assert first.status is WorkflowCommandClaimStatus.ACQUIRED
    assert second.status is WorkflowCommandClaimStatus.ACQUIRED
    assert stale is False


@pytest.mark.asyncio
async def test_redis_error_is_exposed_as_store_unavailable():
    store = RedisWorkflowCommandStore("redis://unused", client=BrokenRedis())

    with pytest.raises(WorkflowCommandStoreUnavailable):
        await store.claim("tenant", "novel", "command", 720)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code"),
    [
        (WorkflowCommandClaimStatus.IN_PROGRESS, "workflow_command_in_progress"),
        (
            WorkflowCommandClaimStatus.ALREADY_APPLIED,
            "workflow_command_already_applied",
        ),
    ],
)
async def test_duplicate_command_returns_409(status, code):
    store = SimpleNamespace(
        claim=AsyncMock(return_value=WorkflowCommandClaim(status))
    )

    with pytest.raises(HTTPException) as raised:
        await workflow_router._claim_command(
            store, tenant_context(), str(uuid4()), "same-command"
        )

    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == code


@pytest.mark.asyncio
async def test_store_failure_precedes_lock_quota_and_llm():
    context = tenant_context()
    repository = SimpleNamespace(
        find_by_id=AsyncMock(return_value=Novel(id=uuid4()))
    )
    orchestrator = SimpleNamespace(try_start=AsyncMock(), finish=AsyncMock())
    quota = SimpleNamespace(reserve=AsyncMock())
    store = SimpleNamespace(
        claim=AsyncMock(side_effect=WorkflowCommandStoreUnavailable())
    )

    with pytest.raises(HTTPException) as raised:
        await workflow_router._prepare_execution(
            str(uuid4()),
            WorkflowInvokeRequest(input={}),
            "command",
            context,
            orchestrator,
            repository,
            quota,
            store,
        )

    assert raised.value.status_code == 503
    assert raised.value.detail["code"] == "idempotency_store_unavailable"
    orchestrator.try_start.assert_not_awaited()
    quota.reserve.assert_not_awaited()


@pytest.mark.asyncio
async def test_lock_conflict_releases_command_for_replay():
    context = tenant_context()
    thread_id = str(uuid4())
    repository = SimpleNamespace(find_by_id=AsyncMock(return_value=Novel()))
    orchestrator = SimpleNamespace(
        try_start=AsyncMock(return_value=False), finish=Mock()
    )
    quota = SimpleNamespace(reserve=AsyncMock())
    store = RedisWorkflowCommandStore("redis://unused", client=FakeRedis())

    with pytest.raises(HTTPException) as raised:
        await workflow_router._prepare_execution(
            thread_id, WorkflowInvokeRequest(input={}), "command",
            context, orchestrator, repository, quota, store,
        )
    replay = await store.claim(
        str(context.tenant_id), thread_id, "command", 720
    )

    assert raised.value.status_code == 409
    assert replay.status is WorkflowCommandClaimStatus.ACQUIRED
    quota.reserve.assert_not_awaited()


@pytest.mark.asyncio
async def test_checkpoint_failure_releases_command_for_replay(monkeypatch):
    context = tenant_context()
    thread_id = str(uuid4())
    repository = SimpleNamespace(find_by_id=AsyncMock(return_value=Novel()))
    orchestrator = SimpleNamespace(
        try_start=AsyncMock(return_value=True), finish=Mock()
    )
    quota = SimpleNamespace(reserve=AsyncMock())
    store = RedisWorkflowCommandStore("redis://unused", client=FakeRedis())
    checkpoint_error = HTTPException(status_code=503, detail="pending")
    monkeypatch.setattr(
        workflow_router, "_ensure_checkpoint_ready",
        AsyncMock(side_effect=checkpoint_error),
    )

    with pytest.raises(HTTPException):
        await workflow_router._prepare_execution(
            thread_id, WorkflowInvokeRequest(input={}), "command",
            context, orchestrator, repository, quota, store,
        )
    replay = await store.claim(
        str(context.tenant_id), thread_id, "command", 720
    )

    assert replay.status is WorkflowCommandClaimStatus.ACQUIRED
    orchestrator.finish.assert_called_once()
    quota.reserve.assert_not_awaited()


@pytest.mark.asyncio
async def test_quota_failure_releases_command_for_replay(monkeypatch):
    context = tenant_context()
    thread_id = str(uuid4())
    repository = SimpleNamespace(find_by_id=AsyncMock(return_value=Novel()))
    orchestrator = SimpleNamespace(
        try_start=AsyncMock(return_value=True), finish=Mock(),
        set_auto_mode=Mock(), get_workflow_run_id=AsyncMock(return_value=None),
    )
    quota = SimpleNamespace(
        reserve=AsyncMock(side_effect=QuotaExceededError("额度不足"))
    )
    store = RedisWorkflowCommandStore("redis://unused", client=FakeRedis())
    monkeypatch.setattr(workflow_router, "_ensure_checkpoint_ready", AsyncMock())

    with pytest.raises(HTTPException) as raised:
        await workflow_router._prepare_execution(
            thread_id, WorkflowInvokeRequest(input={}), "command",
            context, orchestrator, repository, quota, store,
        )
    replay = await store.claim(
        str(context.tenant_id), thread_id, "command", 720
    )

    assert raised.value.status_code == 429
    assert replay.status is WorkflowCommandClaimStatus.ACQUIRED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (StaleWorkflowDecisionError("提案已变化"), 409, "stale_workflow_decision"),
        (InvalidReviewDecisionError("决定无效"), 422, "invalid_workflow_decision"),
    ],
)
async def test_resume_decision_is_validated_before_execution(
    error, status_code, code
):
    orchestrator = SimpleNamespace(
        validate_resume_decision=AsyncMock(side_effect=error),
        set_auto_mode=Mock(),
    )
    quota = SimpleNamespace(reserve=AsyncMock())
    request = WorkflowInvokeRequest(command={"resume": {"decision": "accept"}})

    with pytest.raises(HTTPException) as raised:
        await workflow_router._prepare_request(
            request, tenant_context(), str(uuid4()), orchestrator, quota
        )

    assert raised.value.status_code == status_code
    assert raised.value.detail["code"] == code
    quota.reserve.assert_not_awaited()
    orchestrator.set_auto_mode.assert_not_called()


def test_required_idempotency_key_can_be_enabled(monkeypatch):
    monkeypatch.setattr(workflow_router.settings, "WORKFLOW_IDEMPOTENCY_REQUIRED", True)

    with pytest.raises(HTTPException) as raised:
        workflow_router._resolve_command_id(None)

    assert raised.value.status_code == 400
    assert raised.value.detail["code"] == "idempotency_key_required"


@pytest.mark.asyncio
async def test_invoke_finalizes_command_and_blocks_same_key(monkeypatch):
    context = tenant_context()
    repository = SimpleNamespace(
        find_by_id=AsyncMock(return_value=Novel(id=uuid4()))
    )
    orchestrator = SimpleNamespace(
        try_start=AsyncMock(return_value=True),
        set_auto_mode=Mock(),
        get_workflow_run_id=AsyncMock(return_value=None),
        invoke=AsyncMock(return_value={"status": "ok"}),
        register_task=Mock(),
        finish=Mock(),
    )
    quota = SimpleNamespace(reserve=AsyncMock())
    redis = FakeRedis()
    store = RedisWorkflowCommandStore("redis://unused", client=redis)
    monkeypatch.setattr(
        workflow_router, "_ensure_checkpoint_ready", AsyncMock()
    )
    arguments = (
        str(uuid4()),
        WorkflowInvokeRequest(input={}),
        "same-command",
        context,
        orchestrator,
        repository,
        quota,
        store,
    )

    result = await workflow_router.invoke_workflow(*arguments)
    with pytest.raises(HTTPException) as duplicate:
        await workflow_router.invoke_workflow(*arguments)

    assert result == {"status": "ok"}
    assert duplicate.value.status_code == 409
    assert duplicate.value.detail["code"] == "workflow_command_already_applied"
    quota.reserve.assert_awaited_once()
    orchestrator.invoke.assert_awaited_once()
    running_ttl = math.ceil(workflow_router.settings.WORKFLOW_TIMEOUT_SECONDS + 120)
    assert redis.ttl_history == [running_ttl, 86_400]


@pytest.mark.asyncio
async def test_auto_retry_reuses_command_run_and_quota(monkeypatch):
    monkeypatch.setattr(
        workflow_router.settings, "WORKFLOW_AUTO_RETRY_ENABLED", True
    )
    monkeypatch.setattr(workflow_router, "_ensure_checkpoint_ready", AsyncMock())
    context = tenant_context()
    thread_id = str(uuid4())
    repository = SimpleNamespace(find_by_id=AsyncMock(return_value=Novel()))
    orchestrator = SimpleNamespace(
        try_start=AsyncMock(return_value=True),
        set_auto_mode=Mock(),
        set_active_command=Mock(),
        get_workflow_run_id=AsyncMock(return_value=None),
        invoke=AsyncMock(side_effect=ProviderUnavailableError("temporary")),
        retry=AsyncMock(return_value={"status": "ok"}),
        register_task=Mock(),
        finish=Mock(),
    )
    quota = SimpleNamespace(reserve=AsyncMock())
    store = RedisWorkflowCommandStore("redis://unused", client=FakeRedis())
    request = WorkflowInvokeRequest(input={
        "_auto_mode": True, "workflow_run_id": "same-run",
    })

    result = await workflow_router.invoke_workflow(
        thread_id, request, "same-command", context,
        orchestrator, repository, quota, store,
    )

    assert result == {"status": "ok"}
    assert orchestrator.invoke.await_args.args[2]["workflow_run_id"] == "same-run"
    orchestrator.retry.assert_awaited_once_with(context, thread_id)
    quota.reserve.assert_awaited_once()
    assert quota.reserve.await_args.args[1] == "same-run"
    orchestrator.set_active_command.assert_called_once_with(
        context, thread_id, "same-command"
    )


def invoke_orchestrator(outcome) -> SimpleNamespace:
    invoke = (
        AsyncMock(side_effect=outcome)
        if isinstance(outcome, Exception)
        else AsyncMock(return_value=outcome)
    )
    return SimpleNamespace(
        try_start=AsyncMock(return_value=True), set_auto_mode=Mock(),
        get_workflow_run_id=AsyncMock(return_value=None), invoke=invoke,
        register_task=Mock(), finish=Mock(),
    )


@pytest.mark.asyncio
async def test_invoke_failure_releases_command_for_replay(monkeypatch):
    context = tenant_context()
    thread_id = str(uuid4())
    repository = SimpleNamespace(find_by_id=AsyncMock(return_value=Novel()))
    orchestrator = invoke_orchestrator(RuntimeError("provider failed"))
    quota = SimpleNamespace(reserve=AsyncMock())
    store = RedisWorkflowCommandStore("redis://unused", client=FakeRedis())
    monkeypatch.setattr(workflow_router, "_ensure_checkpoint_ready", AsyncMock())

    with pytest.raises(HTTPException) as raised:
        await workflow_router.invoke_workflow(
            thread_id, WorkflowInvokeRequest(input={}), "command", context,
            orchestrator, repository, quota, store,
        )
    replay = await store.claim(
        str(context.tenant_id), thread_id, "command", 720
    )

    assert raised.value.status_code == 500
    assert replay.status is WorkflowCommandClaimStatus.ACQUIRED


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [{"status": "ok"}, RuntimeError("failed")])
async def test_settlement_failure_keeps_command_fail_closed(monkeypatch, outcome):
    context = tenant_context()
    thread_id = str(uuid4())
    repository = SimpleNamespace(find_by_id=AsyncMock(return_value=Novel()))
    orchestrator = invoke_orchestrator(outcome)
    quota = SimpleNamespace(reserve=AsyncMock())
    redis = BrokenSettlementRedis()
    store = RedisWorkflowCommandStore("redis://unused", client=redis)
    monkeypatch.setattr(workflow_router, "_ensure_checkpoint_ready", AsyncMock())

    with pytest.raises(HTTPException) as raised:
        await workflow_router.invoke_workflow(
            thread_id, WorkflowInvokeRequest(input={}), "command", context,
            orchestrator, repository, quota, store,
        )
    duplicate = await store.claim(
        str(context.tenant_id), thread_id, "command", 720
    )

    assert raised.value.status_code == 503
    assert raised.value.detail["code"] == "idempotency_store_unavailable"
    assert duplicate.status is WorkflowCommandClaimStatus.IN_PROGRESS


async def prepared_stream(
    store: RedisWorkflowCommandStore,
    context: TenantContext,
    thread_id: str,
) -> PreparedWorkflow:
    claim = await store.claim(
        str(context.tenant_id), thread_id, "stream-command", 720
    )
    command = ClaimedWorkflowCommand(
        "stream-command", claim.lease_token or ""
    )
    return PreparedWorkflow(None, None, False, False, command)


@pytest.mark.asyncio
async def test_auto_mode_retries_provider_error_once_with_same_command(monkeypatch):
    monkeypatch.setattr(
        workflow_router.settings, "WORKFLOW_AUTO_RETRY_ENABLED", True
    )
    command = ClaimedWorkflowCommand("same-command", "lease")
    prepared = PreparedWorkflow(
        {"workflow_run_id": "same-run"}, None, False, False, command, True
    )
    channel = workflow_router.StreamChannel(asyncio.Queue(), asyncio.Event())
    orchestrator = AutoRetryStreamingOrchestrator(retry_after=500)
    sleep = AsyncMock()
    monkeypatch.setattr(workflow_router.asyncio, "sleep", sleep)
    context = tenant_context()
    thread_id = str(uuid4())

    await workflow_router._produce_stream_events(
        channel, orchestrator, context, thread_id, prepared
    )

    assert len(orchestrator.calls) == 2
    assert {call["command_id"] for call in orchestrator.calls} == {"same-command"}
    assert orchestrator.calls[0]["input_data"]["workflow_run_id"] == "same-run"
    assert orchestrator.calls[1]["is_retry"] is True
    orchestrator.prepare_retry_checkpoint.assert_awaited_once_with(
        context, thread_id
    )
    events = [channel.queue.get_nowait(), channel.queue.get_nowait()]
    assert [event.id for event in events] == [1, 2]
    assert events[0].data["status"] == "retrying"
    assert events[0].data["retry_after"] == 120
    assert events[0].data["retry_attempt"] == 1
    assert orchestrator.retry_attempts == [1]
    sleep.assert_awaited_once_with(120)


@pytest.mark.asyncio
async def test_auto_mode_never_retries_provider_error_more_than_once(monkeypatch):
    monkeypatch.setattr(
        workflow_router.settings, "WORKFLOW_AUTO_RETRY_ENABLED", True
    )
    prepared = PreparedWorkflow(
        None, None, False, False,
        ClaimedWorkflowCommand("same-command", "lease"), True,
    )
    channel = workflow_router.StreamChannel(asyncio.Queue(), asyncio.Event())
    orchestrator = AutoRetryStreamingOrchestrator(failures=2)

    with pytest.raises(ProviderUnavailableError):
        await workflow_router._produce_stream_events(
            channel, orchestrator, tenant_context(), str(uuid4()), prepared
        )

    assert len(orchestrator.calls) == 2
    assert orchestrator.retry_attempts == [1]
    orchestrator.prepare_retry_checkpoint.assert_awaited_once()


@pytest.mark.asyncio
async def test_second_provider_failure_releases_command_for_manual_recovery(
    monkeypatch,
):
    monkeypatch.setattr(
        workflow_router.settings, "WORKFLOW_AUTO_RETRY_ENABLED", True
    )
    context = tenant_context()
    thread_id = str(uuid4())
    store = RedisWorkflowCommandStore("redis://unused", client=FakeRedis())
    initial = await prepared_stream(store, context, thread_id)
    prepared = PreparedWorkflow(
        initial.input_data, initial.resume_value, initial.is_resume,
        initial.is_retry, initial.command, True,
    )
    channel = workflow_router.StreamChannel(asyncio.Queue(), asyncio.Event())
    orchestrator = AutoRetryStreamingOrchestrator(failures=2)

    await workflow_router._run_stream_execution(
        channel, orchestrator, store, context, thread_id, prepared
    )
    replay = await store.claim(
        str(context.tenant_id), thread_id, "stream-command", 720
    )

    assert len(orchestrator.calls) == 2
    assert replay.status is WorkflowCommandClaimStatus.ACQUIRED
    assert orchestrator.retry_attempts == [1]


@pytest.mark.asyncio
async def test_auto_retry_disabled_does_not_retry_provider_error(monkeypatch):
    monkeypatch.setattr(
        workflow_router.settings, "WORKFLOW_AUTO_RETRY_ENABLED", False
    )
    prepared = PreparedWorkflow(
        None,
        None,
        False,
        False,
        ClaimedWorkflowCommand("same-command", "lease"),
        True,
    )
    channel = workflow_router.StreamChannel(asyncio.Queue(), asyncio.Event())
    orchestrator = AutoRetryStreamingOrchestrator()

    with pytest.raises(ProviderUnavailableError):
        await workflow_router._produce_stream_events(
            channel, orchestrator, tenant_context(), str(uuid4()), prepared
        )

    assert len(orchestrator.calls) == 1
    orchestrator.prepare_retry_checkpoint.assert_not_awaited()


@pytest.mark.asyncio
async def test_stream_disconnect_does_not_cancel_background_workflow():
    context = tenant_context()
    thread_id = str(uuid4())
    store = RedisWorkflowCommandStore("redis://unused", client=FakeRedis())
    prepared = await prepared_stream(store, context, thread_id)
    orchestrator = StreamingOrchestrator()
    channel, producer = workflow_router._start_stream_execution(
        orchestrator, store, context, thread_id, prepared
    )
    body = workflow_router._stream_generator(
        channel, orchestrator, context, thread_id, prepared.command.command_id
    )

    first_frame = await anext(body)
    await body.aclose()
    assert '"status":"started"' in first_frame
    assert producer.done() is False
    assert channel.disconnected.is_set()

    orchestrator.gate.set()
    await asyncio.wait_for(producer, timeout=1)
    duplicate = await store.claim(
        str(context.tenant_id), thread_id, "stream-command", 720
    )
    assert producer.cancelled() is False
    assert orchestrator.finished is True
    assert duplicate.status is WorkflowCommandClaimStatus.ALREADY_APPLIED
    assert channel.queue.empty()


@pytest.mark.asyncio
async def test_stream_timeout_releases_command_for_replay(monkeypatch):
    monkeypatch.setattr(workflow_router.settings, "WORKFLOW_TIMEOUT_SECONDS", 0.02)
    context = tenant_context()
    thread_id = str(uuid4())
    store = RedisWorkflowCommandStore("redis://unused", client=FakeRedis())
    prepared = await prepared_stream(store, context, thread_id)
    orchestrator = StreamingOrchestrator()
    channel, producer = workflow_router._start_stream_execution(
        orchestrator, store, context, thread_id, prepared
    )
    body = workflow_router._stream_generator(
        channel, orchestrator, context, thread_id, prepared.command.command_id
    )

    frames = [frame async for frame in body]
    await asyncio.wait_for(producer, timeout=1)
    replay = await store.claim(
        str(context.tenant_id), thread_id, "stream-command", 720
    )

    assert any("workflow_timeout" in frame for frame in frames)
    assert producer.cancelled() is False
    assert orchestrator.finished is True
    assert replay.status is WorkflowCommandClaimStatus.ACQUIRED


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_stream_settlement_failure_is_reported_and_fail_closed(fails):
    context = tenant_context()
    thread_id = str(uuid4())
    redis = BrokenSettlementRedis()
    store = RedisWorkflowCommandStore("redis://unused", client=redis)
    prepared = await prepared_stream(store, context, thread_id)
    orchestrator = FailingStreamingOrchestrator() if fails else StreamingOrchestrator()
    if not fails:
        orchestrator.gate.set()
    channel, producer = workflow_router._start_stream_execution(
        orchestrator, store, context, thread_id, prepared
    )
    body = workflow_router._stream_generator(
        channel, orchestrator, context, thread_id, prepared.command.command_id
    )

    frames = [frame async for frame in body]
    await asyncio.wait_for(producer, timeout=1)
    duplicate = await store.claim(
        str(context.tenant_id), thread_id, "stream-command", 720
    )

    assert any("idempotency_store_unavailable" in frame for frame in frames)
    assert duplicate.status is WorkflowCommandClaimStatus.IN_PROGRESS
