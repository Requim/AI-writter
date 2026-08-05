"""进度检查节点：以持久化进度为准控制下一章与完结状态。"""

import json
import logging

from langchain_core.runnables import RunnableConfig
from langgraph.types import Overwrite, interrupt

from application.schemas.agent_state import NovelAgentState
from application.feature_policy import require_planning_v1

logger = logging.getLogger("uvicorn")


def _safe_get_total_chapters(state: NovelAgentState) -> int:
    raw = state.get("total_outline")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return 0
    return int(raw.get("total_chapters", 0) or 0) if isinstance(raw, dict) else 0


async def _trusted_progress(
    state: NovelAgentState, config: RunnableConfig
) -> tuple[int, bool, bool]:
    checkpoint_index = int(state.get("current_chapter_index", 0) or 0)
    checkpoint_completed = bool(state.get("is_completed", False))
    try:
        configurable = config["configurable"]
        repo = configurable.get("novel_repository")
        novel_id = configurable.get("novel_id", "")
        if repo is None or not novel_id:
            return checkpoint_index, checkpoint_completed, False
        novel = await repo.find_by_id(configurable.get("tenant_id", ""), novel_id)
        if novel is None or novel.progress is None:
            return checkpoint_index, checkpoint_completed, False
        persisted_index = int(novel.progress.current_chapter)
        return (
            persisted_index,
            novel.progress.is_complete(),
            persisted_index < checkpoint_index,
        )
    except Exception as exc:
        logger.warning("【进度检查节点】数据库进度校验失败，沿用 checkpoint: %s", exc)
        return checkpoint_index, checkpoint_completed, False


def _rewind_cleanup(state: NovelAgentState, current_index: int) -> dict[str, object]:
    outlines = [
        item
        for item in state.get("chapter_outlines", [])
        if isinstance(item, dict)
        and isinstance(item.get("chapter_number"), int)
        and item["chapter_number"] <= current_index
    ]
    completed = [
        item
        for item in state.get("completed_chapters", [])
        if isinstance(item, dict)
        and isinstance(item.get("chapter_index"), int)
        and item["chapter_index"] < current_index
    ]
    return {
        "current_chapter_content": "",
        "compaction_checked": False,
        "compaction_metrics": {},
        "memory_context": "",
        "memory_retrieved_for_chapter": -1,
        "reflection_issues": [],
        "user_decision": {},
        "chapter_outlines": Overwrite(outlines),
        "completed_chapters": Overwrite(completed),
        "tactical_window": None,
        "tactical_previous_window": None,
        "tactical_window_expected_version": None,
        "tactical_window_persisted": False,
        "story_state_needs_reconciliation": True,
    }


def _continue_update(current_index: int) -> dict[str, object]:
    return {
        "__route__": "continue",
        "current_chapter_index": current_index,
        "current_chapter_content": "",
        "compaction_checked": False,
        "compaction_metrics": {},
        "reflection_issues": [],
        "user_decision": {},
        "memory_context": "",
    }


async def progress_check_node(
    state: NovelAgentState, config: RunnableConfig
) -> dict[str, object]:
    total_chapters = _safe_get_total_chapters(state)
    current_index, is_completed, rewound = await _trusted_progress(state, config)
    if (
        not is_completed
        and int(state.get("workflow_schema_version") or 2) >= 5
    ):
        await require_planning_v1(config)
    updates = _rewind_cleanup(state, current_index) if rewound else {}
    logger.info(
        "【进度检查节点】当前章节=%s, 总章节=%s, 是否完成=%s",
        current_index,
        total_chapters,
        is_completed,
    )
    updates.update(
        {
            "current_chapter_index": current_index,
            "is_completed": is_completed,
            "progress_percentage": (
                current_index / total_chapters * 100 if total_chapters else 0
            ),
        }
    )
    if is_completed or (total_chapters > 0 and current_index >= total_chapters):
        return {**updates, "__route__": "end"}
    if current_index == 0 or config["configurable"].get("auto_mode", False):
        return {**updates, **_continue_update(current_index)}
    interrupt(
        {
            "action": "ready_for_next_chapter",
            "message": f"第{current_index}章已完成，共{total_chapters}章",
            "current_chapter": current_index,
            "total_chapters": total_chapters,
            "progress_percentage": round(
                current_index / total_chapters * 100, 1
            ) if total_chapters else 0,
            "note": "点击「生成下一章」继续创作，或去书架查看已有章节",
        }
    )
    return {**updates, **_continue_update(current_index)}
