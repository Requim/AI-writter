"""Agent编排器实现 - 持有所有依赖，驱动LangGraph工作流"""
import logging
logger = logging.getLogger("uvicorn")
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from typing import Dict, Any
from application.workflow_builder import create_novel_workflow
from service.ports.agent_service import AgentOrchestrator
from infrastructure.memory.postgres_memory import PostgresMemoryAdapter
from infrastructure.database.repository import PostgresNovelRepository
from config import settings
from psycopg.rows import dict_row
from infrastructure.llm import DeepSeekAdapter, OpenAIAdapter, AnthropicAdapter


class NovelOrchestrator(AgentOrchestrator):
    """Agent编排器 - 组装依赖并驱动工作流"""

    def __init__(
        self,
        repository: PostgresNovelRepository,
        memory_service: PostgresMemoryAdapter,
        llm_config: Dict[str, Any],
    ):
        self.repository = repository
        self.memory_service = memory_service
        self.llm_config = llm_config
        self._workflow = None
        self._checkpointer = None
        # 提前创建 LLM 实例，注入给 Agent 节点使用
        self._llm_instance = self._build_llm_instance()
        # 执行中标记，防止并发请求导致同一章节重复生成
        self._executing: Dict[str, bool] = {}

    def is_executing(self, thread_id: str) -> bool:
        """检查指定 thread_id 的工作流是否正在执行中"""
        return self._executing.get(thread_id, False)

    def mark_executing(self, thread_id: str, value: bool) -> None:
        """标记指定 thread_id 的工作流执行状态"""
        self._executing[thread_id] = value

    def _build_llm_instance(self):
        """根据配置创建 LLM 适配器实例"""
        provider = self.llm_config.get("provider", "deepseek")
        model = self.llm_config.get("model", "deepseek-chat")

        if provider == "openai":
            api_key = self.llm_config.get("openai_api_key", "")
            return OpenAIAdapter(api_key=api_key, model=model)
        elif provider == "anthropic":
            api_key = self.llm_config.get("anthropic_api_key", "")
            return AnthropicAdapter(api_key=api_key, model=model)
        else:
            # 默认 DeepSeek
            api_key = self.llm_config.get("deepseek_api_key", "")
            return DeepSeekAdapter(api_key=api_key, model=model)

    async def _ensure_workflow(self):
        if self._workflow is None:
            # Use AsyncPostgresSaver for async operations
            # psycopg AsyncConnection expects URL without +asyncpg
            db_url = settings.DATABASE_URL
            if "+asyncpg" in db_url:
                db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")

            # Use from_conn_string (async context manager) to create the checkpointer.
            # from_conn_string auto-manages connection lifecycle with correct settings.
            # The checkpointer must outlive the context, so we use a persistent
            # connection pattern instead.
            from psycopg_pool import AsyncConnectionPool

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

            logger.info(f"{'='*60}")
            logger.info(f"【编排器】检查点就绪 ✅")
            self._workflow = create_novel_workflow(checkpointer=self._checkpointer)
            logger.info(f"【编排器】工作流创建完成 ✅")
            logger.info(f"{'='*60}")

    def _make_config(self, thread_id: str) -> Dict[str, Any]:
        return {
            "configurable": {
                "thread_id": thread_id,
                "memory_service": self.memory_service,
                "novel_repository": self.repository,
                "llm_config": {
                    **self.llm_config,
                    "llm_instance": self._llm_instance,
                },
            }
        }

    async def invoke(self, thread_id: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """启动新工作流"""
        logger.info(f"{'='*60}")
        logger.info(f"【编排器·启动】进入 | thread_id={thread_id}, 输入字段={list(input_data.keys())}")
        await self._ensure_workflow()
        config = self._make_config(thread_id)
        result = await self._workflow.ainvoke(input_data, config)
        has_interrupt = "__interrupt__" in str(type(result)) or (isinstance(result, dict) and "__interrupt__" in result)
        logger.info(f"【编排器·启动】完成 | thread_id={thread_id}, 产生中断={'是' if has_interrupt else '否'}")
        logger.info(f"{'='*60}")
        return result

    async def resume(self, thread_id: str, resume_value: Any) -> Dict[str, Any]:
        """恢复被中断的工作流"""
        logger.info(f"{'='*60}")
        logger.info(f"【编排器·恢复】进入 | thread_id={thread_id}, 恢复值类型={type(resume_value).__name__}, 恢复值={str(resume_value)[:100]}")
        await self._ensure_workflow()
        config = self._make_config(thread_id)
        try:
            result = await self._workflow.ainvoke(
                Command(resume=resume_value),
                config,
            )
        except Exception as e:
            error_str = str(e).lower()
            # checkpoint 不兼容时自动降级（如旧版 v1 checkpoint 迁移到 v2 图）
            if "checkpoint" in error_str or "node" in error_str:
                logger.info(f"【编排器·恢复】Checkpoint 不兼容，降级重启: {e}")
                return await self._rebuild_from_state(thread_id)
            raise
        has_interrupt = "__interrupt__" in str(type(result)) or (isinstance(result, dict) and "__interrupt__" in result)
        logger.info(f"【编排器·恢复】完成 | thread_id={thread_id}, 产生中断={'是' if has_interrupt else '否'}")
        logger.info(f"{'='*60}")
        return result

    async def _rebuild_from_state(self, thread_id: str) -> Dict[str, Any]:
        """降级恢复：从已有 state 重启，不丢失数据"""
        logger.info(f"{'='*60}")
        logger.info(f"【编排器·降级】从已有 state 重建 | thread_id={thread_id}")
        config = self._make_config(thread_id)
        try:
            old_state = await self._workflow.aget_state(config)
            values = getattr(old_state, 'values', {}) or {}
        except Exception:
            values = {}
        
        if values.get("novel_type"):
            result = await self.invoke(thread_id, {
                "novel_id": thread_id,
                "novel_type": values.get("novel_type", ""),
                "title": values.get("title", ""),
                "summary": values.get("summary", ""),
                "total_outline": values.get("total_outline", {}),
                "graph_version": "v2",
            })
            logger.info(f"【编排器·降级】重建成功 | thread_id={thread_id}")
            logger.info(f"{'='*60}")
            return result
        
        logger.info(f"【编排器·降级】state 为空，无法重建 | thread_id={thread_id}")
        logger.info(f"{'='*60}")
        raise RuntimeError(f"无法从 checkpoint 恢复 thread_id={thread_id}，且无已有 state 可用")

    async def stream(self, thread_id: str, input_data):
        """流式执行工作流，yield SSE chunks"""
        input_desc = list(input_data.keys()) if isinstance(input_data, dict) else type(input_data).__name__
        logger.info(f"{'='*60}")
        logger.info(f"【编排器·流式】开始 | thread_id={thread_id}, 输入={input_desc}")
        await self._ensure_workflow()
        config = self._make_config(thread_id)
        chunk_count = 0
        async for chunk in self._workflow.astream(input_data, config):
            chunk_count += 1
            logger.info(f"【编排器·流式】数据块 #{chunk_count} | 类型={type(chunk).__name__}")
            yield chunk
        logger.info(f"【编排器·流式】结束 | thread_id={thread_id}, 总计数据块={chunk_count}")
        logger.info(f"{'='*60}")

    async def aclose(self):
        """关闭连接池，释放后端资源"""
        if self._checkpointer is not None:
            pool = self._checkpointer.conn
            if hasattr(pool, 'close'):
                await pool.close()
                logger.info("【编排器】连接池已关闭")
