"""进度检查节点 - 通过总纲进度条控制小说完结，每章完成后暂停等用户触发下一章"""
import logging
logger = logging.getLogger("uvicorn")
from langgraph.types import interrupt
import json
from application.schemas.agent_state import NovelAgentState


def _safe_get_total_chapters(state: NovelAgentState) -> int:
    raw = state.get("total_outline")
    if not raw:
        return 0
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return 0
    if isinstance(raw, dict):
        return raw.get("total_chapters", 0)
    return 0


async def progress_check_node(state: NovelAgentState, config) -> dict:
    is_completed = state.get("is_completed", False)
    current_index = state.get("current_chapter_index", 0)
    total_chapters = _safe_get_total_chapters(state)

    logger.info(f"{'='*60}")
    logger.info(f"【进度检查节点】进入 | 当前章节={current_index}, 总章节={total_chapters}, 是否完成={is_completed}")

    # 检测是否有章节被删除：从 DB 查已有章节数，如果 current_index 大于实际数则回退
    try:
        repo = config["configurable"].get("novel_repository")
        if repo and current_index > 0:
            novel_id = config["configurable"].get("novel_id", "")
            tenant_id = config["configurable"].get("tenant_id", "")
            if novel_id:
                novel = await repo.find_by_id_with_chapters(tenant_id, novel_id)
                if novel and len(novel.chapters) < current_index:
                    logger.info(f"【进度检查节点】检测到章节被删除: DB有{len(novel.chapters)}章, state记录{current_index}章, 回退索引")
                    current_index = len(novel.chapters)
    except Exception:
        pass

    if is_completed or (total_chapters > 0 and current_index >= total_chapters):
        logger.info("【进度检查节点】小说已完成! 进入 -> 结束")
        logger.info(f"{'='*60}")
        return {"__route__": "end"}

    if current_index == 0:
        logger.info("【进度检查节点】首章创作 -> 记忆检索节点")
        logger.info(f"{'='*60}")
        return {"__route__": "continue", "current_chapter_index": current_index}

    # 自动模式：不中断，直接继续下一章
    auto_mode = config["configurable"].get("auto_mode", False)
    if auto_mode:
        logger.info(f"【进度检查节点】自动模式 | 继续创作第 {current_index} 章")
        logger.info(f"{'='*60}")
        return {
            "__route__": "continue",
            "current_chapter_index": current_index,
            "current_chapter_content": "",
            "reflection_issues": [],
            "user_decision": {},
            "memory_context": "",
        }

    interrupt({
        "action": "ready_for_next_chapter",
        "message": f"第{current_index}章已完成，共{total_chapters}章",
        "current_chapter": current_index,
        "total_chapters": total_chapters,
        "progress_percentage": round(current_index / total_chapters * 100, 1) if total_chapters > 0 else 0,
        "note": "点击「生成下一章」继续创作，或去书架查看已有章节",
    })

    logger.info(f"【进度检查节点】用户选择继续 -> 路由节点 | 准备创作第 {current_index + 1} 章")
    logger.info(f"{'='*60}")
    return {
        "__route__": "continue",
        "current_chapter_index": current_index,
        # 清理临时状态，防止下一章路由误判
        "current_chapter_content": "",
        "reflection_issues": [],
        "user_decision": {},
        "memory_context": "",
    }
