"""在异步任务间传递执行所有权；只允许当前租约持有者提交生成结果。"""
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ExecutionFence:
    tenant_id: UUID
    novel_id: UUID
    run_id: UUID
    token: str
    fence: int


execution_fence: ContextVar[ExecutionFence | None] = ContextVar('execution_fence', default=None)


class ExecutionLeaseLost(RuntimeError):
    """旧执行者必须停止，不能把过期结果提交到新一轮任务。"""
