"""Tenant-scoped LangGraph orchestration and public workflow events."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, cast

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command, Overwrite
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from application.events import WorkflowEvent
from application.quota_service import QuotaService
from application.errors import (
    RetryableWorkflowError,
    StaleWorkflowDecisionError,
    WorkflowBusyError,
)
from application.agents.router_agent import _route
from application.proposals import proposal_update, resolve_review_decision
from application.schemas.agent_state import NovelAgentState, PendingProposal
from application.workflow_builder import WORKFLOW_NODES, create_novel_workflow
from config import settings
from infrastructure.database.repository import PostgresNovelRepository
from infrastructure.llm import AnthropicAdapter, DeepSeekAdapter, OpenAIAdapter
from infrastructure.memory.postgres_memory import PostgresMemoryAdapter
from service.entities.identity import TenantContext
from service.ports.agent_service import AgentOrchestrator

logger = logging.getLogger("uvicorn")

LARGE_STATE_FIELDS = {
    "current_chapter_content",
    "memory_context",
    "completed_chapters",
    "quality_results",
}
TASK_REGISTRATION_GRACE_SECONDS = 60.0

LEGACY_PROPOSAL_FIELDS = {
    "review_or_modify_creative_brief": ("creative_brief", "ai_generated_creative_brief"),
    "review_or_modify_character_design": (
        "character_design",
        "ai_generated_character_design",
    ),
    "confirm_or_provide_title": ("title", "ai_suggestions"),
    "confirm_or_provide_summary": ("summary", "ai_generated_summary"),
    "review_or_modify_outline": ("outline", "ai_generated_outline"),
    "review_or_provide_chapter_outline": ("chapter_outline", "ai_generated_outline"),
}
LEGACY_QUALITY_ACTIONS = {
    "review_reflection_issues",
    "quality_gate_exhausted",
    "quality_gate_human_review",
}


def _legacy_quality_payload(interrupt_data: dict[str, Any]) -> dict[str, Any]:
    gate = {
        "decision": interrupt_data.get("quality_decision", "human_review"),
        "score": interrupt_data.get("quality_score", 0),
        "rubric_scores": interrupt_data.get("rubric_scores", {}),
        "word_count_analysis": interrupt_data.get("word_count_analysis", {}),
        "source_score_scale": interrupt_data.get("source_score_scale"),
    }
    return {
        "status": "ready",
        "action": interrupt_data.get("action"),
        "gate": gate,
        "issues": interrupt_data.get("issues", []),
    }


def _legacy_proposal_parts(interrupt_data: Any) -> tuple[str, Any, int | None] | None:
    """从 v2 interrupt 中提取可恢复的提案内容。"""
    if not isinstance(interrupt_data, dict):
        return None
    action = str(interrupt_data.get("action", ""))
    chapter_number = interrupt_data.get("chapter_number")
    chapter = int(chapter_number) if isinstance(chapter_number, int) else None
    if action in LEGACY_QUALITY_ACTIONS:
        return "reflection", _legacy_quality_payload(interrupt_data), chapter
    source = LEGACY_PROPOSAL_FIELDS.get(action)
    if source is None:
        return None
    kind, payload_field = source
    payload = interrupt_data.get(payload_field)
    if kind == "summary" and isinstance(payload, str):
        payload = {
            "reader_blurb": payload,
            "editorial_brief": payload,
            "legacy_single_view": True,
        }
    if payload in (None, "", [], {}):
        return None
    return kind, payload, chapter


def _rewind_state_update(
    values: dict[str, Any],
    next_index: int,
    discard_from_index: int,
    is_completed: bool,
) -> dict[str, Any]:
    total_outline = values.get("total_outline")
    total = (
        int(total_outline.get("total_chapters", 0) or 0)
        if isinstance(total_outline, dict)
        else 0
    )
    outlines = [
        item
        for item in values.get("chapter_outlines", [])
        if isinstance(item, dict)
        and isinstance(item.get("chapter_number"), int)
        and item["chapter_number"] <= next_index
    ]
    completed = [
        item
        for item in values.get("completed_chapters", [])
        if isinstance(item, dict)
        and isinstance(item.get("chapter_index"), int)
        and item["chapter_index"] < discard_from_index
    ]
    return {
        "__route__": "end" if is_completed else "continue",
        "current_chapter_index": next_index,
        "current_chapter_content": "",
        "memory_context": "",
        "memory_retrieved_for_chapter": -1,
        "reflection_issues": [],
        "user_decision": {},
        "pending_proposal": None,
        "pending_proposal_decision": None,
        "revision_instructions": "",
        "revision_attempts": 0,
        "compaction_checked": False,
        "compaction_metrics": {},
        "progress_percentage": (next_index / total * 100) if total else 0,
        "is_completed": is_completed,
        "chapter_outlines": Overwrite(outlines),
        "completed_chapters": Overwrite(completed),
    }


class NovelOrchestrator(AgentOrchestrator):
    def __init__(
        self,
        repository: PostgresNovelRepository,
        memory_service: PostgresMemoryAdapter,
        llm_config: dict[str, Any],
        quota_service: QuotaService | None = None,
    ) -> None:
        self.repository = repository
        self.memory_service = memory_service
        self.llm_config = llm_config
        self.quota_service = quota_service
        self._workflow: Any = None
        self._checkpointer: Any = None
        self._llm_instance: Any = None
        self._locks: dict[str, asyncio.Lock] = {}
        self._active_tasks: dict[str, asyncio.Task[Any]] = {}
        self._auto_mode: dict[str, bool] = {}
        self._execution_snapshots: dict[str, dict[str, Any]] = {}

    @staticmethod
    def execution_key(context: TenantContext, thread_id: str) -> str:
        return f"{context.tenant_id}:{thread_id}"

    def _registration_grace_expired(self, key: str) -> bool:
        started_at = self._execution_snapshots.get(key, {}).get("started_at")
        if not isinstance(started_at, str):
            return False
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(started_at)
        except ValueError:
            return False
        return age.total_seconds() > TASK_REGISTRATION_GRACE_SECONDS

    def _build_llm_instance(self) -> Any:
        provider = self.llm_config.get("provider", "deepseek")
        model = self.llm_config.get("model", "deepseek-chat")
        timeout = float(self.llm_config.get("timeout", settings.LLM_TIMEOUT_SECONDS))
        max_retries = int(
            self.llm_config.get("max_retries", settings.LLM_MAX_RETRIES)
        )
        if provider == "openai":
            return OpenAIAdapter(
                self.llm_config.get("openai_api_key") or "",
                model,
                timeout,
                base_url=self.llm_config.get("openai_base_url"),
                max_retries=max_retries,
            )
        if provider == "anthropic":
            return AnthropicAdapter(
                self.llm_config.get("anthropic_api_key") or "",
                model,
                timeout,
                max_retries=max_retries,
            )
        return DeepSeekAdapter(
            self.llm_config.get("deepseek_api_key") or "",
            model,
            timeout,
            max_retries=max_retries,
        )

    def _get_llm_instance(self) -> Any:
        if self._llm_instance is None:
            self._llm_instance = self._build_llm_instance()
        return self._llm_instance

    async def _ensure_workflow(self) -> None:
        if self._workflow is not None:
            return
        db_url = settings.LANGGRAPH_CHECKPOINTER_URI or settings.DATABASE_URL
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
        pool = AsyncConnectionPool(
            db_url,
            min_size=1,
            max_size=2,
            kwargs={
                "autocommit": True,
                "row_factory": dict_row,
                "prepare_threshold": 0,
            },
            open=False,
        )
        await pool.open()
        self._checkpointer = AsyncPostgresSaver(conn=pool)
        await self._checkpointer.setup()
        self._workflow = create_novel_workflow(checkpointer=self._checkpointer)
        logger.info("Tenant-scoped workflow and checkpoint pool are ready")

    def set_auto_mode(
        self, context: TenantContext, thread_id: str, enabled: bool
    ) -> None:
        self._auto_mode[self.execution_key(context, thread_id)] = enabled

    def _make_config(
        self,
        context: TenantContext,
        thread_id: str,
        include_llm: bool = True,
    ) -> dict[str, Any]:
        internal_thread_id = self.execution_key(context, thread_id)
        llm = self._get_llm_instance() if include_llm else self._llm_instance
        return {
            "configurable": {
                "thread_id": internal_thread_id,
                "public_thread_id": thread_id,
                "novel_id": thread_id,
                "tenant_id": str(context.tenant_id),
                "tenant_context": context,
                "auto_mode": self._auto_mode.get(internal_thread_id, False),
                "workflow_review_v3_enabled": settings.WORKFLOW_REVIEW_V3_ENABLED,
                "adaptive_compaction_enabled": settings.ADAPTIVE_COMPACTION_ENABLED,
                "memory_service": self.memory_service,
                "novel_repository": self.repository,
                "quota_service": self.quota_service,
                "llm_config": {**self.llm_config, "llm_instance": llm},
            }
        }

    async def try_start(self, context: TenantContext, thread_id: str) -> bool:
        key = self.execution_key(context, thread_id)
        lock = self._locks.setdefault(key, asyncio.Lock())
        if lock.locked():
            task = self._active_tasks.get(key)
            orphaned = bool(task and task.done())
            if task is None:
                orphaned = self._registration_grace_expired(key)
            if not orphaned:
                return False
            logger.warning("Recovering orphaned workflow lock for %s", thread_id)
            self.finish(context, thread_id, task=task)
        await lock.acquire()
        now = datetime.now(timezone.utc).isoformat()
        self._execution_snapshots[key] = {
            "status": "running",
            "active_node": None,
            "message": "正在连接创作工作流",
            "retry_attempt": 0,
            "started_at": now,
            "stage_started_at": now,
            "last_activity_at": now,
        }
        return True

    def set_active_command(
        self, context: TenantContext, thread_id: str, command_id: str
    ) -> None:
        """绑定当前执行命令，供事件和快照过滤旧响应。"""
        key = self.execution_key(context, thread_id)
        self._execution_snapshots.setdefault(key, {})["command_id"] = command_id

    def record_retry_attempt(
        self, context: TenantContext, thread_id: str, attempt: int
    ) -> None:
        """记录当前命令的自动重试次数，供快照与心跳展示。"""
        key = self.execution_key(context, thread_id)
        snapshot = self._execution_snapshots.setdefault(key, {})
        snapshot["retry_attempt"] = max(0, attempt)
        snapshot["last_activity_at"] = datetime.now(timezone.utc).isoformat()

    @asynccontextmanager
    async def exclusive_operation(
        self,
        context: TenantContext,
        thread_id: str,
        message: str,
    ) -> AsyncIterator[None]:
        """在小说级互斥锁内执行章节变更，避免与生成任务并发写入。"""
        if not await self.try_start(context, thread_id):
            raise WorkflowBusyError("该作品已有创作或编辑任务正在执行")
        task = asyncio.current_task()
        if task is not None:
            self.register_task(context, thread_id, task)
        self.record_activity(context, thread_id, message=message)
        try:
            yield
        finally:
            self.finish(context, thread_id, task=task)

    def register_task(
        self, context: TenantContext, thread_id: str, task: asyncio.Task[Any]
    ) -> None:
        key = self.execution_key(context, thread_id)
        self._active_tasks[key] = task
        task.add_done_callback(
            lambda completed: self.finish(context, thread_id, task=completed)
        )

    def record_activity(
        self,
        context: TenantContext,
        thread_id: str,
        *,
        active_node: str | None = None,
        message: str | None = None,
        status: str = "running",
    ) -> None:
        key = self.execution_key(context, thread_id)
        snapshot = self._execution_snapshots.setdefault(key, {})
        now = datetime.now(timezone.utc).isoformat()
        snapshot["status"] = status
        snapshot["last_activity_at"] = now
        if active_node is not None:
            if active_node != snapshot.get("active_node"):
                snapshot["stage_started_at"] = now
            snapshot["active_node"] = active_node
        if message is not None:
            snapshot["message"] = message

    def get_execution_snapshot(
        self, context: TenantContext, thread_id: str
    ) -> dict[str, Any]:
        """返回带当前阶段耗时的执行快照。"""
        key = self.execution_key(context, thread_id)
        snapshot = dict(self._execution_snapshots.get(key, {}))
        started_at = snapshot.get("stage_started_at")
        if isinstance(started_at, str):
            try:
                elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(started_at)
                snapshot["stage_elapsed_seconds"] = max(0, int(elapsed.total_seconds()))
            except ValueError:
                pass
        return snapshot

    def is_executing(self, context: TenantContext, thread_id: str) -> bool:
        lock = self._locks.get(self.execution_key(context, thread_id))
        return bool(lock and lock.locked())

    def finish(
        self,
        context: TenantContext,
        thread_id: str,
        *,
        task: asyncio.Task[Any] | None = None,
        status: str = "idle",
    ) -> None:
        key = self.execution_key(context, thread_id)
        current = self._active_tasks.get(key)
        if task is not None and current is not task:
            return
        self._active_tasks.pop(key, None)
        lock = self._locks.get(key)
        if lock and lock.locked():
            lock.release()
        snapshot = self._execution_snapshots.get(key)
        if snapshot is not None:
            snapshot["status"] = status
            snapshot["last_activity_at"] = datetime.now(timezone.utc).isoformat()

    async def cancel(self, context: TenantContext, thread_id: str) -> bool:
        key = self.execution_key(context, thread_id)
        task = self._active_tasks.get(key)
        lock = self._locks.get(key)
        if task is None:
            if not self._registration_grace_expired(key):
                return False
            recovered = bool(lock and lock.locked())
            self.finish(context, thread_id, status="cancelled")
            return recovered
        if task.done():
            recovered = bool(lock and lock.locked())
            self.finish(context, thread_id, task=task, status="cancelled")
            return recovered
        self.record_activity(
            context,
            thread_id,
            message="正在结束当前任务",
            status="cancelling",
        )
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        except Exception:
            logger.exception("Workflow task failed while cancelling %s", thread_id)
        finally:
            self.finish(context, thread_id, task=task, status="cancelled")
        return True

    async def invoke(
        self, context: TenantContext, thread_id: str, input_data: dict[str, Any]
    ) -> dict[str, Any]:
        await self._ensure_workflow()
        return await self._workflow.ainvoke(
            input_data, self._make_config(context, thread_id)
        )

    async def resume(
        self, context: TenantContext, thread_id: str, resume_value: Any
    ) -> dict[str, Any]:
        await self._ensure_workflow()
        command = await self.prepare_resume_command(context, thread_id, resume_value)
        return await self._workflow.ainvoke(
            command,
            self._make_config(context, thread_id),
        )

    async def prepare_resume_command(
        self, context: TenantContext, thread_id: str, resume_value: Any
    ) -> Command | None:
        """为旧审核 checkpoint 补建提案，避免恢复时重新调用模型。"""
        await self._ensure_workflow()
        config = self._make_config(context, thread_id, include_llm=False)
        snapshot = await self._workflow.aget_state(config)
        values = getattr(snapshot, "values", {}) or {}
        proposal = values.get("pending_proposal")
        if isinstance(proposal, dict):
            resolve_review_decision(
                cast(NovelAgentState, values),
                resume_value,
                cast(PendingProposal, proposal),
            )
            return Command(resume=resume_value)
        interrupts: list[Any] = []
        for task in getattr(snapshot, "tasks", []) or []:
            interrupts.extend(self._interrupt_values(getattr(task, "interrupts", [])))
        parts = _legacy_proposal_parts(interrupts[0] if interrupts else None)
        if parts is None:
            first = interrupts[0] if interrupts else None
            if isinstance(first, dict) and first.get("action") == "confirm_revision":
                await self._prepare_legacy_revision_recompute(config, values)
                return None
            return Command(resume=resume_value)
        kind, payload, chapter_number = parts
        update = proposal_update(
            cast(NovelAgentState, values),
            kind,
            payload,
            chapter_number,
        )
        update["workflow_schema_version"] = int(
            values.get("workflow_schema_version") or 2
        )
        update["pending_proposal_decision"] = resume_value
        logger.info("已从旧 checkpoint 补建 %s 提案", kind)
        return Command(resume=resume_value, update=update)

    async def _prepare_legacy_revision_recompute(
        self, config: dict[str, Any], values: dict[str, Any]
    ) -> None:
        """旧修订预览仅允许重算一次，后续由标准重试恢复。"""
        if values.get("legacy_revision_recompute_done"):
            raise StaleWorkflowDecisionError("旧版修订已重算，请同步最新创作现场")
        await self._route_retry_node(
            config,
            "revision_node",
            "旧版修订仅含预览，正在兼容性重算",
            {"legacy_revision_recompute_done": True},
        )
        logger.warning("旧版修订 checkpoint 仅含预览，将执行一次兼容性重算")

    async def validate_resume_decision(
        self, context: TenantContext, thread_id: str, resume_value: Any
    ) -> None:
        """在配额与模型调用前校验当前提案决定。"""
        await self._ensure_workflow()
        config = self._make_config(context, thread_id, include_llm=False)
        snapshot = await self._workflow.aget_state(config)
        values = getattr(snapshot, "values", {}) or {}
        proposal = values.get("pending_proposal")
        if not isinstance(proposal, dict):
            return
        resolve_review_decision(
            cast(NovelAgentState, values),
            resume_value,
            cast(PendingProposal, proposal),
        )

    @staticmethod
    def _failed_task_node(state: Any) -> str | None:
        for task in getattr(state, "tasks", []) or []:
            error = getattr(task, "error", None)
            name = str(getattr(task, "name", ""))
            if error is not None and name in WORKFLOW_NODES and name != "router_agent":
                return name
        return None

    async def _route_retry_node(
        self,
        config: dict[str, Any],
        next_node: str,
        reasoning: str,
        extra_update: dict[str, Any] | None = None,
    ) -> None:
        update = {"next_tool": next_node, "router_reasoning": reasoning}
        update.update(extra_update or {})
        await self._workflow.aupdate_state(
            config,
            update,
            as_node="router_agent",
        )

    async def prepare_retry_checkpoint(
        self, context: TenantContext, thread_id: str
    ) -> str:
        """Route a failed draft from trusted checkpoint state without replaying setup."""
        await self._ensure_workflow()
        config = self._make_config(context, thread_id, include_llm=False)
        state = await self._workflow.aget_state(config)
        values = getattr(state, "values", {}) or {}
        next_nodes = tuple(getattr(state, "next", ()) or ())
        failed_node = self._failed_task_node(state)
        if failed_node:
            next_node = failed_node
            reasoning = f"从原失败节点重试 {next_node}"
            await self._route_retry_node(config, next_node, reasoning)
        elif values.get("current_chapter_content"):
            next_node, reasoning = _route(values)
            await self._route_retry_node(config, next_node, reasoning)
        elif next_nodes:
            next_node = str(next_nodes[0])
            reasoning = f"从 checkpoint 重试 {next_node}"
        else:
            raise RetryableWorkflowError("当前没有可重试的工作流 checkpoint")

        self.record_activity(
            context,
            thread_id,
            active_node=next_node,
            message=reasoning,
        )
        return next_node

    async def rewind_checkpoint(
        self,
        context: TenantContext,
        thread_id: str,
        next_index: int,
        *,
        discard_from_index: int,
        is_completed: bool = False,
    ) -> bool:
        """将 checkpoint 回退到数据库已确认的下一章节位置。"""
        await self._ensure_workflow()
        config = self._make_config(context, thread_id, include_llm=False)
        state = await self._workflow.aget_state(config)
        values = getattr(state, "values", {}) or {}
        if not values:
            return False
        update = _rewind_state_update(
            values, next_index, discard_from_index, is_completed
        )
        await self._workflow.aupdate_state(
            config,
            update,
            as_node="progress_check_node",
        )
        self.record_activity(
            context,
            thread_id,
            active_node=None if is_completed else "router_agent",
            message=(
                "章节已重写，作品仍为完结状态"
                if is_completed
                else f"已回退，下一步从第 {next_index + 1} 章继续"
            ),
            status="idle",
        )
        if is_completed:
            key = self.execution_key(context, thread_id)
            self._execution_snapshots[key]["active_node"] = None
        return True

    async def retry(
        self, context: TenantContext, thread_id: str
    ) -> dict[str, Any]:
        await self.prepare_retry_checkpoint(context, thread_id)
        return await self._workflow.ainvoke(
            None,
            self._make_config(context, thread_id),
        )

    @staticmethod
    def _interrupt_values(value: Any) -> list[Any]:
        if not value:
            return []
        values = value if isinstance(value, (list, tuple)) else [value]
        return [getattr(item, "value", item) for item in values]

    async def _stream_payload(
        self,
        context: TenantContext,
        thread_id: str,
        input_data: dict[str, Any] | None,
        resume_value: Any,
        is_resume: bool,
        is_retry: bool,
    ) -> Any:
        if is_retry:
            await self.prepare_retry_checkpoint(context, thread_id)
            return None
        if is_resume:
            return await self.prepare_resume_command(context, thread_id, resume_value)
        return input_data or {"novel_id": thread_id}

    def _custom_stream_event(
        self,
        context: TenantContext,
        thread_id: str,
        chunk: dict[str, Any],
        command_id: str | None,
    ) -> WorkflowEvent:
        data = chunk.get("data", {})
        event_type = chunk.get("type", "status")
        message = (
            data.get("message") or data.get("text")
            if isinstance(data, dict)
            else None
        )
        active_node = chunk.get("node")
        if event_type == "reasoning" and isinstance(data, dict):
            active_node = data.get("next_node") or active_node
        self.record_activity(
            context,
            thread_id,
            active_node=active_node,
            message=message if isinstance(message, str) else None,
        )
        return WorkflowEvent(
            id=0,
            type=event_type,
            thread_id=thread_id,
            command_id=command_id,
            node=chunk.get("node"),
            data=data,
        )

    def _interrupt_stream_event(
        self,
        context: TenantContext,
        thread_id: str,
        interrupts: list[Any],
        command_id: str | None,
    ) -> WorkflowEvent:
        first = interrupts[0] if interrupts else None
        message = first.get("message") if isinstance(first, dict) else None
        self.record_activity(
            context,
            thread_id,
            message=message or "等待人工确认后继续",
            status="paused",
        )
        return WorkflowEvent(
            id=0,
            type="interrupt",
            thread_id=thread_id,
            command_id=command_id,
            data={"interrupts": interrupts},
        )

    def _node_stream_events(
        self,
        context: TenantContext,
        thread_id: str,
        node: str,
        update: Any,
        command_id: str | None,
    ) -> list[WorkflowEvent]:
        next_node = update.get("next_tool") if isinstance(update, dict) else None
        next_node = next_node if isinstance(next_node, str) and next_node else None
        reasoning = update.get("router_reasoning") if isinstance(update, dict) else None
        message = reasoning if isinstance(reasoning, str) and reasoning else f"{node} 已完成"
        self.record_activity(context, thread_id, active_node=next_node, message=message)
        if not next_node:
            key = self.execution_key(context, thread_id)
            snapshot = self._execution_snapshots.get(key, {})
            if snapshot.get("active_node") == node:
                snapshot["active_node"] = None
        events = [self._node_status_event(thread_id, node, next_node, command_id)]
        if isinstance(reasoning, str):
            events.append(self._event(thread_id, "reasoning", node, {"text": reasoning}, command_id))
        if isinstance(update, dict) and "progress_percentage" in update:
            data = {
                "percentage": update["progress_percentage"],
                "current_chapter": update.get("current_chapter_index"),
            }
            events.append(self._event(thread_id, "progress", node, data, command_id))
        return events

    @staticmethod
    def _event(
        thread_id: str,
        event_type: str,
        node: str | None,
        data: dict[str, Any],
        command_id: str | None,
    ) -> WorkflowEvent:
        return WorkflowEvent(
            id=0, type=event_type, thread_id=thread_id,
            command_id=command_id, node=node, data=data,
        )

    def _node_status_event(
        self, thread_id: str, node: str, next_node: str | None, command_id: str | None
    ) -> WorkflowEvent:
        data = {"status": "completed"}
        if next_node:
            data["next_node"] = next_node
        return self._event(thread_id, "status", node, data, command_id)

    async def stream_events(
        self,
        context: TenantContext,
        thread_id: str,
        input_data: dict[str, Any] | None = None,
        resume_value: Any = None,
        is_resume: bool = False,
        is_retry: bool = False,
        command_id: str | None = None,
    ) -> AsyncIterator[WorkflowEvent]:
        await self._ensure_workflow()
        message = "正在重试失败步骤" if is_retry else "正在恢复创作现场" if is_resume else "正在启动创作流程"
        self.record_activity(context, thread_id, message=message)
        payload = await self._stream_payload(
            context, thread_id, input_data, resume_value, is_resume, is_retry
        )
        sequence = 0
        async for mode, chunk in self._workflow.astream(
            payload, self._make_config(context, thread_id), stream_mode=["custom", "updates"]
        ):
            events = self._events_from_chunk(context, thread_id, mode, chunk, command_id)
            for event in events:
                sequence += 1
                yield event.model_copy(update={"id": sequence})
        self.record_activity(context, thread_id, message="本轮工作流已结束", status="completed")
        yield self._event(
            thread_id, "completed", None, {"status": "idle"}, command_id
        ).model_copy(update={"id": sequence + 1})

    def _events_from_chunk(
        self,
        context: TenantContext,
        thread_id: str,
        mode: str,
        chunk: Any,
        command_id: str | None,
    ) -> list[WorkflowEvent]:
        if mode == "custom" and isinstance(chunk, dict):
            return [self._custom_stream_event(context, thread_id, chunk, command_id)]
        if mode != "updates" or not isinstance(chunk, dict):
            return []
        events: list[WorkflowEvent] = []
        interrupts = self._interrupt_values(chunk.get("__interrupt__"))
        if interrupts:
            events.append(self._interrupt_stream_event(context, thread_id, interrupts, command_id))
        for node, update in chunk.items():
            if not node.startswith("__"):
                events.extend(self._node_stream_events(context, thread_id, node, update, command_id))
        return events

    async def stream(
        self, context: TenantContext, thread_id: str, input_data: dict[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        async for event in self.stream_events(
            context, thread_id, input_data=input_data
        ):
            yield event.model_dump(mode="json")

    async def get_public_state(
        self, context: TenantContext, thread_id: str
    ) -> dict[str, Any]:
        await self._ensure_workflow()
        state = await self._workflow.aget_state(
            self._make_config(context, thread_id, include_llm=False)
        )
        values = getattr(state, "values", {}) or {}
        safe_values = {
            key: value for key, value in values.items() if key not in LARGE_STATE_FIELDS
        }
        safe_values["has_current_chapter_content"] = bool(
            values.get("current_chapter_content")
        )
        interrupts = []
        for task in getattr(state, "tasks", []) or []:
            interrupts.extend(
                self._interrupt_values(getattr(task, "interrupts", []))
            )
        next_nodes = list(getattr(state, "next", ()) or ())
        execution = self.get_execution_snapshot(context, thread_id)
        if not execution.get("active_node") and next_nodes:
            execution["active_node"] = next_nodes[0]
        last_activity = execution.get("last_activity_at")
        stale = False
        if self.is_executing(context, thread_id) and isinstance(last_activity, str):
            try:
                elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(last_activity)
                stale = elapsed.total_seconds() > settings.WORKFLOW_TIMEOUT_SECONDS
            except ValueError:
                pass
        execution["is_stale"] = stale
        status = "running" if self.is_executing(context, thread_id) else "idle"
        if interrupts and status == "idle":
            status = "paused"
        return {
            "thread_id": thread_id,
            "status": status,
            "has_interrupt": bool(interrupts),
            "interrupts": interrupts,
            "next_nodes": next_nodes,
            "execution": execution,
            "server_time": datetime.now(timezone.utc).isoformat(),
            "state": safe_values,
        }

    async def get_workflow_run_id(
        self, context: TenantContext, thread_id: str
    ) -> str | None:
        """Read the private idempotency key from the latest checkpoint."""
        await self._ensure_workflow()
        state = await self._workflow.aget_state(
            self._make_config(context, thread_id, include_llm=False)
        )
        value = (getattr(state, "values", {}) or {}).get("workflow_run_id")
        return str(value) if value else None

    async def aclose(self) -> None:
        for task in list(self._active_tasks.values()):
            task.cancel()
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks.values(), return_exceptions=True)
        if self._checkpointer is not None:
            pool = self._checkpointer.conn
            if hasattr(pool, "close"):
                await pool.close()
