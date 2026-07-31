"""Durable reconciliation between novel progress and LangGraph checkpoints."""

import logging
from typing import Literal

from application.orchestrator import NovelOrchestrator
from infrastructure.database.repository import PostgresNovelRepository
from service.entities.identity import TenantContext
from service.value_objects.progress import Progress

logger = logging.getLogger("uvicorn")
CheckpointStatus = Literal["synced", "not_found", "deferred"]


def _checkpoint_request(progress: Progress | None) -> dict[str, object] | None:
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
        "next_index": next_index,
        "discard_from_index": discard_from_index,
        "is_completed": request.get("is_completed") is True,
    }


async def reconcile_pending_checkpoint(
    repository: PostgresNovelRepository,
    orchestrator: NovelOrchestrator,
    context: TenantContext,
    novel_id: str,
) -> CheckpointStatus:
    """重放持久化的 checkpoint 同步请求，成功后按请求值条件清除标记。"""
    try:
        novel = await repository.find_by_id(str(context.tenant_id), novel_id)
        request = _checkpoint_request(novel.progress if novel else None)
        if request is None:
            return "not_found"
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
        return "deferred"
