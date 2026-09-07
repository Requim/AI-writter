"""数据库事务内校验fencing，必须与小说写入持有相同的行锁。"""
from typing import Any
from sqlalchemy import select, func
from application.execution_fence import execution_fence, ExecutionLeaseLost
from infrastructure.database.runtime_models import WorkflowLeaseModel
from infrastructure.database.models import NovelModel


async def assert_execution_owner(session: Any, tenant_id: Any, novel_id: Any) -> None:
    owner = execution_fence.get()
    if owner is None:
        return
    if str(owner.tenant_id) != str(tenant_id) or str(owner.novel_id) != str(novel_id):
        raise ExecutionLeaseLost('执行作用域已变化')
    current = await session.scalar(select(WorkflowLeaseModel.fence).where(
        WorkflowLeaseModel.tenant_id == owner.tenant_id, WorkflowLeaseModel.novel_id == owner.novel_id,
        WorkflowLeaseModel.fence == owner.fence, WorkflowLeaseModel.token == owner.token,
        WorkflowLeaseModel.expires_at > func.clock_timestamp()))
    if current is None:
        raise ExecutionLeaseLost('执行租约已失效，请同步当前创作现场')


async def lock_execution_write(session: Any, tenant_id: Any, novel_id: Any) -> None:
    owner = execution_fence.get()
    if owner is None:
        return
    await session.scalar(select(NovelModel.id).where(NovelModel.tenant_id == owner.tenant_id, NovelModel.id == owner.novel_id).with_for_update())
    await assert_execution_owner(session, tenant_id, novel_id)
