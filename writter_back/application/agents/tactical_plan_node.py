"""Generate the bounded tactical layer used by Schema 5 chapter planning."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from application.errors import RetryableWorkflowError
from application.feature_policy import require_planning_v1
from application.prompts.tactical_plan_prompts import (
    TACTICAL_WINDOW_SCHEMA,
    build_tactical_window_prompt,
)
from application.schemas.agent_state import NovelAgentState
from application.streaming import emit_workflow_event
from application.tactical_planning import (
    chapter_slot_contract,
    select_tactical_window_range,
    tactical_window_status,
    validate_tactical_window,
)
from service.value_objects.novel_plan import NovelPlan
from service.value_objects.tactical_plan import TacticalWindow


def _plan(state: NovelAgentState) -> NovelPlan:
    value = state.get("novel_plan")
    if not isinstance(value, dict) or not value:
        raise RetryableWorkflowError("战术规划失败：缺少已接受的整书计划")
    return NovelPlan.from_dict(value)


def _window(value: Any) -> TacticalWindow | None:
    if isinstance(value, TacticalWindow):
        return value
    if not isinstance(value, dict) or not value:
        return None
    try:
        return TacticalWindow.from_dict(value)
    except (TypeError, ValueError):
        return None


async def _latest_window(config: RunnableConfig) -> TacticalWindow | None:
    values = config["configurable"]
    repository = values.get("novel_repository")
    getter = getattr(repository, "get_latest_tactical_plan", None)
    if not callable(getter):
        return None
    return await getter(values.get("tenant_id", ""), values.get("novel_id", ""))


def _planning_context(
    plan: NovelPlan, chapter: int
) -> tuple[int, int, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    start, end = select_tactical_window_range(plan, chapter)
    volume = next(
        item for item in plan.volumes
        if item.start_chapter <= chapter <= item.end_chapter
    )
    arcs = [
        asdict(arc) for arc in plan.arcs
        if arc.start_chapter <= end and arc.end_chapter >= start
    ]
    slots = [
        chapter_slot_contract(slot) for slot in plan.chapter_slots
        if start <= slot.chapter_number <= end
    ]
    return start, end, asdict(volume), arcs, slots


def _candidate(
    raw: Any,
    *,
    plan: NovelPlan,
    revision: int,
    start: int,
    end: int,
    volume_id: str,
    version: int,
    source: str,
) -> TacticalWindow:
    if not isinstance(raw, dict):
        raise ValueError("战术输出必须是 JSON 对象")
    return TacticalWindow.from_dict({
        "schema_version": 1,
        "version": version,
        "novel_plan_version": plan.version,
        "story_state_revision": revision,
        "source": source,
        "start_chapter": start,
        "end_chapter": end,
        "volume_id": volume_id,
        "window_objective": raw.get("window_objective"),
        "beats": raw.get("beats"),
    })


async def _generate_window(
    state: NovelAgentState,
    config: RunnableConfig,
    plan: NovelPlan,
    latest: TacticalWindow | None,
) -> TacticalWindow:
    chapter = int(state.get("current_chapter_index", 0) or 0) + 1
    revision = chapter - 1
    start, end, volume, arcs, slots = _planning_context(plan, chapter)
    llm = config["configurable"].get("llm_config", {}).get("llm_instance")
    if llm is None:
        raise RetryableWorkflowError("战术规划失败：LLM 不可用")
    expected = latest.version if latest else 0
    errors: list[str] = []
    for _attempt in range(3):
        prompt = build_tactical_window_prompt(
            total_outline=dict(state.get("total_outline") or {}),
            volume=volume,
            arcs=arcs,
            slot_contracts=slots,
            story_state=str(state.get("memory_context") or ""),
            start_chapter=start,
            end_chapter=end,
            validation_errors=errors,
            instruction=str(state.get("tactical_plan_feedback") or ""),
        )
        raw = await llm.structured_generate(
            prompt=prompt, schema=TACTICAL_WINDOW_SCHEMA, temperature=0.35,
        )
        try:
            candidate = _candidate(
                raw,
                plan=plan,
                revision=revision,
                start=start,
                end=end,
                volume_id=str(volume["volume_id"]),
                version=expected + 1,
                source="review_revision" if state.get("tactical_plan_feedback") else "chapter_refresh",
            )
            errors = validate_tactical_window(candidate, plan, chapter, revision)
        except (TypeError, ValueError) as exc:
            errors = [str(exc)]
        if not errors:
            return candidate
    raise RetryableWorkflowError("战术规划校验失败：" + "；".join(errors[:5]))


def tactical_window_diff(
    previous: TacticalWindow | None, candidate: TacticalWindow
) -> dict[str, Any]:
    if previous is None:
        return {"kind": "initial", "affected_chapters": list(range(
            candidate.start_chapter, candidate.end_chapter + 1
        ))}
    old = {beat.chapter_number: beat.to_dict() for beat in previous.beats}
    new = {beat.chapter_number: beat.to_dict() for beat in candidate.beats}
    affected = sorted(
        chapter for chapter in old.keys() | new.keys()
        if old.get(chapter) != new.get(chapter)
    )
    return {
        "kind": "refresh",
        "previous_version": previous.version,
        "window_changed": (
            previous.start_chapter, previous.end_chapter
        ) != (candidate.start_chapter, candidate.end_chapter),
        "affected_chapters": affected,
    }


async def tactical_plan_node(
    state: NovelAgentState, config: RunnableConfig
) -> Command[Literal["chapter_outline_node"]]:
    """Reuse an active accepted window or generate one bounded candidate."""
    await require_planning_v1(config)
    plan = _plan(state)
    chapter = int(state.get("current_chapter_index", 0) or 0) + 1
    revision = chapter - 1
    latest = await _latest_window(config)
    current = _window(state.get("tactical_window"))
    if (
        current
        and not state.get("story_state_needs_reconciliation")
        and tactical_window_status(current, plan, chapter, revision) == "active"
    ):
        return Command(goto="chapter_outline_node")
    if (
        latest
        and not state.get("tactical_plan_feedback")
        and not state.get("story_state_needs_reconciliation")
        and tactical_window_status(latest, plan, chapter, revision) == "active"
    ):
        return Command(goto="chapter_outline_node", update={
            "tactical_window": latest.to_dict(),
            "tactical_window_expected_version": latest.version,
            "tactical_window_persisted": True,
            "tactical_previous_window": latest.to_dict(),
        })
    emit_workflow_event(
        "status",
        {"status": "started", "message": f"正在规划第{chapter}章起的近期战术"},
        "tactical_plan_node",
    )
    candidate = await _generate_window(state, config, plan, latest)
    return Command(goto="chapter_outline_node", update={
        "tactical_window": candidate.to_dict(),
        "tactical_window_expected_version": latest.version if latest else 0,
        "tactical_window_persisted": False,
        "tactical_previous_window": latest.to_dict() if latest else None,
        "tactical_plan_feedback": None,
        "story_state_needs_reconciliation": False,
    })
