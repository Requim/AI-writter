"""持久化节点 - 章节阶段写 chapters 表，设定阶段直接放行"""
import logging
logger = logging.getLogger("uvicorn")
from langgraph.types import Command
from typing import Literal
from uuid import uuid4, UUID
from datetime import datetime
from application.schemas.agent_state import NovelAgentState
from application.prompts.memory_prompts import (
    build_chapter_summary_prompt,
    build_story_state_prompt,
    CHAPTER_SUMMARY_TEMPERATURE,
    STORY_STATE_TEMPERATURE,
)


async def persist_node(state: NovelAgentState, config) -> Command[Literal["progress_check_node"]]:
    repository = config["configurable"].get("novel_repository")
    memory_service = config["configurable"].get("memory_service")
    novel_id = config["configurable"].get("thread_id", "")
    current_index = state.get("current_chapter_index", 0)
    current_chapter_content = state.get("current_chapter_content", "")

    # 没有章节内容 = 设定阶段（刚走完 outline_node），同步 title/summary/outline 到 novels 表
    if not current_chapter_content:
        logger.info(f"{'='*60}")
        logger.info(f"【持久化节点】进入 | novel_id={novel_id}, 阶段=设定")
        if repository and novel_id:
            try:
                novel = await repository.find_by_id(novel_id)
                if novel:
                    title_val = state.get("title")
                    summary_val = state.get("summary")
                    outline_raw = state.get("total_outline")
                    updated = False
                    if title_val:
                        novel.title = title_val
                        updated = True
                    if summary_val:
                        novel.summary = summary_val
                        updated = True
                    if isinstance(outline_raw, dict):
                        from service.value_objects.outline import Outline
                        outline_fields = {'story_background', 'main_characters', 'main_plot', 'chapters', 'writing_style', 'total_chapters'}
                        filtered = {k: v for k, v in outline_raw.items() if k in outline_fields}
                        try:
                            novel.total_outline = Outline(**filtered)
                        except Exception:
                            pass
                        updated = True
                    # 同步 progress.total_chapters（用于进度条显示）
                    total_ch = outline_raw.get("total_chapters", 0) if isinstance(outline_raw, dict) else 0
                    if total_ch and novel.progress:
                        old_progress = novel.progress.to_dict() if hasattr(novel.progress, 'to_dict') else {}
                        old_progress["total_chapters"] = total_ch
                        from service.value_objects.progress import Progress
                        novel.progress = Progress(**old_progress)
                        updated = True
                    if updated:
                        await repository.update(novel)
                        logger.info(f"【持久化节点】novels 表已更新 | title={novel.title}, total_chapters={total_ch}")
            except Exception as e:
                logger.info(f"【持久化节点】更新 novels 失败(降级): {e}")
        logger.info(f"【持久化节点】完成 -> 进度检查节点")
        logger.info(f"{'='*60}")
        return Command(goto="progress_check_node")

    # ==================== 章节阶段：保存章节 + 进度 ====================
    current_chapter_content = state.get("current_chapter_content", "")
    chapter_outline = (
        state.get("chapter_outlines", [{}])[-1]
        if state.get("chapter_outlines") else {}
    )

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

    if repository and novel_id:
        try:
            # UPSERT：先删该章节索引的旧版本，再保存新版本，保证每章只有一行
            await repository.delete_chapters_by_index(novel_id, current_index)
            logger.info(f"【持久化节点】已清理 ch={current_index} 旧版本")

            from service.entities.chapter import Chapter
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
            logger.info(f"【持久化节点】章节已保存 | ch={current_index}, {completed_chapter['title']}, {completed_chapter['word_count']}字")

            novel = await repository.find_by_id_with_chapters(novel_id)
            if novel:
                await repository.update(novel)
                logger.info(f"【持久化节点】进度已更新")
        except Exception as e:
            logger.info(f"【持久化节点】章节保存失败(降级): {e}")
            pass

    if memory_service and novel_id:
        try:
            # UPSERT：先删该章节索引的旧记忆，再存新版本
            await memory_service.delete_chapter_memory(novel_id, current_index)
            await memory_service.store_chapter_memory(novel_id, completed_chapter)
            logger.info(f"【持久化节点】长期记忆已存储（替换旧版）")
        except Exception as e:
            logger.info(f"【持久化节点】记忆存储失败(降级): {e}")
            pass

    # ====== Plan A: 分层记忆 —— 生成 L层摘要 + S层故事状态 ======
    if memory_service and novel_id and current_chapter_content:
        try:
            llm_config = config["configurable"].get("llm_config", {})
            llm_instance = llm_config.get("llm_instance")
            if llm_instance:
                # --- L层：章节摘要 ---
                summary_prompt = build_chapter_summary_prompt(
                    completed_chapter['title'], current_chapter_content
                )
                summary = await llm_instance.generate(summary_prompt, temperature=CHAPTER_SUMMARY_TEMPERATURE)
                await memory_service.store_chapter_summary(novel_id, current_index, summary[:500])
                logger.info(f"【持久化节点·分层记忆】L层摘要已存储 | ch={current_index}")

                # --- S层：故事状态 ---
                state_prompt = build_story_state_prompt(
                    current_index, completed_chapter['title'], current_chapter_content
                )
                story_state = await llm_instance.generate(state_prompt, temperature=STORY_STATE_TEMPERATURE)
                await memory_service.update_story_state(novel_id, story_state[:1000])
                logger.info(f"【持久化节点·分层记忆】S层故事状态已更新")
        except Exception as e:
            logger.info(f"【持久化节点·分层记忆】生成失败(降级): {e}")

    total_outline_raw = state.get("total_outline")
    if isinstance(total_outline_raw, str):
        import json as _json
        try:
            total_outline_raw = _json.loads(total_outline_raw)
        except Exception:
            total_outline_raw = {}
    total_chapters = total_outline_raw.get("total_chapters", 0) if isinstance(total_outline_raw, dict) else 0
    new_percentage = ((current_index + 1) / total_chapters * 100) if total_chapters > 0 else 0
    is_completed = (current_index + 1) >= total_chapters

    logger.info(f"【持久化节点】完成 -> 进度检查节点 | {new_percentage:.1f}%, 完结={'是' if is_completed else '否'}")
    logger.info(f"{'='*60}")
    return Command(
        goto="progress_check_node",
        update={
            "completed_chapters": [completed_chapter],
            "progress_percentage": new_percentage,
            "is_completed": is_completed,
            "current_chapter_index": current_index + 1,
            # 清理临时状态，防止下一章路由误判
            "current_chapter_content": "",
            "reflection_issues": [],
            "user_decision": {},
            "memory_context": "",
        }
    )
