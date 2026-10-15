"""Real subprocess termination and relaunch, without paid provider requests."""

import asyncio
import os
from pathlib import Path
import signal
import sys

import pytest
from sqlalchemy import text

from infrastructure.database.runtime_journal import RuntimeJournal
from tests.test_workflow_runtime import seed


async def wait_until(check, timeout=15):
    async with asyncio.timeout(timeout):
        while not await check():
            await asyncio.sleep(0.05)


async def path_exists(path):
    return path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_signal", [signal.SIGTERM, signal.SIGKILL],
                         ids=["graceful-shutdown", "hard-process-crash"])
async def test_real_process_restart_resumes_disconnected_checkpoint_once(
    repository, tenant_context, sample_novel, tmp_path, stop_signal,
):
    store, tenant, novel = await seed(repository, tenant_context, sample_novel)
    gate = tmp_path / "completion-gate"
    script = Path(__file__).with_name("restart_process_probe.py")
    environment = {**os.environ, "DATABASE_URL": os.environ["TEST_DATABASE_URL"],
                   "PYTHONPATH": str(script.parent.parent)}
    arguments = [sys.executable, str(script), tenant, str(tenant_context.user_id), novel, str(gate)]
    children = []
    try:
        first = await asyncio.create_subprocess_exec(*arguments, "start", env=environment)
        children.append(first)
        await wait_until(lambda: path_exists(gate.with_suffix(".entered")))
        first.send_signal(stop_signal)
        expected_exit = 0 if stop_signal == signal.SIGTERM else -signal.SIGKILL
        assert await asyncio.wait_for(first.wait(), 15) == expected_exit
        if stop_signal == signal.SIGKILL:
            assert await store.recovery_candidates() == []

            async def expired():
                await store.recover_expired()
                return bool(await store.recovery_candidates())

            await wait_until(expired, timeout=75)
        assert len(await store.recovery_candidates()) == 1
        second = await asyncio.create_subprocess_exec(*arguments, "restore", env=environment)
        children.append(second)
        await wait_until(lambda: path_exists(gate.with_suffix(".restored")))
        gate.touch()
        journal = RuntimeJournal(repository.async_session)

        async def applied():
            return (await journal.status(tenant, novel))["status"] == "applied"

        await wait_until(applied)
        assert await store.recovery_candidates() == []
        async with repository.async_session() as session:
            count = await session.scalar(text(
                "SELECT count(*) FROM workflow_runs WHERE novel_id=:novel"), {"novel": sample_novel.id})
            assert count == 2
        second.send_signal(signal.SIGTERM)
        assert await asyncio.wait_for(second.wait(), 15) == 0
    finally:
        for child in children:
            if child.returncode is None:
                child.kill()
                await child.wait()
        await store.aclose()
