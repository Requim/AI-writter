"""Authenticated, tenant-scoped workflow streaming, resume and cancellation."""

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, TypeAlias
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.dependencies import get_tenant_context
from api.workflow_commands import (
    ClaimedWorkflowCommand,
    claim_command as _claim_command,
    command_error as _command_error,
    finalize_command as _finalize_command,
    finalize_command_or_http as _finalize_command_or_http,
    get_workflow_command_store,
    release_command as _release_command,
    release_command_or_http as _release_command_or_http,
    resolve_command_id,
)
from application.checkpoint_reconciliation import reconcile_pending_checkpoint
from application.errors import (
    InvalidReviewDecisionError,
    RetryableWorkflowError,
    StaleWorkflowDecisionError,
)
from application.events import WorkflowEvent
from application.orchestrator import NovelOrchestrator
from application.proposals import (
    CURRENT_WORKFLOW_SCHEMA_VERSION,
    LEGACY_WORKFLOW_SCHEMA_VERSION,
)
from application.quota_service import QuotaService
from config import settings
from infrastructure.database.identity_repository import (
    AIUnavailableError,
    QuotaExceededError,
)
from infrastructure.database.repository import PostgresNovelRepository
from service.entities.identity import TenantContext
from service.entities.novel import Novel
from service.ports.workflow_command_store import (
    WorkflowCommandStore,
    WorkflowCommandStoreUnavailable,
)

logger = logging.getLogger("uvicorn")
router = APIRouter()
_MAX_PROVIDER_RETRY_AFTER_SECONDS = 120.0


def get_orchestrator(request: Request) -> NovelOrchestrator:
    return request.app.state.orchestrator


def get_repository(request: Request) -> PostgresNovelRepository:
    return request.app.state.repository


def get_quota_service(request: Request) -> QuotaService:
    return request.app.state.quota_service


class WorkflowInvokeRequest(BaseModel):
    input: dict[str, Any] | None = None
    command: dict[str, Any] | None = None


@dataclass(frozen=True)
class PreparedWorkflow:
    input_data: dict[str, Any] | None
    resume_value: Any
    is_resume: bool
    is_retry: bool
    command: ClaimedWorkflowCommand
    auto_mode: bool = False


StreamItem: TypeAlias = WorkflowEvent | Exception | None


def _resolve_command_id(idempotency_key: str | None) -> str:
    """保留旧路由私有入口，实际规则由共享命令保护模块维护。"""
    return resolve_command_id(idempotency_key)


@dataclass
class StreamChannel:
    queue: asyncio.Queue[StreamItem]
    disconnected: asyncio.Event

    def publish(self, item: StreamItem) -> None:
        if not self.disconnected.is_set():
            self.queue.put_nowait(item)

    def disconnect(self) -> None:
        self.disconnected.set()
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break


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
    if outline.main_characters:
        input_data.setdefault(
            "character_design",
            {
                "naming_policy": outline.creative_brief.get("naming_policy", {}),
                "characters": outline.main_characters,
                "relationships": [],
            },
        )
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


def _requested_auto_mode(request: WorkflowInvokeRequest) -> bool:
    command = request.command or {}
    input_data = request.input or {}
    return bool(command.get("_auto_mode", input_data.get("_auto_mode", False)))


async def _validate_resume_decision(
    orchestrator: NovelOrchestrator,
    context: TenantContext,
    thread_id: str,
    resume_value: Any,
) -> None:
    validator = getattr(orchestrator, "validate_resume_decision", None)
    if not callable(validator):
        return
    try:
        await validator(context, thread_id, resume_value)
    except StaleWorkflowDecisionError as exc:
        raise _command_error(
            409, "stale_workflow_decision", str(exc)
        ) from exc
    except InvalidReviewDecisionError as exc:
        raise _command_error(
            422, "invalid_workflow_decision", str(exc), False
        ) from exc


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
    if is_resume:
        await _validate_resume_decision(
            orchestrator, context, thread_id, command.get("resume")
        )
    auto_mode = command.pop("_auto_mode", input_data.pop("_auto_mode", False))
    orchestrator.set_auto_mode(context, thread_id, bool(auto_mode))
    if not is_resume and not is_retry:
        input_data["workflow_schema_version"] = (
            CURRENT_WORKFLOW_SCHEMA_VERSION
            if settings.WORKFLOW_REVIEW_V3_ENABLED
            else LEGACY_WORKFLOW_SCHEMA_VERSION
        )
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
    if isinstance(exc, StaleWorkflowDecisionError):
        return {
            "code": "stale_workflow_decision",
            "message": str(exc),
            "retryable": True,
        }
    if isinstance(exc, InvalidReviewDecisionError):
        return {
            "code": "invalid_workflow_decision",
            "message": str(exc),
            "retryable": False,
        }
    if isinstance(exc, RetryableWorkflowError):
        return {
            "code": "structured_output_invalid",
            "message": "模型返回的审读结果格式不符合要求，请重试当前步骤",
            "retryable": True,
        }
    if settings.DEBUG:
        return {"code": "workflow_failed", "message": str(exc), "retryable": False}
    provider_error = _provider_status_error(exc)
    if provider_error:
        return provider_error
    if _is_provider_connection_error(exc):
        return {
            "code": "provider_connection_failed",
            "message": "无法稳定连接模型服务，请重试当前步骤",
            "retryable": True,
        }
    payload: dict[str, Any] = {
        "code": getattr(exc, "code", None) or "workflow_failed",
        "message": "当前步骤执行失败，请同步创作现场后重试，并查看错误详情",
        "retryable": True,
    }
    for field in ("node", "retry_attempt"):
        value = getattr(exc, field, None)
        if value is not None:
            payload[field] = value
    return payload


def _provider_status_error(exc: Exception) -> dict[str, Any] | None:
    status = getattr(exc, "status_code", None)
    retry_after = _retry_after_seconds(exc)
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
    return None


def _is_retryable_provider_error(exc: Exception) -> bool:
    return _provider_status_error(exc) is not None or _is_provider_connection_error(exc)


def _header_retry_after(headers: Any) -> Any:
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return None
    return getter("retry-after") or getter("Retry-After")


def _raw_retry_after(exc: Exception) -> Any:
    response = getattr(exc, "response", None)
    value = _header_retry_after(getattr(response, "headers", None))
    if value is not None:
        return value
    value = _header_retry_after(getattr(exc, "headers", None))
    if value is not None:
        return value
    body = getattr(exc, "body", None)
    return body.get("retry_after") if isinstance(body, Mapping) else None


def _retry_after_seconds(exc: Exception) -> float | None:
    raw = _raw_retry_after(exc)
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        try:
            target = parsedate_to_datetime(str(raw))
            target = target.replace(tzinfo=target.tzinfo or timezone.utc)
            seconds = (target - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    return min(_MAX_PROVIDER_RETRY_AFTER_SECONDS, max(0.0, seconds))


async def _wait_for_auto_retry(exc: Exception) -> float:
    delay = _retry_after_seconds(exc) or 0.0
    if delay:
        await asyncio.sleep(delay)
    return delay


def _record_retry_attempt(
    orchestrator: NovelOrchestrator,
    context: TenantContext,
    thread_id: str,
    attempt: int,
) -> None:
    recorder = getattr(orchestrator, "record_retry_attempt", None)
    if callable(recorder):
        recorder(context, thread_id, attempt)


def _should_auto_retry(
    prepared: PreparedWorkflow, exc: Exception, attempt: int
) -> bool:
    return (
        settings.WORKFLOW_AUTO_RETRY_ENABLED
        and prepared.auto_mode
        and attempt == 0
        and _is_retryable_provider_error(exc)
    )


def _retry_prepared(prepared: PreparedWorkflow) -> PreparedWorkflow:
    return replace(
        prepared,
        input_data=None,
        resume_value=None,
        is_resume=False,
        is_retry=True,
    )


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


async def _prepare_execution(
    thread_id: str,
    request: WorkflowInvokeRequest,
    idempotency_key: str | None,
    context: TenantContext,
    orchestrator: NovelOrchestrator,
    repository: PostgresNovelRepository,
    quota: QuotaService,
    command_store: WorkflowCommandStore,
) -> PreparedWorkflow:
    novel = await _authorize_thread(context, thread_id, repository)
    command = await _claim_command(command_store, context, thread_id, idempotency_key)
    acquired = False
    try:
        await _acquire(orchestrator, context, thread_id)
        acquired = True
        bind_command = getattr(orchestrator, "set_active_command", None)
        if callable(bind_command):
            bind_command(context, thread_id, command.command_id)
        await _ensure_checkpoint_ready(repository, orchestrator, context, thread_id)
        prepared = await _prepare_request(
            request, context, thread_id, orchestrator, quota, novel
        )
        return PreparedWorkflow(
            *prepared,
            command=command,
            auto_mode=_requested_auto_mode(request),
        )
    except (Exception, asyncio.CancelledError):
        try:
            if acquired:
                orchestrator.finish(context, thread_id)
        finally:
            await _release_command_or_http(
                command_store, context, thread_id, command
            )
        raise


async def _invoke_prepared(
    prepared: PreparedWorkflow,
    orchestrator: NovelOrchestrator,
    context: TenantContext,
    thread_id: str,
) -> Any:
    async with asyncio.timeout(settings.WORKFLOW_TIMEOUT_SECONDS):
        try:
            return await _invoke_once(prepared, orchestrator, context, thread_id)
        except Exception as exc:
            if not _should_auto_retry(prepared, exc, 0):
                raise
            logger.warning("自动模式将在原 checkpoint 重试一次: %s", thread_id)
            _record_retry_attempt(orchestrator, context, thread_id, 1)
            await _wait_for_auto_retry(exc)
            retry = _retry_prepared(prepared)
            return await _invoke_once(retry, orchestrator, context, thread_id)


async def _invoke_once(
    prepared: PreparedWorkflow,
    orchestrator: NovelOrchestrator,
    context: TenantContext,
    thread_id: str,
) -> Any:
    operation = (
        orchestrator.retry(context, thread_id)
        if prepared.is_retry
        else orchestrator.resume(context, thread_id, prepared.resume_value)
        if prepared.is_resume
        else orchestrator.invoke(context, thread_id, prepared.input_data or {})
    )
    return await operation


async def _settle_invocation(
    command_store: WorkflowCommandStore,
    context: TenantContext,
    thread_id: str,
    command: ClaimedWorkflowCommand,
    applied: bool,
) -> None:
    if applied:
        await _finalize_command_or_http(
            command_store, context, thread_id, command
        )
        return
    await _release_command_or_http(command_store, context, thread_id, command)


@router.post("/{thread_id}/invoke", deprecated=True)
async def invoke_workflow(
    thread_id: str,
    request: WorkflowInvokeRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: TenantContext = Depends(get_tenant_context),
    orchestrator: NovelOrchestrator = Depends(get_orchestrator),
    repository: PostgresNovelRepository = Depends(get_repository),
    quota: QuotaService = Depends(get_quota_service),
    command_store: WorkflowCommandStore = Depends(get_workflow_command_store),
) -> Any:
    prepared = await _prepare_execution(
        thread_id,
        request,
        idempotency_key,
        context,
        orchestrator,
        repository,
        quota,
        command_store,
    )
    applied = False
    try:
        current = asyncio.current_task()
        if current:
            orchestrator.register_task(context, thread_id, current)
        result = await _invoke_prepared(prepared, orchestrator, context, thread_id)
        applied = True
        return result
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="工作流执行超时") from exc
    except asyncio.CancelledError:
        raise HTTPException(status_code=409, detail="工作流已取消")
    except StaleWorkflowDecisionError as exc:
        raise _command_error(409, "stale_workflow_decision", str(exc)) from exc
    except InvalidReviewDecisionError as exc:
        raise _command_error(
            422, "invalid_workflow_decision", str(exc), False
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Workflow invocation failed for %s", thread_id)
        raise HTTPException(status_code=500, detail=_public_error(exc)) from exc
    finally:
        try:
            orchestrator.finish(context, thread_id)
        finally:
            await _settle_invocation(
                command_store, context, thread_id, prepared.command, applied
            )


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


async def _produce_stream_events(
    channel: StreamChannel,
    orchestrator: NovelOrchestrator,
    context: TenantContext,
    thread_id: str,
    prepared: PreparedWorkflow,
) -> None:
    attempt = 0
    sequence = 0
    current = prepared
    while True:
        try:
            async for event in _stream_attempt(
                orchestrator, context, thread_id, current
            ):
                sequence += 1
                channel.publish(event.model_copy(update={"id": sequence}))
            return
        except Exception as exc:
            if not _should_auto_retry(current, exc, attempt):
                raise
            attempt += 1
            current = _retry_prepared(current)
            _record_retry_attempt(orchestrator, context, thread_id, attempt)
            sequence += 1
            delay = _retry_after_seconds(exc) or 0.0
            channel.publish(
                _auto_retry_event(thread_id, sequence, current, delay)
            )
            await _wait_for_auto_retry(exc)


def _stream_attempt(
    orchestrator: NovelOrchestrator,
    context: TenantContext,
    thread_id: str,
    prepared: PreparedWorkflow,
) -> AsyncIterator[WorkflowEvent]:
    return orchestrator.stream_events(
        context,
        thread_id,
        input_data=prepared.input_data,
        resume_value=prepared.resume_value,
        is_resume=prepared.is_resume,
        is_retry=prepared.is_retry,
        command_id=prepared.command.command_id,
    )


def _auto_retry_event(
    thread_id: str,
    event_id: int,
    prepared: PreparedWorkflow,
    retry_after: float,
) -> WorkflowEvent:
    return WorkflowEvent(
        id=event_id,
        type="status",
        thread_id=thread_id,
        command_id=prepared.command.command_id,
        data={
            "status": "retrying",
            "message": "模型服务短暂异常，正在从当前步骤自动重试",
            "retry_after": retry_after,
            "retry_attempt": 1,
        },
    )


def _stream_store_error(
    thread_id: str, event_id: int, command_id: str
) -> WorkflowEvent:
    return WorkflowEvent(
        id=event_id,
        type="error",
        thread_id=thread_id,
        command_id=command_id,
        data={
            "code": "idempotency_store_unavailable",
            "message": "命令执行结果暂时无法确认，请稍后同步",
            "retryable": True,
        },
    )


def _stream_timeout_error(thread_id: str, command_id: str) -> WorkflowEvent:
    return WorkflowEvent(
        id=2_000_000,
        type="error",
        thread_id=thread_id,
        command_id=command_id,
        data={
            "code": "workflow_timeout",
            "message": "工作流执行超时，请重试当前步骤",
            "retryable": True,
        },
    )


def _heartbeat_event(
    thread_id: str,
    event_id: int,
    command_id: str,
    execution: dict[str, Any],
) -> str:
    return WorkflowEvent(
        id=event_id,
        type="heartbeat",
        thread_id=thread_id,
        command_id=command_id,
        node=execution.get("active_node"),
        data={
            "status": "running",
            "active_node": execution.get("active_node"),
            "stage_started_at": execution.get("stage_started_at"),
            "stage_elapsed_seconds": execution.get("stage_elapsed_seconds", 0),
            "retry_attempt": execution.get("retry_attempt", 0),
        },
    ).to_sse()


async def _relay_stream_queue(
    channel: StreamChannel,
    orchestrator: NovelOrchestrator,
    context: TenantContext,
    thread_id: str,
    command_id: str,
) -> AsyncIterator[str]:
    heartbeat_id = 1_000_000
    while True:
        try:
            item = await asyncio.wait_for(
                channel.queue.get(), timeout=settings.SSE_HEARTBEAT_SECONDS
            )
        except asyncio.TimeoutError:
            heartbeat_id += 1
            execution = orchestrator.get_execution_snapshot(context, thread_id)
            yield _heartbeat_event(thread_id, heartbeat_id, command_id, execution)
            continue
        if item is None:
            return
        if isinstance(item, Exception):
            logger.error("Workflow stream failed for %s", thread_id, exc_info=item)
            yield WorkflowEvent(
                id=heartbeat_id + 1,
                type="error",
                thread_id=thread_id,
                command_id=command_id,
                data=_public_error_data(item),
            ).to_sse()
            continue
        yield item.to_sse()


async def _settle_stream_command(
    channel: StreamChannel,
    command_store: WorkflowCommandStore,
    thread_id: str,
    context: TenantContext,
    prepared: PreparedWorkflow,
    applied: bool,
) -> None:
    try:
        if applied:
            await _finalize_command(command_store, context, thread_id, prepared.command)
        else:
            await _release_command(command_store, context, thread_id, prepared.command)
    except WorkflowCommandStoreUnavailable:
        logger.exception("Workflow command settlement failed for %s", thread_id)
        channel.publish(
            _stream_store_error(thread_id, 2_000_001, prepared.command.command_id)
        )


async def _run_stream_execution(
    channel: StreamChannel,
    orchestrator: NovelOrchestrator,
    command_store: WorkflowCommandStore,
    context: TenantContext,
    thread_id: str,
    prepared: PreparedWorkflow,
) -> None:
    applied = False
    try:
        async with asyncio.timeout(settings.WORKFLOW_TIMEOUT_SECONDS):
            await _produce_stream_events(
                channel, orchestrator, context, thread_id, prepared
            )
        applied = True
    except asyncio.TimeoutError:
        channel.publish(_stream_timeout_error(thread_id, prepared.command.command_id))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        channel.publish(exc)
    finally:
        try:
            await _settle_stream_command(
                channel, command_store, thread_id, context, prepared, applied
            )
        finally:
            orchestrator.finish(context, thread_id, task=asyncio.current_task())
            channel.publish(None)


async def _stream_generator(
    channel: StreamChannel,
    orchestrator: NovelOrchestrator,
    context: TenantContext,
    thread_id: str,
    command_id: str,
) -> AsyncIterator[str]:
    try:
        async for frame in _relay_stream_queue(
            channel, orchestrator, context, thread_id, command_id
        ):
            yield frame
    finally:
        channel.disconnect()


def _start_stream_execution(
    orchestrator: NovelOrchestrator,
    command_store: WorkflowCommandStore,
    context: TenantContext,
    thread_id: str,
    prepared: PreparedWorkflow,
) -> tuple[StreamChannel, asyncio.Task[None]]:
    channel = StreamChannel(asyncio.Queue(), asyncio.Event())
    producer = asyncio.create_task(
        _run_stream_execution(
            channel, orchestrator, command_store, context, thread_id, prepared
        ),
        name=f"workflow:{context.tenant_id}:{thread_id}",
    )
    orchestrator.register_task(context, thread_id, producer)
    return channel, producer


async def _stream_response(
    thread_id: str,
    request: WorkflowInvokeRequest,
    idempotency_key: str | None,
    context: TenantContext,
    orchestrator: NovelOrchestrator,
    repository: PostgresNovelRepository,
    quota: QuotaService,
    command_store: WorkflowCommandStore,
) -> StreamingResponse:
    prepared = await _prepare_execution(
        thread_id,
        request,
        idempotency_key,
        context,
        orchestrator,
        repository,
        quota,
        command_store,
    )
    channel, _producer = _start_stream_execution(
        orchestrator, command_store, context, thread_id, prepared
    )
    body = _stream_generator(
        channel, orchestrator, context, thread_id, prepared.command.command_id
    )
    return StreamingResponse(
        body,
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
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: TenantContext = Depends(get_tenant_context),
    orchestrator: NovelOrchestrator = Depends(get_orchestrator),
    repository: PostgresNovelRepository = Depends(get_repository),
    quota: QuotaService = Depends(get_quota_service),
    command_store: WorkflowCommandStore = Depends(get_workflow_command_store),
) -> StreamingResponse:
    return await _stream_response(
        thread_id,
        request,
        idempotency_key,
        context,
        orchestrator,
        repository,
        quota,
        command_store,
    )


@router.get("/{thread_id}/stream", deprecated=True)
async def stream_workflow_get(
    thread_id: str,
    context: TenantContext = Depends(get_tenant_context),
    orchestrator: NovelOrchestrator = Depends(get_orchestrator),
    repository: PostgresNovelRepository = Depends(get_repository),
    quota: QuotaService = Depends(get_quota_service),
    command_store: WorkflowCommandStore = Depends(get_workflow_command_store),
) -> StreamingResponse:
    return await _stream_response(
        thread_id,
        WorkflowInvokeRequest(input={"novel_id": thread_id}),
        str(uuid4()),
        context,
        orchestrator,
        repository,
        quota,
        command_store,
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
