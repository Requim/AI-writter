import asyncio
from uuid import uuid4

import pytest

from application.orchestrator import NovelOrchestrator
from service.entities.identity import TenantContext


def context():
    return TenantContext(
        tenant_id=uuid4(), tenant_name="取消测试", user_id=uuid4(), role="owner",
        is_platform_admin=False, ai_enabled=True, monthly_generation_limit=30,
    )


@pytest.mark.asyncio
async def test_cancel_timeout_retains_lock_until_task_really_exits(monkeypatch):
    service = NovelOrchestrator(None, None, {})
    tenant = context()
    started, cleanup, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def worker():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleanup.set()
            await release.wait()

    original_wait = asyncio.wait_for

    async def fast_wait(awaitable, timeout):
        return await original_wait(awaitable, timeout=0.02)

    await service.try_start(tenant, "novel")
    task = asyncio.create_task(worker())
    service.register_task(tenant, "novel", task)
    await started.wait()
    monkeypatch.setattr(asyncio, "wait_for", fast_wait)
    try:
        assert await service.cancel(tenant, "novel") is False
        assert cleanup.is_set()
        assert service.is_executing(tenant, "novel")
        assert await service.try_start(tenant, "novel") is False
        service.record_activity(tenant, "novel", message="迟到的生成事件")
        assert service.get_execution_snapshot(tenant, "novel")["status"] == "cancelling"
        assert await service.cancel(tenant, "novel") is False
        assert task.cancelling() == 1
    finally:
        release.set()
        await task
        await asyncio.sleep(0)
    assert not service.is_executing(tenant, "novel")
    snapshot = service.get_execution_snapshot(tenant, "novel")
    assert snapshot["status"] == "cancelled"
    assert snapshot["active_node"] is None
    assert "正在生成" not in snapshot["message"]
