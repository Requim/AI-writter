"""独立章节重写命令幂等测试。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.routers import novel_router
from api.workflow_commands import ClaimedWorkflowCommand
from config import settings
from service.entities.identity import TenantContext
from service.ports.workflow_command_store import (
    WorkflowCommandClaim,
    WorkflowCommandClaimStatus,
    WorkflowCommandStoreUnavailable,
)


class MemoryCommandStore:
    def __init__(self) -> None:
        self.status: WorkflowCommandClaimStatus | None = None
        self.claim_error: Exception | None = None
        self.claim_calls: list[tuple[str, str, str, float]] = []
        self.finalize_calls: list[tuple[str, str, str, str, float]] = []
        self.release_calls: list[tuple[str, str, str, str]] = []
        self.lease_token = "rewrite-lease"

    async def claim(self, tenant_id, novel_id, command_id, ttl_seconds):
        self.claim_calls.append((tenant_id, novel_id, command_id, ttl_seconds))
        if self.claim_error:
            raise self.claim_error
        if self.status is not None:
            return WorkflowCommandClaim(self.status)
        self.status = WorkflowCommandClaimStatus.IN_PROGRESS
        return WorkflowCommandClaim(
            WorkflowCommandClaimStatus.ACQUIRED, self.lease_token
        )

    async def finalize(
        self, tenant_id, novel_id, command_id, lease_token, ttl_seconds
    ):
        self.finalize_calls.append(
            (tenant_id, novel_id, command_id, lease_token, ttl_seconds)
        )
        self.status = WorkflowCommandClaimStatus.ALREADY_APPLIED
        return True

    async def release(self, tenant_id, novel_id, command_id, lease_token):
        self.release_calls.append((tenant_id, novel_id, command_id, lease_token))
        self.status = None
        return True


class RewriteOrchestrator:
    @asynccontextmanager
    async def exclusive_operation(self, *_args):
        yield


def _context() -> TenantContext:
    return TenantContext(
        tenant_id=uuid4(),
        tenant_name="测试租户",
        user_id=uuid4(),
        role="owner",
        is_platform_admin=False,
        ai_enabled=True,
        monthly_generation_limit=30,
    )


def _request(quota=None, memory=None):
    state = SimpleNamespace(
        quota_service=quota or SimpleNamespace(reserve=AsyncMock()),
        orchestrator=RewriteOrchestrator(),
        memory_service=memory or SimpleNamespace(
            get_hierarchical_context=AsyncMock(return_value={})
        ),
    )
    return SimpleNamespace(app=SimpleNamespace(state=state))


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
async def test_rewrite_duplicate_stops_before_execution(monkeypatch, status, code):
    store = MemoryCommandStore()
    store.status = status
    execute = AsyncMock()
    monkeypatch.setattr(novel_router, "_execute_rewrite_command", execute)

    with pytest.raises(HTTPException) as raised:
        await novel_router.rewrite_chapter(
            str(uuid4()), str(uuid4()), _request(), "same", _context(), Mock(), store
        )

    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == code
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_rewrite_store_failure_precedes_quota_and_model(monkeypatch):
    quota = SimpleNamespace(reserve=AsyncMock())
    store = MemoryCommandStore()
    store.claim_error = WorkflowCommandStoreUnavailable()
    model = AsyncMock()
    monkeypatch.setattr(novel_router, "_generate_rewritten_chapter", model)

    with pytest.raises(HTTPException) as raised:
        await novel_router.rewrite_chapter(
            str(uuid4()), str(uuid4()), _request(quota), "same", _context(), Mock(), store
        )

    assert raised.value.status_code == 503
    assert raised.value.detail["code"] == "idempotency_store_unavailable"
    quota.reserve.assert_not_awaited()
    model.assert_not_awaited()


@pytest.mark.asyncio
async def test_rewrite_requires_key_when_compatibility_is_disabled(monkeypatch):
    store = MemoryCommandStore()
    execute = AsyncMock()
    monkeypatch.setattr(settings, "WORKFLOW_IDEMPOTENCY_REQUIRED", True)
    monkeypatch.setattr(novel_router, "_execute_rewrite_command", execute)

    with pytest.raises(HTTPException) as raised:
        await novel_router.rewrite_chapter(
            str(uuid4()), str(uuid4()), _request(), None, _context(), Mock(), store
        )

    assert raised.value.status_code == 400
    assert raised.value.detail["code"] == "idempotency_key_required"
    assert store.claim_calls == []
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_rewrite_success_finalizes_and_blocks_same_key(monkeypatch):
    context = _context()
    novel_id = str(uuid4())
    store = MemoryCommandStore()
    response = object()
    prepare = AsyncMock(return_value=({}, {}))
    generate = AsyncMock(return_value={})
    finish = AsyncMock(return_value=response)
    monkeypatch.setattr(novel_router, "_prepare_rewrite", prepare)
    monkeypatch.setattr(novel_router, "_generate_rewritten_chapter", generate)
    monkeypatch.setattr(novel_router, "_finish_rewrite", finish)
    arguments = (novel_id, str(uuid4()), _request(), "same", context, Mock(), store)

    assert await novel_router.rewrite_chapter(*arguments) is response
    with pytest.raises(HTTPException) as duplicate:
        await novel_router.rewrite_chapter(*arguments)

    assert duplicate.value.detail["code"] == "workflow_command_already_applied"
    assert store.claim_calls[0] == (
        str(context.tenant_id), novel_id, "same",
        settings.WORKFLOW_TIMEOUT_SECONDS + 120,
    )
    assert store.finalize_calls[0][-1] == 86_400
    generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_rewrite_retry_reuses_quota_run_id(monkeypatch):
    context = _context()
    novel_id = str(uuid4())
    quota = SimpleNamespace(reserve=AsyncMock())
    request = _request(quota)
    chapter = SimpleNamespace(chapter_index=2)
    command = ClaimedWorkflowCommand("same-command", "lease")
    monkeypatch.setattr(
        novel_router, "_load_rewrite_target",
        AsyncMock(return_value=(chapter, SimpleNamespace())),
    )
    monkeypatch.setattr(novel_router, "_rewrite_state", Mock(return_value={}))
    monkeypatch.setattr(novel_router, "_rewrite_config", Mock(return_value={}))

    await novel_router._prepare_rewrite(
        request, context, Mock(), novel_id, "chapter", command
    )
    await novel_router._prepare_rewrite(
        request, context, Mock(), novel_id, "chapter", command
    )

    first_run_id = quota.reserve.await_args_list[0].args[2]
    second_run_id = quota.reserve.await_args_list[1].args[2]
    assert first_run_id == second_run_id


@pytest.mark.asyncio
async def test_rewrite_releases_only_before_persistence(monkeypatch):
    context = _context()
    novel_id = str(uuid4())
    store = MemoryCommandStore()
    claim = await store.claim(str(context.tenant_id), novel_id, "same", 720)
    command = ClaimedWorkflowCommand("same", claim.lease_token or "")
    monkeypatch.setattr(novel_router, "_prepare_rewrite", AsyncMock(return_value=({}, {})))
    monkeypatch.setattr(
        novel_router, "_generate_rewritten_chapter",
        AsyncMock(side_effect=RuntimeError("provider failed")),
    )

    with pytest.raises(RuntimeError, match="provider failed"):
        await novel_router._execute_rewrite_command(
            _request(), context, Mock(), novel_id, "chapter", command, store
        )

    assert store.status is None
    assert len(store.release_calls) == 1


@pytest.mark.asyncio
async def test_rewrite_persistence_uncertainty_fails_closed(monkeypatch):
    context = _context()
    novel_id = str(uuid4())
    store = MemoryCommandStore()
    claim = await store.claim(str(context.tenant_id), novel_id, "same", 720)
    command = ClaimedWorkflowCommand("same", claim.lease_token or "")

    async def uncertain_persistence(state, _config):
        state[novel_router._REWRITE_PERSISTENCE_STARTED] = True
        raise RuntimeError("commit result unknown")

    monkeypatch.setattr(novel_router, "_prepare_rewrite", AsyncMock(return_value=({}, {})))
    monkeypatch.setattr(novel_router, "_generate_rewritten_chapter", uncertain_persistence)

    with pytest.raises(RuntimeError, match="commit result unknown"):
        await novel_router._execute_rewrite_command(
            _request(), context, Mock(), novel_id, "chapter", command, store
        )

    assert store.status is WorkflowCommandClaimStatus.IN_PROGRESS
    assert store.release_calls == []
