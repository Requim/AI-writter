"""长期记忆检索节点"""
from langgraph.types import Command
from typing import Literal
from application.schemas.agent_state import NovelAgentState


async def memory_retrieval_node(state: NovelAgentState, config) -> Command[Literal["chapter_outline_node"]]:
    """
    长期记忆检索节点 - 检索前文上下文，确保章节连贯性
    """
    memory_service = config["configurable"].get("memory_service")
    novel_id = config["configurable"].get("thread_id", "")  # thread_id = novel_id
    current_index = state.get("current_chapter_index", 0)
    memory_status = '✅ 已连接' if memory_service else '❌ 不可用'
    print(f"{'='*60}", flush=True)
    print(f"【记忆检索节点】进入 | 小说ID={novel_id}, 当前章节={current_index}, 记忆服务={memory_status}", flush=True)

    if memory_service and novel_id:
        # 从长期记忆服务检索前文上下文
        memory_context = await memory_service.get_novel_context(novel_id)
    else:
        # 降级：从已完成章节构造上下文（含开头+结尾）
        completed = state.get("completed_chapters", [])
        memory_parts = []
        for ch in completed[-3:]:
            full = ch.get('content', '')
            head = full[:400]
            tail = f"\n（结尾）{full[-300:]}" if len(full) > 700 else ""
            memory_parts.append(
                f"第{ch.get('chapter_index', 0) + 1}章：{ch.get('title', '')}\n{head}{tail}"
            )
        memory_context = "\n\n".join(memory_parts)

    print(f"【记忆检索节点】完成 -> 章节细纲节点 | memory_context长度={len(memory_context)}字", flush=True)
    print(f"{'='*60}", flush=True)
    return Command(
        goto="chapter_outline_node",
        update={"memory_context": memory_context}
    )
