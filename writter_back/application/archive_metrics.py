"""Refresh archive sizes after independent chapter edits or rewrites."""

from application.schemas.agent_state import NovelAgentState


async def refresh_archived_word_counts(state: NovelAgentState, config: dict) -> NovelAgentState:
    """验收前按租户和作品读取已归档正文长度，避免重写后的旧检查点误计。"""
    values = config.get("configurable") or {}
    repository = values.get("novel_repository")
    reader = getattr(repository, "completed_chapter_word_counts", None)
    if not callable(reader):
        return state
    rows = await reader(values["tenant_id"], values["novel_id"])
    previous = {row["chapter_index"]: row for row in state.get("completed_chapters", [])
                if isinstance(row, dict) and isinstance(row.get("chapter_index"), int)}
    completed = [{**previous.get(row["chapter_index"], {}), **row} for row in rows]
    return {**state, "completed_chapters": completed}
