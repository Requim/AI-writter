"""事件先持久化后推送，客户端离线不会丢失已产生的事件。"""
import hashlib
import json
from typing import Any
from uuid import UUID
from sqlalchemy import select, func
from application.execution_fence import ExecutionFence, ExecutionLeaseLost
from application.events import WorkflowEvent
from infrastructure.database.models import NovelModel
from infrastructure.database.runtime_models import WorkflowLeaseModel, WorkflowEventModel, WorkflowArtifactModel, WorkflowRunModel


class RuntimeJournal:
    def __init__(self, sessions: Any) -> None:
        self.sessions = sessions

    async def append(self, owner: ExecutionFence, event: WorkflowEvent) -> WorkflowEvent:
        async with self.sessions() as session, session.begin():
            await session.scalar(select(NovelModel.id).where(NovelModel.tenant_id == owner.tenant_id, NovelModel.id == owner.novel_id).with_for_update())
            lease = await session.get(WorkflowLeaseModel, (owner.tenant_id, owner.novel_id))
            now = await session.scalar(select(func.clock_timestamp()))
            if not lease or lease.fence != owner.fence or lease.token != owner.token or lease.expires_at <= now:
                raise ExecutionLeaseLost('事件执行租约已失效')
            lease.sequence += 1
            event = event.model_copy(update={'id': lease.sequence})
            payload = event.model_dump(mode='json')
            session.add(WorkflowEventModel(tenant_id=owner.tenant_id, novel_id=owner.novel_id,
                sequence=lease.sequence, run_id=owner.run_id, payload=payload))
            if event.type in ('interrupt', 'completed'):
                encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
                session.add(WorkflowArtifactModel(tenant_id=owner.tenant_id, novel_id=owner.novel_id, run_id=owner.run_id,
                    kind=event.type, digest=hashlib.sha256(encoded.encode()).hexdigest(), payload=payload))
            return event

    async def read(self, tenant: str, novel: str, cursor: int, limit: int = 200) -> list[WorkflowEvent]:
        async with self.sessions() as session:
            rows = await session.scalars(select(WorkflowEventModel).where(WorkflowEventModel.tenant_id == UUID(tenant),
                WorkflowEventModel.novel_id == UUID(novel), WorkflowEventModel.sequence > cursor)
                .order_by(WorkflowEventModel.sequence).limit(limit))
            return [WorkflowEvent.model_validate(row.payload) for row in rows]

    async def status(self, tenant: str, novel: str) -> dict[str, Any]:
        async with self.sessions() as session:
            lease = await session.get(WorkflowLeaseModel, (UUID(tenant), UUID(novel)))
            now = await session.scalar(select(func.clock_timestamp()))
            active = bool(lease and lease.token and lease.expires_at > now)
            run = await session.get(WorkflowRunModel, lease.run_id) if lease and lease.run_id else None
            return {'running': active, 'sequence': lease.sequence if lease else 0,
                'run_id': str(run.id) if run else None, 'status': run.status if run else 'not_started',
                'attempt': run.attempt if run else 0, 'cancel_requested': bool(run and run.cancel_requested)}
