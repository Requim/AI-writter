"""恢复接口只重放事件，不创建命令，也不消耗模型额度。"""
import asyncio
from typing import Any
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from api.dependencies import get_tenant_context
from infrastructure.database.runtime_journal import RuntimeJournal
from service.entities.identity import TenantContext
from application.events import WorkflowEvent
from infrastructure.command_store.postgres_command_store import PostgresWorkflowCommandStore
from service.ports.workflow_command_store import WorkflowCommandClaimStatus
from application.execution_fence import execution_fence
from uuid import uuid4

router = APIRouter()


async def authorized_journal(request: Request, context: TenantContext, novel_id: str) -> RuntimeJournal:
    repository = request.app.state.repository
    if await repository.find_by_id(str(context.tenant_id), novel_id) is None:
        raise HTTPException(status_code=404, detail='小说不存在')
    return RuntimeJournal(repository.async_session)


async def replay_frames(journal: RuntimeJournal, tenant: str, novel: str, cursor: int) -> Any:
    while True:
        events = await journal.read(tenant, novel, cursor)
        for event in events:
            if event.id != cursor + 1:
                yield WorkflowEvent(id=0, type="error", thread_id=novel, data={"code": "event_gap", "message": "事件记录存在缺口，请同步创作现场"}).to_sse()
                return
            cursor = event.id
            yield event.to_sse()
        status = await journal.status(tenant, novel)
        if not status['running'] and cursor >= status['sequence']:
            return
        if not events:
            yield ': keepalive\n\n'
            await asyncio.sleep(1)


@router.get('/{novel_id}/events')
async def replay(novel_id: str, request: Request, last_event_id: str | None = Header(default=None),
                 context: TenantContext = Depends(get_tenant_context)) -> StreamingResponse:
    """从Last-Event-ID之后按小说单调序号重放；无游标从首条开始。"""
    journal = await authorized_journal(request, context, novel_id)
    try:
        cursor = int(last_event_id or '0')
        if cursor < 0:
            raise ValueError()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail='事件游标无效') from exc
    status = await journal.status(str(context.tenant_id), novel_id)
    if cursor > status['sequence']:
        raise HTTPException(status_code=409, detail='事件游标超过当前记录，请同步创作现场')
    return StreamingResponse(replay_frames(journal, str(context.tenant_id), novel_id, cursor), media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache, no-transform', 'X-Accel-Buffering': 'no'})


@router.get('/{novel_id}/run')
async def run_status(novel_id: str, request: Request, context: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    """跨进程返回当前执行状态，租约过期不得继续显示正在运行。"""
    journal = await authorized_journal(request, context, novel_id)
    return await journal.status(str(context.tenant_id), novel_id)


@router.post('/{novel_id}/recovery/retry')
async def retry_recovery(novel_id: str, request: Request, context: TenantContext = Depends(get_tenant_context)) -> dict[str, str]:
    """显式解除检查点死信退避，不修改稿件，也不直接执行模型。"""
    await authorized_journal(request, context, novel_id)
    repository = request.app.state.repository
    store = PostgresWorkflowCommandStore(repository.async_session)
    command = 'recovery-reset:' + uuid4().hex
    claim = await store.claim(str(context.tenant_id), novel_id, command, 30)
    if claim.status != WorkflowCommandClaimStatus.ACQUIRED or claim.lease_token is None:
        raise HTTPException(status_code=409, detail='小说正在执行，请稍后重试')
    previous = execution_fence.set(store.owners[claim.lease_token])
    try:
        novel = await repository.find_by_id(str(context.tenant_id), novel_id)
        pending = novel.progress.checkpoint_sync if novel else None
        if not isinstance(pending, dict):
            return {'status': 'not_found'}
        replacement = {key: value for key, value in pending.items() if key != '_recovery'}
        changed = await repository.defer_checkpoint_sync(str(context.tenant_id), novel_id, pending, replacement)
        return {'status': 'ready' if changed else 'stale'}
    finally:
        try:
            await store.release(str(context.tenant_id), novel_id, command, claim.lease_token)
        finally:
            execution_fence.reset(previous)
            await store.aclose()
