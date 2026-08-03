"""Authenticated, tenant-scoped workflow streaming, resume and cancellation."""

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.dependencies import get_tenant_context
from application.checkpoint_reconciliation import reconcile_pending_checkpoint
from application.errors import RetryableWorkflowError
from application.events import WorkflowEvent
from application.orchestrator import NovelOrchestrator
from application.quota_service import QuotaService
from config import settings
from infrastructure.database.identity_repository import (
    AIUnavailableError,
    QuotaExceededError,
)
from infrastructure.database.repository import PostgresNovelRepository
from service.entities.identity import TenantContext
from service.entities.novel import Novel

logger = logging.getLogger("uvicorn")
router = APIRouter()


def get_orchestrator(request: Request) -> NovelOrchestrator:
    return request.app.state.orchestrator


def get_repository(request: Request) -> PostgresNovelRepository:
    return request.app.state.repository


def get_quota_service(request: Request) -> QuotaService:
    return request.app.state.quota_service


class WorkflowInvokeRequest(BaseModel):
    input: dict[str, Any] | None = None
    command: dict[str, Any] | None = None


async def _authorize_thread(
    context: TenantContext,
    thread_id: str,
    repository: PostgresNovelRepository,
) -> Novel:
    try:
        novel = await repository.find_by_id(str(context.tenant_id), thread_id)
    except ValueError:
        novel = None
    if novel is None:
        raise HTTPException(status_code=404, detail="小说不存在")
    return novel


def _seed_initial_input(input_data: dict[str, Any], novel: Novel) -> None:
    """Backfill persisted creation settings without overriding explicit input."""
    input_data.setdefault("novel_type", novel.novel_type)
    if novel.progress is not None:
        input_data.setdefault("current_chapter_index", novel.progress.current_chapter)
        input_data.setdefault("progress_percentage", novel.progress.percentage)
        input_data.setdefault("is_completed", novel.progress.is_complete())
    if novel.title:
        input_data.setdefault("title", novel.title)
    if novel.summary:
        input_data.setdefault("summary", novel.summary)

    outline = novel.total_outline
    if outline is None:
        return
    if outline.creative_brief:
        input_data.setdefault("creative_brief", outline.creative_brief)
    if outline.prompt_version:
        input_data.setdefault("prompt_version", outline.prompt_version)
    if outline.story_background and outline.main_plot and outline.volumes:
        outline_data = asdict(outline)
        if novel.title:
            outline_data["source_title"] = novel.title
        if novel.summary:
            outline_data["source_summary"] = novel.summary
        input_data.setdefault("total_outline", outline_data)
        return
    if outline.total_chapters:
        input_data.setdefault("target_total_chapters", outline.total_chapters)
    if outline.writing_style:
        input_data.setdefault("requested_writing_style", outline.writing_style)


async def _prepare_request(
    request: WorkflowInvokeRequest,
    context: TenantContext,
    thread_id: str,
    orchestrator: NovelOrchestrator,
    quota: QuotaService,
    novel: Novel | None = None,
) -> tuple[dict[str, Any] | None, Any, bool, bool]:
    input_data = dict(request.input or {})
    command = dict(request.command or {})
    input_data.pop("tenant_id", None)
    command.pop("tenant_id", None)
    is_retry = command.pop("retry", False) is True
    is_resume = "resume" in command
    if is_retry and is_resume:
        raise HTTPException(status_code=422, detail="retry 与 resume 不能同时提交")
    if request.command is not None and not is_retry and not is_resume:
        raise HTTPException(status_code=422, detail="工作流 command 无效")
    auto_mode = command.pop("_auto_mode", input_data.pop("_auto_mode", False))
    orchestrator.set_auto_mode(context, thread_id, bool(auto_mode))
    if not is_resume and not is_retry:
        if novel is not None:
            _seed_initial_input(input_data, novel)
        existing_run_id = await orchestrator.get_workflow_run_id(context, thread_id)
        run_id = str(input_data.get("workflow_run_id") or existing_run_id or uuid4())
        input_data["workflow_run_id"] = run_id
        input_data["novel_id"] = thread_id
        try:
            await quota.reserve(context, run_id, "outline", -1)
        except (QuotaExceededError, AIUnavailableError) as exc:
            raise HTTPException(status_code=429, detail={"code": "quota_exceeded", "message": str(exc)}) from exc
    return (
        input_data if not is_resume and not is_retry else None,
        command.get("resume"),
        is_resume,
        is_retry,
    )


def _public_error(exc: Exception) -> str:
    return _public_error_data(exc)["message"]


def _is_provider_connection_error(exc: Exception) -> bool:
    if exc.__class__.__name__ in {"APITimeoutError", "APIConnectionError"}:
        return True
    message = str(exc).lower()
    return (
        exc.__class__.__name__ == "APIError"
        and "stream" in message
        and "interrupt" in message
    )


def _public_error_data(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, RetryableWorkflowError):
        return {
            "code": "structured_output_invalid",
            "message": "模型返回的审读结果格式不符合要求，请重试当前步骤",
            "retryable": True,
        }
    if settings.DEBUG:
        return {"code": "workflow_failed", "message": str(exc), "retryable": False}

    status = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None)
    body_data = body if isinstance(body, dict) else {}
    retry_after = body_data.get("retry_after")
    if status in {408, 504, 524}:
        return {
            "code": "provider_timeout",
            "message": "模型服务生成超时，请重试当前步骤",
            "retryable": True,
            "retry_after": retry_after,
        }
    if status == 429:
        return {
            "code": "provider_rate_limited",
            "message": "模型服务当前繁忙，请稍后重试",
            "retryable": True,
            "retry_after": retry_after,
        }
    if isinstance(status, int) and status >= 500:
        return {
            "code": "provider_unavailable",
            "message": "模型服务暂时不可用，请重试当前步骤",
            "retryable": True,
            "retry_after": retry_after,
        }
    if _is_provider_connection_error(exc):
        return {
            "code": "provider_connection_failed",
            "message": "无法稳定连接模型服务，请重试当前步骤",
            "retryable": True,
        }
    return {
        "code": "workflow_failed",
        "message": "工作流执行失败，请联系管理员查看日志",
        "retryable": False,
    }


async def _acquire(
    orchestrator: NovelOrchestrator,
    context: TenantContext,
    thread_id: str,
) -> None:
    if not await orchestrator.try_start(context, thread_id):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "workflow_already_running",
                "message": "该作品已有创作任务，请查看当前阶段或先结束任务",
            },
        )


async def _ensure_checkpoint_ready(
    repository: PostgresNovelRepository,
    orchestrator: NovelOrchestrator,
    context: TenantContext,
    thread_id: str,
) -> None:
    status = await reconcile_pending_checkpoint(
        repository, orchestrator, context, thread_id
    )
    if status == "deferred":
        raise HTTPException(
            status_code=503,
            detail={
                "code": "checkpoint_sync_pending",
                "message": "创作现场正在同步，请稍后重试",
            },
        )


@router.post("/{thread_id}/invoke", deprecated=True)
async def invoke_workflow(
    thread_id: str,
    request: WorkflowInvokeRequest,
    context: TenantContext = Depends(get_tenant_context),
    orchestrator: NovelOrchestrator = Depends(get_orchestrator),
    repository: PostgresNovelRepository = Depends(get_repository),
    quota: QuotaService = Depends(get_quota_service),
) -> Any:
    novel = await _authorize_thread(context, thread_id, repository)
    await _acquire(orchestrator, context, thread_id)
    try:
        await _ensure_checkpoint_ready(
            repository, orchestrator, context, thread_id
        )
        input_data, resume_value, is_resume, is_retry = await _prepare_request(
            request, context, thread_id, orchestrator, quota, novel
        )
        current = asyncio.current_task()
        if current:
            orchestrator.register_task(context, thread_id, current)
        operation = (
            orchestrator.retry(context, thread_id)
            if is_retry
            else orchestrator.resume(context, thread_id, resume_value)
            if is_resume
            else orchestrator.invoke(context, thread_id, input_data or {})
        )
        return await asyncio.wait_for(
            operation, timeout=settings.WORKFLOW_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="工作流执行超时") from exc
    except asyncio.CancelledError:
        raise HTTPException(status_code=409, detail="工作流已取消")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Workflow invocation failed for %s", thread_id)
        raise HTTPException(status_code=500, detail=_public_error(exc)) from exc
    finally:
        orchestrator.finish(context, thread_id)


@router.get("/{thread_id}/state")
async def get_workflow_state(
    thread_id: str,
    context: TenantContext = Depends(get_tenant_context),
    orchestrator: NovelOrchestrator = Depends(get_orchestrator),
    repository: PostgresNovelRepository = Depends(get_repository),
) -> dict[str, Any]:
    novel = await _authorize_thread(context, thread_id, repository)
    try:
        if not orchestrator.is_executing(context, thread_id):
            status = await reconcile_pending_checkpoint(
                repository, orchestrator, context, thread_id
            )
            if status == "deferred":
                return {
                    "thread_id": thread_id,
                    "status": "unknown",
                    "has_interrupt": False,
                    "interrupts": [],
                    "next_nodes": [],
                    "execution": {"message": "创作现场正在同步"},
                    "state": {
                        "current_chapter_index": novel.progress.current_chapter,
                    },
                }
        return await asyncio.wait_for(
            orchestrator.get_public_state(context, thread_id), timeout=10.0
        )
    except asyncio.TimeoutError:
        return {
            "thread_id": thread_id,
            "status": "unknown",
            "has_interrupt": False,
            "interrupts": [],
            "state": {},
        }


async def _stream_response(
    thread_id: str,
    request: WorkflowInvokeRequest,
    context: TenantContext,
    orchestrator: NovelOrchestrator,
    repository: PostgresNovelRepository,
    quota: QuotaService,
) -> StreamingResponse:
    novel = await _authorize_thread(context, thread_id, repository)
    await _acquire(orchestrator, context, thread_id)
    try:
        await _ensure_checkpoint_ready(
            repository, orchestrator, context, thread_id
        )
        input_data, resume_value, is_resume, is_retry = await _prepare_request(
            request, context, thread_id, orchestrator, quota, novel
        )
    except Exception:
        orchestrator.finish(context, thread_id)
        raise

    async def generate() -> AsyncIterator[str]:
        queue: asyncio.Queue[WorkflowEvent | Exception | None] = asyncio.Queue()

        async def produce() -> None:
            try:
                async for event in orchestrator.stream_events(
                    context,
                    thread_id,
                    input_data=input_data,
                    resume_value=resume_value,
                    is_resume=is_resume,
                    is_retry=is_retry,
                ):
                    await queue.put(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await queue.put(exc)
            finally:
                await queue.put(None)

        producer = asyncio.create_task(
            produce(), name=f"workflow:{context.tenant_id}:{thread_id}"
        )
        orchestrator.register_task(context, thread_id, producer)
        heartbeat_id = 1_000_000
        try:
            while True:
                try:
                    item = await asyncio.wait_for(
                        queue.get(), timeout=settings.SSE_HEARTBEAT_SECONDS
                    )
                except asyncio.TimeoutError:
                    heartbeat_id += 1
                    yield WorkflowEvent(
                        id=heartbeat_id,
                        type="heartbeat",
                        thread_id=thread_id,
                        data={"status": "running"},
                    ).to_sse()
                    continue
                if item is None:
                    break
                if isinstance(item, Exception):
                    logger.exception(
                        "Workflow stream failed for %s", thread_id, exc_info=item
                    )
                    yield WorkflowEvent(
                        id=heartbeat_id + 1,
                        type="error",
                        thread_id=thread_id,
                        data=_public_error_data(item),
                    ).to_sse()
                    break
                yield item.to_sse()
        finally:
            if not producer.done():
                producer.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(producer), timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            finally:
                orchestrator.finish(context, thread_id, task=producer)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/{thread_id}/stream")
async def stream_workflow_post(
    thread_id: str,
    request: WorkflowInvokeRequest,
    context: TenantContext = Depends(get_tenant_context),
    orchestrator: NovelOrchestrator = Depends(get_orchestrator),
    repository: PostgresNovelRepository = Depends(get_repository),
    quota: QuotaService = Depends(get_quota_service),
) -> StreamingResponse:
    return await _stream_response(
        thread_id, request, context, orchestrator, repository, quota
    )


@router.get("/{thread_id}/stream", deprecated=True)
async def stream_workflow_get(
    thread_id: str,
    context: TenantContext = Depends(get_tenant_context),
    orchestrator: NovelOrchestrator = Depends(get_orchestrator),
    repository: PostgresNovelRepository = Depends(get_repository),
    quota: QuotaService = Depends(get_quota_service),
) -> StreamingResponse:
    return await _stream_response(
        thread_id,
        WorkflowInvokeRequest(input={"novel_id": thread_id}),
        context,
        orchestrator,
        repository,
        quota,
    )


@router.post("/{thread_id}/cancel")
async def cancel_workflow(
    thread_id: str,
    context: TenantContext = Depends(get_tenant_context),
    orchestrator: NovelOrchestrator = Depends(get_orchestrator),
    repository: PostgresNovelRepository = Depends(get_repository),
) -> dict[str, str]:
    await _authorize_thread(context, thread_id, repository)
    cancelled = await orchestrator.cancel(context, thread_id)
    return {
        "thread_id": thread_id,
        "status": (
            "cancelled"
            if cancelled
            else "running"
            if orchestrator.is_executing(context, thread_id)
            else "idle"
        ),
    }
