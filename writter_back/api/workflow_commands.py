"""HTTP 层共享的工作流命令幂等保护。"""

import asyncio
from dataclasses import dataclass
from uuid import uuid4

from fastapi import HTTPException, Request

from config import settings
from service.entities.identity import TenantContext
from service.ports.workflow_command_store import (
    WorkflowCommandClaimStatus,
    WorkflowCommandStore,
    WorkflowCommandStoreUnavailable,
)

RUNNING_TTL_BUFFER_SECONDS = 120
TERMINAL_TTL_SECONDS = 24 * 60 * 60
COMMAND_STORE_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class ClaimedWorkflowCommand:
    command_id: str
    lease_token: str


def get_workflow_command_store(request: Request) -> WorkflowCommandStore:
    return request.app.state.workflow_command_store


def command_error(
    status_code: int, code: str, message: str, retryable: bool = True
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "retryable": retryable},
    )


def resolve_command_id(idempotency_key: str | None) -> str:
    command_id = (idempotency_key or "").strip()
    if command_id:
        return command_id
    if settings.WORKFLOW_IDEMPOTENCY_REQUIRED:
        raise command_error(
            400, "idempotency_key_required", "缺少 Idempotency-Key", False
        )
    return str(uuid4())


async def claim_command(
    store: WorkflowCommandStore,
    context: TenantContext,
    novel_id: str,
    idempotency_key: str | None,
) -> ClaimedWorkflowCommand:
    command_id = resolve_command_id(idempotency_key)
    try:
        claim = await asyncio.wait_for(
            store.claim(
                str(context.tenant_id),
                novel_id,
                command_id,
                settings.WORKFLOW_TIMEOUT_SECONDS + RUNNING_TTL_BUFFER_SECONDS,
            ),
            timeout=COMMAND_STORE_TIMEOUT_SECONDS,
        )
    except (WorkflowCommandStoreUnavailable, asyncio.TimeoutError) as exc:
        raise command_error(
            503, "idempotency_store_unavailable", "命令保护服务暂时不可用，请稍后重试"
        ) from exc
    if claim.status is WorkflowCommandClaimStatus.IN_PROGRESS:
        raise command_error(409, "workflow_command_in_progress", "该命令正在执行")
    if claim.status is WorkflowCommandClaimStatus.ALREADY_APPLIED:
        raise command_error(409, "workflow_command_already_applied", "该命令已执行")
    if claim.lease_token is None:
        raise command_error(503, "idempotency_store_unavailable", "命令租约无效")
    return ClaimedWorkflowCommand(command_id, claim.lease_token)


async def finalize_command(
    store: WorkflowCommandStore,
    context: TenantContext,
    novel_id: str,
    command: ClaimedWorkflowCommand,
) -> None:
    try:
        finalized = await asyncio.wait_for(
            store.finalize(
                str(context.tenant_id), novel_id, command.command_id,
                command.lease_token, TERMINAL_TTL_SECONDS,
            ),
            timeout=COMMAND_STORE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise WorkflowCommandStoreUnavailable from exc
    if not finalized:
        raise WorkflowCommandStoreUnavailable("workflow command lease was lost")


async def finalize_command_or_http(
    store: WorkflowCommandStore,
    context: TenantContext,
    novel_id: str,
    command: ClaimedWorkflowCommand,
) -> None:
    try:
        await finalize_command(store, context, novel_id, command)
    except WorkflowCommandStoreUnavailable as exc:
        raise command_error(
            503, "idempotency_store_unavailable", "命令执行结果暂时无法确认，请稍后同步"
        ) from exc


async def release_command(
    store: WorkflowCommandStore,
    context: TenantContext,
    novel_id: str,
    command: ClaimedWorkflowCommand,
) -> None:
    try:
        released = await asyncio.wait_for(
            store.release(
                str(context.tenant_id), novel_id,
                command.command_id, command.lease_token,
            ),
            timeout=COMMAND_STORE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise WorkflowCommandStoreUnavailable from exc
    if not released:
        raise WorkflowCommandStoreUnavailable("workflow command lease was lost")


async def release_command_or_http(
    store: WorkflowCommandStore,
    context: TenantContext,
    novel_id: str,
    command: ClaimedWorkflowCommand,
) -> None:
    try:
        await release_command(store, context, novel_id, command)
    except WorkflowCommandStoreUnavailable as exc:
        raise command_error(
            503, "idempotency_store_unavailable", "命令重试状态暂时无法确认，请稍后同步"
        ) from exc
