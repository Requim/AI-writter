"""按小说授权的运行指标，不返回正文、令牌或Prompt。"""
from uuid import UUID
from typing import Any
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, func
from api.dependencies import get_tenant_context
from api.routers.workflow_replay_router import authorized_journal
from application.runtime_metrics import summarize_events
from config import settings
from infrastructure.database.runtime_models import WorkflowEventModel, WorkflowRunModel
from service.entities.identity import TenantContext

router = APIRouter()


@router.get('/{novel_id}/metrics')
async def metrics(novel_id: str, request: Request, context: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    """返回最近5000条事件统计并显式标记截断，运行终态计数覆盖全部记录。"""
    await authorized_journal(request, context, novel_id)
    sessions = request.app.state.repository.async_session
    async with sessions() as session:
        scope = (WorkflowEventModel.tenant_id == context.tenant_id, WorkflowEventModel.novel_id == UUID(novel_id))
        total = await session.scalar(select(func.count()).select_from(WorkflowEventModel).where(*scope)) or 0
        events = list(await session.scalars(select(WorkflowEventModel.payload).where(*scope).order_by(WorkflowEventModel.sequence.desc()).limit(5000)))
        runs = await session.execute(select(WorkflowRunModel.status, func.count()).where(WorkflowRunModel.tenant_id == context.tenant_id,
            WorkflowRunModel.novel_id == UUID(novel_id)).group_by(WorkflowRunModel.status))
    return {**summarize_events(events), 'total_events': total, 'sample_limit': 5000, 'truncated': total > 5000,
        'runs_by_status': dict(runs.all()), 'generation_paused': settings.WORKFLOW_GENERATION_PAUSED,
        'fact_review_mode': settings.FACT_REVIEW_MODE}
