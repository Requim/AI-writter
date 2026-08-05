"""持久化节点：保存小说设定或单章内容与连续性状态。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from application.continuity import extract_story_state
from application.prompts.memory_prompts import (
    CHAPTER_SUMMARY_SCHEMA,
    CHAPTER_SUMMARY_TEMPERATURE,
    STORY_STATE_SCHEMA,
    STORY_STATE_TEMPERATURE,
    build_chapter_summary_prompt,
    build_story_state_prompt,
)
from application.schemas.agent_state import NovelAgentState
from application.streaming import emit_workflow_event
from config import settings
from service.entities.chapter import Chapter
from service.value_objects.outline import Outline
from service.value_objects.novel_plan import NovelPlan
from service.value_objects.progress import Progress

logger = logging.getLogger("uvicorn")
OUTLINE_FIELDS = frozenset({
    "story_background", "main_characters", "main_plot", "antagonist_plan",
    "truth_reveal_ladder", "cost_curve", "relationship_turns",
    "writing_style", "total_chapters", "volumes", "scale", "creative_brief", "prompt_version",
})
STORY_STATE_FIELDS = {
    "timeline", "characters", "open_conflicts", "foreshadowing",
    "immutable_facts", "last_transition",
}
ACCEPTED_WITH_ISSUES = frozenset({"user_accepted", "user_accepted_revision"})


def _outline_value(raw: Any) -> tuple[Outline | None, int]:
    if not isinstance(raw, dict):
        return None, 0
    filtered = {key: value for key, value in raw.items() if key in OUTLINE_FIELDS}
    try:
        outline = Outline(**filtered)
        total = int(raw.get("total_chapters", 0) or 0)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("小说设定保存失败：宏观总纲格式无效") from exc
    return outline, total


async def _persist_setup(
    state: NovelAgentState, repository: Any, tenant_id: str, novel_id: str,
) -> None:
    if not repository or not novel_id:
        return
    finder = getattr(repository, "find_by_id", None)
    novel = await finder(tenant_id, novel_id) if callable(finder) else None
    if novel is None:
        raise RuntimeError("小说设定保存失败：目标小说不存在")
    updated = False
    if state.get("title"):
        novel.title = state["title"]
        updated = True
    if state.get("summary"):
        novel.summary = state["summary"]
        updated = True
    outline, total = _outline_value(state.get("total_outline"))
    if outline is not None:
        novel.total_outline = outline
        updated = True
    if total and novel.progress:
        progress_data = novel.progress.to_dict() if hasattr(novel.progress, "to_dict") else {}
        progress_data["total_chapters"] = total
        novel.progress = Progress(**progress_data)
        updated = True
    if updated:
        await repository.update(tenant_id, novel)
        logger.info("【持久化节点】novels 表已更新 | title=%s, total_chapters=%s", novel.title, total)


def _quality_score(gate: dict[str, Any]) -> float | None:
    value = gate.get("score")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _review_status(gate: dict[str, Any]) -> str:
    decision = gate.get("decision")
    if decision == "pass":
        return "passed"
    if decision == "user_accepted_without_ai_review":
        return "accepted_unreviewed"
    return "accepted_with_issues" if decision in ACCEPTED_WITH_ISSUES else "unknown"


def _chapter_review_metadata(state: NovelAgentState) -> dict[str, Any]:
    raw_gate = state.get("quality_gate")
    gate = dict(raw_gate) if isinstance(raw_gate, dict) else {}
    raw_decision = state.get("user_decision")
    decision = dict(raw_decision) if isinstance(raw_decision, dict) else {}
    decision.update({
        "review_status": _review_status(gate),
        "quality_score": _quality_score(gate),
        "source_score_scale": gate.get("source_score_scale"),
        "prompt_version": gate.get("prompt_version") or state.get("prompt_version"),
    })
    issues = state.get("reflection_issues") or []
    history = state.get("revision_history") or []
    return {
        "reflection_issues": [dict(item) for item in issues if isinstance(item, dict)],
        "user_decision": decision,
        "revision_count": int(state.get("revision_attempts", 0) or 0),
        "revision_history": [dict(item) for item in history if isinstance(item, dict)],
    }


def _completed_chapter(state: NovelAgentState, content: str, index: int) -> dict[str, Any]:
    outlines = state.get("chapter_outlines") or []
    outline = outlines[-1] if outlines and isinstance(outlines[-1], dict) else {}
    return {
        "id": str(uuid4()), "chapter_index": index,
        "title": outline.get("title", f"第{index + 1}章"), "content": content,
        "word_count": len(content), "outline": outline, "status": "completed",
        **_chapter_review_metadata(state),
    }


def _total_chapters(value: Any) -> int:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return 0
    return int(value.get("total_chapters", 0) or 0) if isinstance(value, dict) else 0


def _progress(index: int, total: int) -> tuple[int, float, bool]:
    completed = index + 1
    percentage = completed / total * 100 if total > 0 else 0
    return completed, percentage, completed >= total if total else False


def _chapter_entity(chapter: dict[str, Any], novel_id: str) -> Chapter:
    now = datetime.now()
    return Chapter(
        id=UUID(chapter["id"]), novel_id=UUID(novel_id),
        chapter_index=chapter["chapter_index"], title=chapter["title"],
        outline=chapter["outline"], content=chapter["content"],
        word_count=chapter["word_count"], status="completed",
        reflection_issues=chapter["reflection_issues"],
        user_decision=chapter["user_decision"],
        revision_count=chapter["revision_count"],
        revision_history=chapter["revision_history"],
        created_at=now, updated_at=now,
    )


async def _generate_summary(llm: Any, chapter: dict[str, Any]) -> str:
    emit_workflow_event(
        "status",
        {"status": "started", "message": "正在生成章节摘要", "stage": "chapter_summary"},
        "chapter_summary",
    )
    prompt = build_chapter_summary_prompt(chapter["title"], chapter["content"])
    for _attempt in range(2):
        generated = await llm.structured_generate(
            prompt=prompt, schema=CHAPTER_SUMMARY_SCHEMA,
            temperature=CHAPTER_SUMMARY_TEMPERATURE,
        )
        value = generated.get("summary") if isinstance(generated, dict) else None
        summary = value.strip() if isinstance(value, str) else ""
        if summary:
            return summary
    raise RuntimeError("章节保存失败：章节摘要生成结果为空")


def _previous_patterns(previous_state: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(previous_state) if previous_state else {}
    except (json.JSONDecodeError, TypeError):
        return []
    values = parsed.get("recent_narrative_patterns", []) if isinstance(parsed, dict) else []
    return [dict(item) for item in values if isinstance(item, dict)]


def _recent_patterns(
    previous_state: str, generated: dict[str, Any], outline: dict[str, Any], index: int,
) -> list[dict[str, Any]]:
    values = generated.get("recent_narrative_patterns")
    patterns = [dict(item) for item in values if isinstance(item, dict)] if isinstance(values, list) else []
    if not patterns:
        patterns = _previous_patterns(previous_state)
    current = outline.get("narrative_pattern")
    if isinstance(current, dict) and current:
        patterns = [item for item in patterns if item.get("chapter_number") != index + 1]
        patterns.append({"chapter_number": index + 1, **current})
    return patterns[-5:]


async def _generate_story_state(
    llm: Any, chapter: dict[str, Any], previous: str, index: int,
) -> dict[str, Any]:
    emit_workflow_event(
        "status",
        {"status": "started", "message": "正在更新故事状态", "stage": "story_state"},
        "story_state",
    )
    prompt = build_story_state_prompt(
        index, chapter["title"], chapter["content"], previous_state=previous,
        chapter_outline=chapter["outline"],
    )
    for _attempt in range(2):
        generated = await llm.structured_generate(
            prompt=prompt, schema=STORY_STATE_SCHEMA, temperature=STORY_STATE_TEMPERATURE,
        )
        if isinstance(generated, dict) and STORY_STATE_FIELDS.issubset(generated):
            generated["recent_narrative_patterns"] = _recent_patterns(
                previous, generated, chapter["outline"], index,
            )
            generated["updated_through_chapter"] = index + 1
            return generated
    raise RuntimeError("章节保存失败：累计故事状态生成结果无效")


async def _persist_chapter(
    state: NovelAgentState, config: RunnableConfig, chapter: dict[str, Any],
    completed_count: int, percentage: float, is_completed: bool,
) -> None:
    values = config["configurable"]
    repository = values.get("novel_repository")
    novel_id, tenant_id = values.get("novel_id", ""), values.get("tenant_id", "")
    if not repository or not novel_id:
        return
    memory_service = values.get("memory_service")
    if memory_service is None:
        raise RuntimeError("章节保存失败：记忆服务不可用")
    llm = values.get("llm_config", {}).get("llm_instance")
    if llm is None:
        raise RuntimeError("章节保存失败：无法生成连续性记忆")
    memory_content, memory_metadata = memory_service.build_chapter_memory(chapter)
    summary = await _generate_summary(llm, chapter)
    previous = extract_story_state(state.get("memory_context", ""))
    story_state = await _generate_story_state(llm, chapter, previous, chapter["chapter_index"])
    rolling_plan = chapter["outline"].get("rolling_plan", [])
    progress = await _chapter_progress(
        repository, tenant_id, novel_id, state, chapter,
        completed_count, percentage, is_completed,
    )
    await repository.replace_chapter(
        tenant_id, novel_id, _chapter_entity(chapter, novel_id), memory_content,
        memory_metadata, progress, chapter_summary=summary[:1200],
        story_state=json.dumps(story_state, ensure_ascii=False),
        rolling_plan=json.dumps(rolling_plan, ensure_ascii=False) if rolling_plan else None,
        discard_following=bool(values.get("discard_following_chapters", False)),
    )


async def _chapter_progress(
    repository: Any,
    tenant_id: str,
    novel_id: str,
    state: NovelAgentState,
    chapter: dict[str, Any],
    completed: int,
    percentage: float,
    is_completed: bool,
) -> Progress:
    fields: dict[str, Any] = {
        "current_chapter": completed,
        "total_chapters": _total_chapters(state.get("total_outline")),
        "percentage": percentage,
        "status": "completed" if is_completed else "writing",
    }
    finder = getattr(repository, "find_by_id", None)
    novel = await finder(tenant_id, novel_id) if callable(finder) else None
    previous = novel.progress if novel is not None else None
    raw_plan = state.get("novel_plan")
    if not isinstance(raw_plan, dict) or not raw_plan:
        return Progress(**fields)
    plan = NovelPlan.from_dict(raw_plan)
    prior_words = int(getattr(previous, "completed_words", 0) or 0)
    fields.update(_plan_progress_fields(plan, completed, prior_words + chapter["word_count"]))
    fields["drift_severity"] = "pending"
    return Progress(**fields)


def _plan_progress_fields(
    plan: NovelPlan, completed: int, completed_words: int
) -> dict[str, Any]:
    chapter = min(max(completed, 1), plan.scale.target_chapters)
    volume_index, volume = next(
        (index, item)
        for index, item in enumerate(plan.volumes, start=1)
        if item.start_chapter <= chapter <= item.end_chapter
    )
    volume_done = min(completed, volume.end_chapter) - volume.start_chapter + 1
    volume_total = volume.end_chapter - volume.start_chapter + 1
    return {
        "total_chapters": plan.scale.target_chapters,
        "target_words": plan.scale.target_total_words,
        "completed_words": completed_words,
        "word_percentage": completed_words / plan.scale.target_total_words * 100,
        "current_volume": volume_index,
        "total_volumes": len(plan.volumes),
        "volume_percentage": max(0, volume_done) / volume_total * 100,
        "plan_version": plan.version,
        "plan_status": "accepted",
    }


def _writing_command(
    chapter: dict[str, Any], percentage: float, is_completed: bool,
) -> Command[Literal["progress_check_node", "plan_reconciliation_node"]]:
    destination = (
        "plan_reconciliation_node"
        if settings.NOVEL_PLANNING_V1_ENABLED
        else "progress_check_node"
    )
    return Command(
        goto=destination,
        update={
            "completed_chapters": [chapter], "progress_percentage": percentage,
            "is_completed": is_completed,
            "current_chapter_index": chapter["chapter_index"] + 1,
            "last_persisted_chapter": chapter,
            "current_chapter_content": "", "reflection_issues": [], "user_decision": {},
            "memory_context": "", "scene_ledger": [], "revision_history": [],
        },
    )


async def persist_node(
    state: NovelAgentState, config: RunnableConfig,
) -> Command[Literal["progress_check_node", "plan_reconciliation_node"]]:
    """按当前是否存在章节正文选择设定或章节持久化路径。"""
    values = config["configurable"]
    content = str(state.get("current_chapter_content") or "")
    if not content:
        await _persist_setup(
            state, values.get("novel_repository"), values.get("tenant_id", ""),
            values.get("novel_id", ""),
        )
        return Command(goto="progress_check_node")
    index = int(state.get("current_chapter_index", 0) or 0)
    chapter = _completed_chapter(state, content, index)
    completed, percentage, is_completed = _progress(
        index, _total_chapters(state.get("total_outline")),
    )
    await _persist_chapter(state, config, chapter, completed, percentage, is_completed)
    emit_workflow_event(
        "chapter_persisted",
        {
            "chapter_id": chapter["id"], "chapter_index": index,
            "current_chapter": completed, "percentage": percentage,
            "is_completed": is_completed,
        },
        "persist_node",
    )
    logger.info("【持久化节点】章节与连续性状态已保存 | ch=%s, title=%s", index, chapter["title"])
    return _writing_command(chapter, percentage, is_completed)
