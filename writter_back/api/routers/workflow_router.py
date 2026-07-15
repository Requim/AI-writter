"""Authenticated, tenant-scoped workflow streaming, resume and cancellation."""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.dependencies import get_tenant_context
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
) -> None:
    try:
        novel = await repository.find_by_id(str(context.tenant_id), thread_id)
    except ValueError:
        novel = None
    if novel is None:
        raise HTTPException(status_code=404, detail="小说不存在")


async def _prepare_request(
    request: WorkflowInvokeRequest,
    context: TenantContext,
    thread_id: str,
    orchestrator: NovelOrchestrator,
    quota: QuotaService,
) -> tuple[dict[str, Any] | None, Any, bool]:
    input_data = dict(request.input or {})
    command = dict(request.command or {})
    input_data.pop("tenant_id", None)
    command.pop("tenant_id", None)
    is_resume = request.command is not None
    auto_mode = command.pop("_auto_mode", input_data.pop("_auto_mode", False))
    orchestrator.set_auto_mode(context, thread_id, bool(auto_mode))
    if not is_resume:
        existing_run_id = await orchestrator.get_workflow_run_id(context, thread_id)
        run_id = str(input_data.get("workflow_run_id") or existing_run_id or uuid4())
        input_data["workflow_run_id"] = run_id
        input_data["novel_id"] = thread_id
        try:
            await quota.reserve(context, run_id, "outline", -1)
        except (QuotaExceededError, AIUnavailableError) as exc:
            raise HTTPException(status_code=429, detail={"code": "quota_exceeded", "message": str(exc)}) from exc
    return input_data if not is_resume else None, command.get("resume"), is_resume


def _public_error(exc: Exception) -> str:
    return _public_error_data(exc)["message"]


def _public_error_data(exc: Exception) -> dict[str, Any]:
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
    if exc.__class__.__name__ in {"APITimeoutError", "APIConnectionError"}:
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
        raise HTTPException(status_code=409, detail="该工作流正在执行中，请等待或取消当前任务")


@router.post("/{thread_id}/invoke", deprecated=True)
async def invoke_workflow(
    thread_id: str,
    request: WorkflowInvokeRequest,
    context: TenantContext = Depends(get_tenant_context),
    orchestrator: NovelOrchestrator = Depends(get_orchestrator),
    repository: PostgresNovelRepository = Depends(get_repository),
    quota: QuotaService = Depends(get_quota_service),
) -> Any:
    await _authorize_thread(context, thread_id, repository)
    await _acquire(orchestrator, context, thread_id)
    try:
        input_data, resume_value, is_resume = await _prepare_request(
            request, context, thread_id, orchestrator, quota
        )
        current = asyncio.current_task()
        if current:
            orchestrator.register_task(context, thread_id, current)
        operation = (
            orchestrator.resume(context, thread_id, resume_value)
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
    await _authorize_thread(context, thread_id, repository)
    try:
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
    await _authorize_thread(context, thread_id, repository)
    await _acquire(orchestrator, context, thread_id)
    try:
        input_data, resume_value, is_resume = await _prepare_request(
            request, context, thread_id, orchestrator, quota
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
            await asyncio.gather(producer, return_exceptions=True)
            orchestrator.finish(context, thread_id)

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
        "status": "cancelling" if cancelled else "idle",
    }
