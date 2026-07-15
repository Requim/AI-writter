"""Tenant-scoped LangGraph orchestration and public workflow events."""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from application.events import WorkflowEvent
from application.quota_service import QuotaService
from application.workflow_builder import create_novel_workflow
from config import settings
from infrastructure.database.repository import PostgresNovelRepository
from infrastructure.llm import AnthropicAdapter, DeepSeekAdapter, OpenAIAdapter
from infrastructure.memory.postgres_memory import PostgresMemoryAdapter
from service.entities.identity import TenantContext
from service.ports.agent_service import AgentOrchestrator

logger = logging.getLogger("uvicorn")

LARGE_STATE_FIELDS = {"current_chapter_content", "memory_context", "completed_chapters"}


class NovelOrchestrator(AgentOrchestrator):
    def __init__(
        self,
        repository: PostgresNovelRepository,
        memory_service: PostgresMemoryAdapter,
        llm_config: dict[str, Any],
        quota_service: QuotaService | None = None,
    ):
        self.repository = repository
        self.memory_service = memory_service
        self.llm_config = llm_config
        self.quota_service = quota_service
        self._workflow = None
        self._checkpointer = None
        self._llm_instance = None
        self._locks: dict[str, asyncio.Lock] = {}
        self._active_tasks: dict[str, asyncio.Task[Any]] = {}
        self._auto_mode: dict[str, bool] = {}

    @staticmethod
    def execution_key(context: TenantContext, thread_id: str) -> str:
        return f"{context.tenant_id}:{thread_id}"

    def _build_llm_instance(self):
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

    def _get_llm_instance(self):
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
            return False
        await lock.acquire()
        return True

    def register_task(
        self, context: TenantContext, thread_id: str, task: asyncio.Task[Any]
    ) -> None:
        self._active_tasks[self.execution_key(context, thread_id)] = task

    def is_executing(self, context: TenantContext, thread_id: str) -> bool:
        lock = self._locks.get(self.execution_key(context, thread_id))
        return bool(lock and lock.locked())

    def finish(self, context: TenantContext, thread_id: str) -> None:
        key = self.execution_key(context, thread_id)
        self._active_tasks.pop(key, None)
        lock = self._locks.get(key)
        if lock and lock.locked():
            lock.release()

    async def cancel(self, context: TenantContext, thread_id: str) -> bool:
        task = self._active_tasks.get(self.execution_key(context, thread_id))
        if task is None or task.done():
            return False
        task.cancel()
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
        return await self._workflow.ainvoke(
            Command(resume=resume_value),
            self._make_config(context, thread_id),
        )

    @staticmethod
    def _interrupt_values(value: Any) -> list[Any]:
        if not value:
            return []
        values = value if isinstance(value, (list, tuple)) else [value]
        return [getattr(item, "value", item) for item in values]

    async def stream_events(
        self,
        context: TenantContext,
        thread_id: str,
        input_data: dict[str, Any] | None = None,
        resume_value: Any = None,
        is_resume: bool = False,
    ) -> AsyncIterator[WorkflowEvent]:
        await self._ensure_workflow()
        payload: Any = (
            Command(resume=resume_value)
            if is_resume
            else (input_data or {"novel_id": thread_id})
        )
        sequence = 0
        async for mode, chunk in self._workflow.astream(
            payload,
            self._make_config(context, thread_id),
            stream_mode=["custom", "updates"],
        ):
            if mode == "custom" and isinstance(chunk, dict):
                sequence += 1
                yield WorkflowEvent(
                    id=sequence,
                    type=chunk.get("type", "status"),
                    thread_id=thread_id,
                    node=chunk.get("node"),
                    data=chunk.get("data", {}),
                )
                continue
            if mode != "updates" or not isinstance(chunk, dict):
                continue
            interrupts = self._interrupt_values(chunk.get("__interrupt__"))
            if interrupts:
                sequence += 1
                yield WorkflowEvent(
                    id=sequence,
                    type="interrupt",
                    thread_id=thread_id,
                    data={"interrupts": interrupts},
                )
            for node, update in chunk.items():
                if node.startswith("__"):
                    continue
                sequence += 1
                yield WorkflowEvent(
                    id=sequence,
                    type="status",
                    thread_id=thread_id,
                    node=node,
                    data={"status": "completed"},
                )
                if isinstance(update, dict) and "router_reasoning" in update:
                    sequence += 1
                    yield WorkflowEvent(
                        id=sequence,
                        type="reasoning",
                        thread_id=thread_id,
                        node=node,
                        data={"text": update["router_reasoning"]},
                    )
                if isinstance(update, dict) and "progress_percentage" in update:
                    sequence += 1
                    yield WorkflowEvent(
                        id=sequence,
                        type="progress",
                        thread_id=thread_id,
                        node=node,
                        data={
                            "percentage": update["progress_percentage"],
                            "current_chapter": update.get("current_chapter_index"),
                        },
                    )
        sequence += 1
        yield WorkflowEvent(
            id=sequence,
            type="completed",
            thread_id=thread_id,
            data={"status": "idle"},
        )

    async def stream(
        self, context: TenantContext, thread_id: str, input_data: dict[str, Any]
    ):
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
        interrupts = []
        for task in getattr(state, "tasks", []) or []:
            interrupts.extend(
                self._interrupt_values(getattr(task, "interrupts", []))
            )
        return {
            "thread_id": thread_id,
            "status": "running" if self.is_executing(context, thread_id) else "idle",
            "has_interrupt": bool(interrupts),
            "interrupts": interrupts,
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
