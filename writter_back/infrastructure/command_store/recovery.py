"""Recovery intent is valid only for the most recent fenced execution."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select

from infrastructure.database.runtime_models import WorkflowLeaseModel, WorkflowRunModel


class RecoveryIntent:
    sessions: Any
    owners: dict

    async def set_recovery(self, token: str, intent: dict) -> bool:
        owner = self.owners.get(token)
        if owner is None:
            return False
        async with self.sessions() as session, session.begin():
            lease = await self._lock(session, str(owner.tenant_id), str(owner.novel_id))
            now = await session.scalar(select(func.clock_timestamp()))
            run = await session.get(WorkflowRunModel, owner.run_id)
            if lease.token != token or lease.expires_at <= now or not run or run.cancel_requested:
                return False
            run.recovery_payload = dict(intent)
            return True

    async def release_for_restart(self, tenant: str, novel: str, command: str, token: str) -> bool:
        return await self._settle(tenant, novel, token, "orphaned")

    async def recovery_candidates(self) -> list[dict]:
        query = select(WorkflowRunModel).join(WorkflowLeaseModel, (
            (WorkflowLeaseModel.tenant_id == WorkflowRunModel.tenant_id)
            & (WorkflowLeaseModel.novel_id == WorkflowRunModel.novel_id)
            & (WorkflowLeaseModel.run_id == WorkflowRunModel.id)
        )).where(
            WorkflowRunModel.status == "orphaned",
            WorkflowRunModel.cancel_requested.is_(False),
            WorkflowRunModel.recovery_payload.is_not(None),
            WorkflowRunModel.deadline > func.clock_timestamp(),
            or_(WorkflowLeaseModel.token.is_(None), WorkflowLeaseModel.expires_at <= func.clock_timestamp()),
        ).order_by(WorkflowRunModel.created_at).limit(20)
        async with self.sessions() as session:
            rows = (await session.scalars(query)).all()
            return [{"run_id": str(row.id), "tenant_id": str(row.tenant_id),
                     "novel_id": str(row.novel_id), "recovery": row.recovery_payload}
                    for row in rows]

    async def clear_recovery(self, run_id: UUID) -> None:
        async with self.sessions() as session, session.begin():
            run = await session.get(WorkflowRunModel, run_id)
            if run:
                run.recovery_payload = None

    async def _recovery_claimable(self, session: Any, lease: Any, run_id: UUID, now: datetime) -> bool:
        if lease.run_id != run_id:
            return False
        run = await session.get(WorkflowRunModel, run_id)
        return bool(run and run.status == "orphaned" and not run.cancel_requested
                    and run.recovery_payload and run.deadline > now)
