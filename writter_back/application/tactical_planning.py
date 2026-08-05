"""滚动战术窗口的确定性选择、装配与校验。"""

from __future__ import annotations

from typing import Any, Iterable, Literal

from service.value_objects.novel_plan import ChapterSlot, NovelPlan, VolumePlan
from service.value_objects.tactical_plan import (
    ChapterExecutionContract,
    TacticalWindow,
    obligation_id,
    payoff_coverage_id,
    setup_coverage_id,
    state_delta_id,
    validate_execution_contract_shape,
    validate_tactical_window_shape,
)


def _volume_for_chapter(plan: NovelPlan, chapter_number: int) -> VolumePlan:
    for volume in plan.volumes:
        if volume.start_chapter <= chapter_number <= volume.end_chapter:
            return volume
    raise ValueError(f"第 {chapter_number} 章不属于任何分卷")


def _arc_milestones(plan: NovelPlan, start: int, end: int) -> set[int]:
    markers: set[int] = set()
    for arc in plan.arcs:
        if start <= arc.end_chapter <= end:
            markers.add(arc.end_chapter)
        for point in arc.escalation_points:
            chapter = int(point.get("chapter_number", 0) or 0)
            if start <= chapter <= end:
                markers.add(chapter)
    return markers


def _slot_milestones(plan: NovelPlan, start: int, end: int) -> set[int]:
    return {
        slot.chapter_number
        for slot in plan.chapter_slots
        if start <= slot.chapter_number <= end and slot.payoff_ids
    }


def _milestones(
    plan: NovelPlan, volume: VolumePlan, current_chapter: int
) -> set[int]:
    start = current_chapter + 2
    end = min(current_chapter + 6, volume.end_chapter)
    if start > end:
        return set()
    markers = _arc_milestones(plan, start, end)
    markers.update(_slot_milestones(plan, start, end))
    markers.update({volume.end_chapter, plan.scale.target_chapters})
    return {chapter for chapter in markers if start <= chapter <= end}


def select_tactical_window_range(
    plan: NovelPlan, current_chapter: int
) -> tuple[int, int]:
    """选择默认 5 章、遇到最近结构里程碑时调整为 3 到 7 章。"""
    if not 1 <= current_chapter <= plan.scale.target_chapters:
        raise ValueError("当前章节超出整书计划范围")
    volume = _volume_for_chapter(plan, current_chapter)
    markers = _milestones(plan, volume, current_chapter)
    fallback = min(current_chapter + 4, volume.end_chapter)
    return current_chapter, min(markers) if markers else fallback


def _obligations(slot: ChapterSlot) -> list[dict[str, str]]:
    return [
        {"id": obligation_id(slot.chapter_number, index), "event": event}
        for index, event in enumerate(slot.must_happen, start=1)
    ]


def chapter_slot_contract(slot: ChapterSlot) -> dict[str, Any]:
    """装配模型不可改写的战略与战役层章节契约。"""
    chapter = slot.chapter_number
    return {
        "chapter_number": chapter,
        "volume_id": slot.volume_id,
        "arc_ids": list(slot.arc_ids),
        "story_function": slot.story_function,
        "obligations": _obligations(slot),
        "planned_state_delta": {
            "id": state_delta_id(chapter),
            "value": slot.planned_state_delta,
        },
        "setup_requirements": [
            {"id": setup_coverage_id(chapter, item), "setup_id": item}
            for item in slot.setup_ids
        ],
        "payoff_requirements": [
            {"id": payoff_coverage_id(chapter, item), "payoff_id": item}
            for item in slot.payoff_ids
        ],
        "target_words": slot.target_words,
        "detail_level": slot.detail_level,
        "status": slot.status,
    }


def hydrate_tactical_window(
    window: TacticalWindow, plan: NovelPlan
) -> dict[str, Any]:
    slots = {slot.chapter_number: slot for slot in plan.chapter_slots}
    payload = window.to_dict()
    payload["beats"] = [
        {
            "tactical": beat.to_dict(),
            "slot_contract": (
                chapter_slot_contract(slots[beat.chapter_number])
                if beat.chapter_number in slots else None
            ),
        }
        for beat in window.beats
    ]
    return payload


assemble_tactical_window = hydrate_tactical_window


def _plan_link_errors(window: TacticalWindow, plan: NovelPlan) -> list[str]:
    errors: list[str] = []
    if window.novel_plan_version != plan.version:
        errors.append("战术窗口关联的整书计划版本已过期")
    try:
        volume = _volume_for_chapter(plan, window.start_chapter)
    except ValueError as exc:
        return [str(exc)]
    if window.volume_id != volume.volume_id:
        errors.append("战术窗口所属卷与整书计划不一致")
    if window.end_chapter > volume.end_chapter:
        errors.append("战术窗口不得跨卷")
    return errors


def _slot_reference_errors(window: TacticalWindow, plan: NovelPlan) -> list[str]:
    slots = {slot.chapter_number: slot for slot in plan.chapter_slots}
    errors: list[str] = []
    for beat in window.beats:
        slot = slots.get(beat.chapter_number)
        if slot is None:
            errors.append(f"第 {beat.chapter_number} 章槽位不存在")
        elif slot.volume_id != window.volume_id:
            errors.append(f"第 {beat.chapter_number} 章槽位不属于战术窗口分卷")
    return errors


def validate_tactical_window(
    window: TacticalWindow,
    plan: NovelPlan,
    current_chapter: int,
    story_state_revision: int,
) -> list[str]:
    """校验窗口形状、版本、确定性范围与所有上层引用。"""
    errors = validate_tactical_window_shape(window)
    if window.story_state_revision != story_state_revision:
        errors.append("战术窗口关联的故事状态已过期")
    try:
        expected = select_tactical_window_range(plan, current_chapter)
    except ValueError as exc:
        errors.append(str(exc))
        expected = None
    if expected and (window.start_chapter, window.end_chapter) != expected:
        errors.append("战术窗口范围不符合确定性里程碑规则")
    errors.extend(_plan_link_errors(window, plan))
    errors.extend(_slot_reference_errors(window, plan))
    return list(dict.fromkeys(errors))


def tactical_window_status(
    window: TacticalWindow | None,
    plan: NovelPlan,
    current_chapter: int,
    story_state_revision: int,
) -> Literal["active", "stale", "missing"]:
    if window is None:
        return "missing"
    errors = validate_tactical_window(
        window, plan, current_chapter, story_state_revision
    )
    return "stale" if errors else "active"


def execution_contract_requirements(slot: ChapterSlot) -> dict[str, set[str]]:
    chapter = slot.chapter_number
    return {
        "obligation_coverage": {
            obligation_id(chapter, index)
            for index in range(1, len(slot.must_happen) + 1)
        },
        "state_delta_coverage": {state_delta_id(chapter)},
        "setup_payoff_coverage": {
            *[setup_coverage_id(chapter, item) for item in slot.setup_ids],
            *[payoff_coverage_id(chapter, item) for item in slot.payoff_ids],
        },
    }


def _coverage_key_errors(
    name: str, actual: dict[str, int], required: set[str]
) -> list[str]:
    missing = sorted(required - actual.keys())
    unexpected = sorted(actual.keys() - required)
    errors = [f"{name}缺少：{missing}"] if missing else []
    if unexpected:
        errors.append(f"{name}包含未声明项：{unexpected}")
    return errors


def _contract_reference_errors(
    contract: ChapterExecutionContract, plan: NovelPlan, window: TacticalWindow
) -> list[str]:
    errors: list[str] = []
    if contract.plan_version != plan.version:
        errors.append("执行契约关联的整书计划版本不一致")
    if contract.tactical_version != window.version:
        errors.append("执行契约关联的战术版本不一致")
    if contract.chapter_number != window.start_chapter:
        errors.append("执行契约必须对应战术窗口当前章")
    if not any(
        beat.chapter_number == contract.chapter_number for beat in window.beats
    ):
        errors.append("执行契约章节不在战术窗口中")
    return errors


def _scene_reference_errors(
    contract: ChapterExecutionContract, scene_indices: Iterable[int]
) -> list[str]:
    valid = {int(scene_index) for scene_index in scene_indices if int(scene_index) >= 1}
    referenced = {
        *contract.obligation_coverage.values(),
        *contract.state_delta_coverage.values(),
        *contract.setup_payoff_coverage.values(),
    }
    invalid = sorted(referenced - valid)
    return [f"执行覆盖引用了不存在的场景：{invalid}"] if invalid else []


def validate_chapter_execution_contract(
    contract: ChapterExecutionContract,
    plan: NovelPlan,
    window: TacticalWindow,
    scene_indices: Iterable[int],
) -> list[str]:
    """正文生成前验证当前章所有义务均映射到真实场景。"""
    errors = validate_execution_contract_shape(contract)
    errors.extend(_contract_reference_errors(contract, plan, window))
    slots = {slot.chapter_number: slot for slot in plan.chapter_slots}
    slot = slots.get(contract.chapter_number)
    if slot is None:
        return list(dict.fromkeys([*errors, "执行契约章节槽位不存在"]))
    required = execution_contract_requirements(slot)
    errors.extend(_coverage_key_errors(
        "必发事件覆盖", contract.obligation_coverage,
        required["obligation_coverage"],
    ))
    errors.extend(_coverage_key_errors(
        "状态变化覆盖", contract.state_delta_coverage,
        required["state_delta_coverage"],
    ))
    errors.extend(_coverage_key_errors(
        "伏笔覆盖", contract.setup_payoff_coverage,
        required["setup_payoff_coverage"],
    ))
    errors.extend(_scene_reference_errors(contract, scene_indices))
    return list(dict.fromkeys(errors))
