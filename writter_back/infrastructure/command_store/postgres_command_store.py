"""跨进程小说租约与持久Attempt记录；数据库失败时拒绝执行。"""
import asyncio
import hashlib
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4
from sqlalchemy import select, func
from sqlalchemy.exc import SQLAlchemyError
from application.execution_fence import ExecutionFence, execution_fence
from infrastructure.database.models import NovelModel
from infrastructure.database.runtime_models import WorkflowLeaseModel, WorkflowRunModel
from service.ports.workflow_command_store import WorkflowCommandStore, WorkflowCommandClaim, WorkflowCommandClaimStatus as Status, WorkflowCommandStoreUnavailable


class PostgresWorkflowCommandStore(WorkflowCommandStore):
    def __init__(self, session_factory: Any) -> None:
        self.sessions = session_factory
        self.owners: dict[str, ExecutionFence] = {}
        self.tasks: dict[str, asyncio.Task[Any]] = {}
        self.renewers: dict[str, asyncio.Task[Any]] = {}

    async def _lock(self, session: Any, tenant: str, novel: str) -> WorkflowLeaseModel:
        found = await session.scalar(select(NovelModel.id).where(NovelModel.tenant_id == UUID(tenant), NovelModel.id == UUID(novel)).with_for_update())
        if found is None:
            raise WorkflowCommandStoreUnavailable('小说不存在')
        lease = await session.get(WorkflowLeaseModel, (UUID(tenant), UUID(novel)))
        if lease is None:
            lease = WorkflowLeaseModel(tenant_id=UUID(tenant), novel_id=UUID(novel), fence=0, sequence=0)
            session.add(lease)
        return lease

    async def claim(self, tenant_id: str, novel_id: str, command_id: str, ttl_seconds: float) -> WorkflowCommandClaim:
        try:
            async with self.sessions() as session, session.begin():
                lease = await self._lock(session, tenant_id, novel_id)
                now = await session.scalar(select(func.clock_timestamp()))
                digest = hashlib.sha256(command_id.encode()).hexdigest()
                runs = (await session.scalars(select(WorkflowRunModel).where(WorkflowRunModel.tenant_id == UUID(tenant_id),
                    WorkflowRunModel.novel_id == UUID(novel_id), WorkflowRunModel.command_hash == digest))).all()
                if any(run.status == 'applied' for run in runs):
                    return WorkflowCommandClaim(Status.ALREADY_APPLIED)
                if lease.token and lease.expires_at > now:
                    return WorkflowCommandClaim(Status.IN_PROGRESS)
                await self._orphan(session, lease, now)
                token, run_id = uuid4().hex, uuid4()
                lease.fence += 1
                lease.run_id, lease.token, lease.expires_at = run_id, token, now + timedelta(seconds=60)
                session.add(WorkflowRunModel(id=run_id, tenant_id=UUID(tenant_id), novel_id=UUID(novel_id), command_hash=digest,
                    attempt=max((run.attempt for run in runs), default=0) + 1, fence=lease.fence, token=token,
                    deadline=now + timedelta(seconds=ttl_seconds), status='running'))
                owner = ExecutionFence(UUID(tenant_id), UUID(novel_id), run_id, token, lease.fence)
            self.owners[token] = owner
            return WorkflowCommandClaim(Status.ACQUIRED, token)
        except SQLAlchemyError as exc:
            raise WorkflowCommandStoreUnavailable from exc

    async def _orphan(self, session: Any, lease: WorkflowLeaseModel, now: Any) -> None:
        if lease.run_id:
            run = await session.get(WorkflowRunModel, lease.run_id)
            if run and run.status == 'running':
                run.status, run.finished_at = 'orphaned', now

    def bind(self, token: str, task: asyncio.Task[Any] | None = None) -> None:
        owner = self.owners.get(token)
        if owner is None:
            raise WorkflowCommandStoreUnavailable('执行所有权不存在')
        execution_fence.set(owner)
        selected = task or asyncio.current_task()
        if selected:
            self.tasks[token] = selected
        if token not in self.renewers:
            self.renewers[token] = asyncio.create_task(self._maintain(owner))

    async def _maintain(self, owner: ExecutionFence) -> None:
        try:
            while True:
                await asyncio.sleep(20)
                if not await self.renew(owner):
                    self._cancel_task(owner.token)
                    return
        except asyncio.CancelledError:
            return
        except Exception:
            self._cancel_task(owner.token)

    def _cancel_task(self, token: str) -> None:
        task = self.tasks.get(token)
        if task and not task.done():
            task.cancel()

    async def renew(self, owner: ExecutionFence) -> bool:
        async with self.sessions() as session, session.begin():
            lease = await self._lock(session, str(owner.tenant_id), str(owner.novel_id))
            now = await session.scalar(select(func.clock_timestamp()))
            run = await session.get(WorkflowRunModel, owner.run_id)
            if lease.token != owner.token or lease.expires_at <= now or not run or run.cancel_requested or run.deadline <= now:
                return False
            lease.expires_at = min(run.deadline, now + timedelta(seconds=60))
            return True

    async def _settle(self, tenant: str, novel: str, token: str, status: str) -> bool:
        try:
            async with self.sessions() as session, session.begin():
                lease = await self._lock(session, tenant, novel)
                now = await session.scalar(select(func.clock_timestamp()))
                if lease.token != token or lease.expires_at <= now:
                    return False
                run = await session.get(WorkflowRunModel, lease.run_id)
                run.status, run.finished_at = status, now
                lease.token, lease.expires_at = None, None
                return True
        except SQLAlchemyError as exc:
            raise WorkflowCommandStoreUnavailable from exc
        finally:
            renewer = self.renewers.pop(token, None)
            if renewer:
                renewer.cancel()
            self.tasks.pop(token, None)
            self.owners.pop(token, None)

    async def finalize(self, tenant_id: str, novel_id: str, command_id: str, lease_token: str, ttl_seconds: float) -> bool:
        return await self._settle(tenant_id, novel_id, lease_token, 'applied')

    async def release(self, tenant_id: str, novel_id: str, command_id: str, lease_token: str) -> bool:
        return await self._settle(tenant_id, novel_id, lease_token, 'released')

    async def cancel(self, tenant: str, novel: str) -> bool:
        async with self.sessions() as session, session.begin():
            lease = await self._lock(session, tenant, novel)
            now = await session.scalar(select(func.clock_timestamp()))
            if not lease.token or lease.expires_at <= now:
                return False
            run = await session.get(WorkflowRunModel, lease.run_id)
            run.cancel_requested = True
            return True

    async def recover_expired(self) -> int:
        async with self.sessions() as session:
            expired = (await session.execute(select(WorkflowLeaseModel.tenant_id, WorkflowLeaseModel.novel_id)
                .where(WorkflowLeaseModel.token.is_not(None), WorkflowLeaseModel.expires_at <= func.clock_timestamp()))).all()
        recovered = 0
        for tenant, novel in expired:
            async with self.sessions() as session, session.begin():
                lease = await self._lock(session, str(tenant), str(novel))
                now = await session.scalar(select(func.clock_timestamp()))
                if lease.token and lease.expires_at <= now:
                    await self._orphan(session, lease, now)
                    lease.token, lease.expires_at = None, None
                    recovered += 1
        return recovered

    async def ping(self) -> None:
        async with self.sessions() as session:
            await session.execute(select(1))

    async def aclose(self) -> None:
        tasks = list(self.renewers.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.renewers.clear()
