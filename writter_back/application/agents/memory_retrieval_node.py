"""长期记忆检索节点"""
import logging
logger = logging.getLogger("uvicorn")
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from typing import Literal
from application.schemas.agent_state import NovelAgentState


async def memory_retrieval_node(
    state: NovelAgentState,
    config: RunnableConfig,
) -> Command[Literal["router_agent"]]:
    """
    长期记忆检索节点 - 检索前文上下文，确保章节连贯性
    降级链路：MemoryService → completed_chapters(state) → DB chapters
    """
    memory_service = config["configurable"].get("memory_service")
    repository = config["configurable"].get("novel_repository")
    novel_id = config["configurable"].get("novel_id", "")
    tenant_id = config["configurable"].get("tenant_id", "")
    current_index = state.get("current_chapter_index", 0)
    memory_status = '✅ 已连接' if memory_service else '❌ 不可用'
    logger.info(f"{'='*60}")
    logger.info(f"【记忆检索节点】进入 | 小说ID={novel_id}, 当前章节={current_index}, 记忆服务={memory_status}")

    memory_context = ""
    retrieval_source = ""

    # ====== 第一优先：MemoryService（novel_memories 表） ======
    if memory_service and novel_id:
        memory_context = await memory_service.get_hierarchical_context(
            tenant_id, novel_id, current_index
        )
        if memory_context:
            retrieval_source = "MemoryService"

    # ====== 第二优先：completed_chapters（state 中的累积列表） ======
    if not memory_context:
        completed = state.get("completed_chapters", [])
        if completed:
            memory_parts = []
            for ch in completed[-3:]:
                full = ch.get('content', '')
                head = full[:400]
                tail = f"\n（结尾）{full[-300:]}" if len(full) > 700 else ""
                memory_parts.append(
                    f"第{ch.get('chapter_index', 0) + 1}章：{ch.get('title', '')}\n{head}{tail}"
                )
            memory_context = "\n\n".join(memory_parts)
            retrieval_source = "completed_chapters"
            logger.info("【记忆检索节点】从 completed_chapters 降级获取记忆")

    # ====== 第三优先：直接从 DB chapters 表查询 ======
    if not memory_context and repository and novel_id:
        try:
            novel = await repository.find_by_id_with_chapters(tenant_id, novel_id)
            if novel and hasattr(novel, 'chapters') and novel.chapters:
                chapters_sorted = sorted(novel.chapters, key=lambda c: c.chapter_index)
                memory_parts = []
                for ch in chapters_sorted[-3:]:
                    full = ch.content or ''
                    head = full[:400]
                    tail = f"\n（结尾）{full[-300:]}" if len(full) > 700 else ""
                    memory_parts.append(
                        f"第{ch.chapter_index + 1}章：{ch.title or ''}\n{head}{tail}"
                    )
                memory_context = "\n\n".join(memory_parts)
                retrieval_source = "DB(chapters)"
                logger.info(f"【记忆检索节点】从 DB chapters 表降级获取记忆，共 {len(chapters_sorted)} 章")
        except Exception as e:
            logger.info(f"【记忆检索节点】DB 降级失败: {e}")

    logger.info(f"【记忆检索节点】完成 -> 路由节点 | 来源={retrieval_source or '无'}, memory_context长度={len(memory_context)}字")
    logger.info(f"{'='*60}")
    return Command(
        goto="router_agent",
        update={
            "memory_context": memory_context,
            "memory_retrieved_for_chapter": current_index,
        },
    )
