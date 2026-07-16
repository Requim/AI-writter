"""持久化节点 - 章节阶段写 chapters 表，设定阶段直接放行"""

import json
import logging

logger = logging.getLogger("uvicorn")
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from typing import Literal
from uuid import uuid4, UUID
from datetime import datetime
from application.schemas.agent_state import NovelAgentState
from application.continuity import extract_story_state
from application.prompts.memory_prompts import (
    build_chapter_summary_prompt,
    build_story_state_prompt,
    CHAPTER_SUMMARY_TEMPERATURE,
    CHAPTER_SUMMARY_SCHEMA,
    STORY_STATE_TEMPERATURE,
    STORY_STATE_SCHEMA,
)


async def persist_node(
    state: NovelAgentState, config: RunnableConfig
) -> Command[Literal["progress_check_node"]]:
    repository = config["configurable"].get("novel_repository")
    memory_service = config["configurable"].get("memory_service")
    novel_id = config["configurable"].get("novel_id", "")
    tenant_id = config["configurable"].get("tenant_id", "")
    current_index = state.get("current_chapter_index", 0)
    current_chapter_content = state.get("current_chapter_content", "")

    # 没有章节内容 = 设定阶段（刚走完 outline_node），同步 title/summary/outline 到 novels 表
    if not current_chapter_content:
        logger.info(f"{'=' * 60}")
        logger.info(f"【持久化节点】进入 | novel_id={novel_id}, 阶段=设定")
        if repository and novel_id:
            novel = await repository.find_by_id(tenant_id, novel_id)
            if novel is None:
                raise RuntimeError("小说设定保存失败：目标小说不存在")
            title_val = state.get("title")
            summary_val = state.get("summary")
            outline_raw = state.get("total_outline")
            updated = False
            total_ch = 0
            if title_val:
                novel.title = title_val
                updated = True
            if summary_val:
                novel.summary = summary_val
                updated = True
            if isinstance(outline_raw, dict):
                from service.value_objects.outline import Outline

                outline_fields = {
                    "story_background",
                    "main_characters",
                    "main_plot",
                    "chapters",
                    "writing_style",
                    "total_chapters",
                    "volumes",
                }
                filtered = {k: v for k, v in outline_raw.items() if k in outline_fields}
                try:
                    novel.total_outline = Outline(**filtered)
                except Exception as exc:
                    raise RuntimeError("小说设定保存失败：宏观总纲格式无效") from exc
                total_ch = int(outline_raw.get("total_chapters", 0) or 0)
                updated = True
            if total_ch and novel.progress:
                old_progress = (
                    novel.progress.to_dict()
                    if hasattr(novel.progress, "to_dict")
                    else {}
                )
                old_progress["total_chapters"] = total_ch
                from service.value_objects.progress import Progress

                novel.progress = Progress(**old_progress)
                updated = True
            if updated:
                await repository.update(tenant_id, novel)
                logger.info(
                    "【持久化节点】novels 表已更新 | title=%s, total_chapters=%s",
                    novel.title,
                    total_ch,
                )
        logger.info("【持久化节点】完成 -> 进度检查节点")
        logger.info(f"{'=' * 60}")
        return Command(goto="progress_check_node")

    # ==================== 章节阶段：保存章节 + 进度 ====================
    current_chapter_content = state.get("current_chapter_content", "")
    chapter_outline = (
        state.get("chapter_outlines", [{}])[-1] if state.get("chapter_outlines") else {}
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
    completed_count = current_index + 1
    new_percentage = (
        (completed_count / total_chapters * 100) if total_chapters > 0 else 0
    )
    is_completed = completed_count >= total_chapters if total_chapters else False

    if repository and novel_id:
        from service.entities.chapter import Chapter
        from service.value_objects.progress import Progress

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
        if memory_service is None:
            raise RuntimeError("章节保存失败：记忆服务不可用")

        memory_content, memory_metadata = memory_service.build_chapter_memory(
            completed_chapter
        )
        progress = Progress(
            current_chapter=completed_count,
            total_chapters=total_chapters,
            percentage=new_percentage,
            status="completed" if is_completed else "writing",
        )
        llm_config = config["configurable"].get("llm_config", {})
        llm_instance = llm_config.get("llm_instance")
        if llm_instance is None:
            raise RuntimeError("章节保存失败：无法生成连续性记忆")

        summary = ""
        summary_prompt = build_chapter_summary_prompt(
            completed_chapter["title"], current_chapter_content
        )
        for _attempt in range(2):
            generated_summary = await llm_instance.structured_generate(
                prompt=summary_prompt,
                schema=CHAPTER_SUMMARY_SCHEMA,
                temperature=CHAPTER_SUMMARY_TEMPERATURE,
            )
            summary_value = (
                generated_summary.get("summary")
                if isinstance(generated_summary, dict)
                else None
            )
            summary = summary_value.strip() if isinstance(summary_value, str) else ""
            if summary:
                break
        if not summary:
            raise RuntimeError("章节保存失败：章节摘要生成结果为空")

        previous_story_state = extract_story_state(state.get("memory_context", ""))
        state_prompt = build_story_state_prompt(
            current_index,
            completed_chapter["title"],
            current_chapter_content,
            previous_state=previous_story_state,
            chapter_outline=chapter_outline,
        )
        story_state_data: dict = {}
        required_story_state_fields = {
            "timeline",
            "characters",
            "open_conflicts",
            "foreshadowing",
            "immutable_facts",
            "last_transition",
        }
        for _attempt in range(2):
            generated_state = await llm_instance.structured_generate(
                prompt=state_prompt,
                schema=STORY_STATE_SCHEMA,
                temperature=STORY_STATE_TEMPERATURE,
            )
            if isinstance(
                generated_state, dict
            ) and required_story_state_fields.issubset(generated_state):
                story_state_data = generated_state
                break
        if not story_state_data:
            raise RuntimeError("章节保存失败：累计故事状态生成结果无效")
        story_state_data["updated_through_chapter"] = current_index + 1

        rolling_plan = chapter_outline.get("rolling_plan", [])
        await repository.replace_chapter(
            tenant_id,
            novel_id,
            chapter_entity,
            memory_content,
            memory_metadata,
            progress,
            chapter_summary=summary[:1200],
            story_state=json.dumps(story_state_data, ensure_ascii=False),
            rolling_plan=(
                json.dumps(rolling_plan, ensure_ascii=False) if rolling_plan else None
            ),
        )
        logger.info(
            "【持久化节点】章节、摘要、累计状态、滚动规划和进度已原子保存 | ch=%s, title=%s",
            current_index,
            completed_chapter["title"],
        )

    logger.info(
        f"【持久化节点】完成 -> 进度检查节点 | {new_percentage:.1f}%, 完结={'是' if is_completed else '否'}"
    )
    logger.info(f"{'=' * 60}")
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
        },
    )
