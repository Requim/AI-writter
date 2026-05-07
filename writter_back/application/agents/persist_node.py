"""持久化节点 - 保存章节，更新进度"""
from langgraph.types import Command
from typing import Literal
from uuid import uuid4, UUID
from datetime import datetime
from application.schemas.agent_state import NovelAgentState


async def persist_node(state: NovelAgentState, config) -> Command[Literal["progress_check_node"]]:
    """
    持久化节点 - 保存章节到数据库，更新进度，存储长期记忆
    """
    repository = config["configurable"].get("novel_repository")
    memory_service = config["configurable"].get("memory_service")
    novel_id = config["configurable"].get("thread_id", "")  # thread_id = novel_id
    current_index = state.get("current_chapter_index", 0)
    repo_status = '✅ 已连接' if repository else '❌ 不可用'
    mem_status = '✅ 已连接' if memory_service else '❌ 不可用'
    print(f"{'='*60}", flush=True)
    print(f"【持久化节点】进入 | 小说ID={novel_id}, 章节索引={current_index}, 数据库={repo_status}, 记忆服务={mem_status}", flush=True)

    current_chapter_content = state.get("current_chapter_content", "")
    chapter_outline = (
        state.get("chapter_outlines", [{}])[-1]
        if state.get("chapter_outlines") else {}
    )
    current_index = state.get("current_chapter_index", 0)

    # 构造章节数据
    chapter_id = str(uuid4())
    completed_chapter = {
        "id": chapter_id,
        "chapter_index": current_index,
        "title": chapter_outline.get("title", f"第{current_index + 1}章"),
        "content": current_chapter_content,
        "word_count": len(current_chapter_content),
        "outline": chapter_outline,
        "status": "completed",
    }

    # 持久化到数据库
    if repository and novel_id:
        try:
            from service.entities.chapter import Chapter
            from service.ports.novel_repository import NovelRepository
            from uuid import UUID

            chapter_entity = Chapter(
                id=UUID(chapter_id),
                novel_id=UUID(novel_id),
                chapter_index=current_index,
                title=completed_chapter["title"],
                outline=chapter_outline,
                content=current_chapter_content,
                word_count=completed_chapter["word_count"],
                status="completed",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            await repository.save_chapter(novel_id, chapter_entity)
            print(f"【持久化节点】章节已保存到数据库 | chapter_index={current_index}, title={completed_chapter['title']}, word_count={completed_chapter['word_count']}", flush=True)

            # 更新小说进度
            # find_by_id_with_chapters 已加载所有章节并计算了进度，无需再 add_chapter
            novel = await repository.find_by_id_with_chapters(novel_id)
            if novel:
                await repository.update(novel)
                print(f"【持久化节点】小说进度已更新 | novel_id={novel_id}", flush=True)
        except Exception as e:
            print(f"【持久化节点】数据库保存失败(降级处理): {e}", flush=True)
            # 降级：只更新状态，不中断流程
            pass

    # 存储到长期记忆
    if memory_service and novel_id:
        try:
            await memory_service.store_chapter_memory(novel_id, completed_chapter)
            print(f"【持久化节点】章节已存入长期记忆", flush=True)
        except Exception as e:
            print(f"【持久化节点】长期记忆存储失败(降级处理): {e}", flush=True)
            pass

    # 更新进度
    total_outline_raw = state.get("total_outline")
    if isinstance(total_outline_raw, str):
        import json as _json
        try:
            total_outline_raw = _json.loads(total_outline_raw)
        except Exception:
            total_outline_raw = {}
    total_chapters = (
        total_outline_raw.get("total_chapters", 0)
        if isinstance(total_outline_raw, dict)
        else 0
    )
    new_percentage = (
        ((current_index + 1) / total_chapters * 100)
        if total_chapters > 0 else 0
    )
    is_completed = (current_index + 1) >= total_chapters

    print(f"【持久化节点】完成 -> 进度检查节点 | 进度={new_percentage:.1f}%, 小说完结={'是' if is_completed else '否'}", flush=True)
    print(f"{'='*60}", flush=True)
    return Command(
        goto="progress_check_node",
        update={
            "completed_chapters": [completed_chapter],
            "progress_percentage": new_percentage,
            "is_completed": is_completed,
            "current_chapter_index": current_index + 1,
        }
    )
