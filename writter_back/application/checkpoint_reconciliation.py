"""Durable reconciliation between novel progress and LangGraph checkpoints."""

import logging
from uuid import uuid4
from typing import Any, Literal
from application.execution_fence import execution_fence
from application.reconciliation_policy import recovery_ready, deferred_request
from infrastructure.command_store.postgres_command_store import PostgresWorkflowCommandStore
from service.ports.workflow_command_store import WorkflowCommandClaimStatus

from application.orchestrator import NovelOrchestrator
from infrastructure.database.repository import PostgresNovelRepository
from service.entities.identity import TenantContext
from service.value_objects.progress import Progress

logger = logging.getLogger("uvicorn")
CheckpointStatus = Literal["synced", "not_found", "deferred"]


def _checkpoint_request(progress: Progress | None) -> dict[str, Any] | None:
    request = getattr(progress, "checkpoint_sync", None)
    if request is None:
        return None
    if not isinstance(request, dict):
        raise ValueError("checkpoint_sync must be an object")
    try:
        next_index = int(request["next_index"])
        discard_from_index = int(request["discard_from_index"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("checkpoint_sync indexes are invalid") from exc
    if next_index < 0 or discard_from_index < 0:
        raise ValueError("checkpoint_sync indexes must be non-negative")
    return {
        **request,
        "next_index": next_index,
        "discard_from_index": discard_from_index,
        "is_completed": request.get("is_completed") is True,
    }


async def _reconcile_once(
    repository: PostgresNovelRepository,
    orchestrator: NovelOrchestrator,
    context: TenantContext,
    novel_id: str,
) -> CheckpointStatus:
    """重放持久化的 checkpoint 同步请求，成功后按请求值条件清除标记。"""
    request = None
    try:
        novel = await repository.find_by_id(str(context.tenant_id), novel_id)
        request = _checkpoint_request(novel.progress if novel else None)
        if request is None:
            return "not_found"
        if not recovery_ready(request):
            return "deferred"
        synced = await orchestrator.rewind_checkpoint(
            context,
            novel_id,
            int(request["next_index"]),
            discard_from_index=int(request["discard_from_index"]),
            is_completed=bool(request["is_completed"]),
        )
        cleared = await repository.clear_checkpoint_sync(
            str(context.tenant_id), novel_id, request
        )
        return (
            "synced" if synced and cleared else "not_found" if cleared else "deferred"
        )
    except ValueError:
        logger.exception("Invalid checkpoint reconciliation state for %s", novel_id)
        return "deferred"
    except Exception:
        logger.exception("Checkpoint reconciliation deferred for novel %s", novel_id)
        await _defer_recovery(repository, context, novel_id, request)
        return "deferred"


async def _defer_recovery(repository: PostgresNovelRepository, context: TenantContext, novel_id: str, request: dict | None) -> None:
    if request is None or not isinstance(repository, PostgresNovelRepository):
        return
    replacement = deferred_request(request, "checkpoint_unavailable")
    await repository.defer_checkpoint_sync(str(context.tenant_id), novel_id, request, replacement)
    if replacement["_recovery"]["status"] == "dead_letter":
        logger.error("checkpoint_recovery_dead_letter novel=%s attempts=5", novel_id)


async def reconcile_pending_checkpoint(repository: PostgresNovelRepository, orchestrator: NovelOrchestrator, context: TenantContext, novel_id: str) -> CheckpointStatus:
    """补偿检查点也必须持有小说共享租约，避免与另一工作进程生成并发。"""
    if not isinstance(repository, PostgresNovelRepository) or execution_fence.get() is not None:
        return await _reconcile_once(repository, orchestrator, context, novel_id)
    novel = await repository.find_by_id(str(context.tenant_id), novel_id)
    pending = novel.progress.checkpoint_sync if novel and novel.progress else None
    if pending is None:
        return "not_found"
    if isinstance(pending, dict) and not recovery_ready(pending):
        return "deferred"
    store = PostgresWorkflowCommandStore(repository.async_session)
    command = "reconcile:" + uuid4().hex
    claim = await store.claim(str(context.tenant_id), novel_id, command, 60)
    if claim.status != WorkflowCommandClaimStatus.ACQUIRED or claim.lease_token is None:
        return "deferred"
    previous = execution_fence.set(store.owners[claim.lease_token])
    try:
        store.bind(claim.lease_token)
        return await _reconcile_once(repository, orchestrator, context, novel_id)
    finally:
        try:
            await store.release(str(context.tenant_id), novel_id, command, claim.lease_token)
        finally:
            execution_fence.reset(previous)
            await store.aclose()
