"""Tests for durable checkpoint reconciliation requests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from application.checkpoint_reconciliation import reconcile_pending_checkpoint
from service.entities.identity import TenantContext
from service.value_objects.progress import Progress


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


@pytest.mark.asyncio
async def test_reconciliation_clears_matching_request_after_checkpoint_update():
    request = {
        "next_index": 2,
        "discard_from_index": 1,
        "is_completed": False,
    }
    repository = SimpleNamespace(
        find_by_id=AsyncMock(
            return_value=SimpleNamespace(progress=Progress(checkpoint_sync=request))
        ),
        clear_checkpoint_sync=AsyncMock(return_value=True),
    )
    orchestrator = SimpleNamespace(rewind_checkpoint=AsyncMock(return_value=True))
    context = _context()

    status = await reconcile_pending_checkpoint(
        repository, orchestrator, context, str(uuid4())
    )

    assert status == "synced"
    assert orchestrator.rewind_checkpoint.await_args.args[2] == 2
    assert orchestrator.rewind_checkpoint.await_args.kwargs == {
        "discard_from_index": 1,
        "is_completed": False,
    }
    repository.clear_checkpoint_sync.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconciliation_keeps_request_when_checkpoint_is_unavailable():
    request = {
        "next_index": 3,
        "discard_from_index": 3,
        "is_completed": False,
    }
    repository = SimpleNamespace(
        find_by_id=AsyncMock(
            return_value=SimpleNamespace(progress=Progress(checkpoint_sync=request))
        ),
        clear_checkpoint_sync=AsyncMock(),
    )
    orchestrator = SimpleNamespace(
        rewind_checkpoint=AsyncMock(side_effect=RuntimeError("checkpoint unavailable"))
    )

    status = await reconcile_pending_checkpoint(
        repository, orchestrator, _context(), str(uuid4())
    )

    assert status == "deferred"
    repository.clear_checkpoint_sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconciliation_is_noop_without_pending_request():
    repository = SimpleNamespace(
        find_by_id=AsyncMock(return_value=SimpleNamespace(progress=Progress())),
        clear_checkpoint_sync=AsyncMock(),
    )
    orchestrator = SimpleNamespace(rewind_checkpoint=AsyncMock())

    status = await reconcile_pending_checkpoint(
        repository, orchestrator, _context(), str(uuid4())
    )

    assert status == "not_found"
    orchestrator.rewind_checkpoint.assert_not_awaited()
