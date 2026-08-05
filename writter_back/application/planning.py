"""整书规划的确定性组装、校验、上下文选择与漂移处理。"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Iterable

from service.value_objects.novel_plan import (
    ChapterSlot,
    NovelPlan,
    NovelPlanValidationError,
    ScaleContract,
    StoryArc,
    VolumePlan,
    allocate_word_targets,
    validate_plan_transition,
)


def scale_from_state(state: dict[str, Any]) -> ScaleContract:
    """从新契约或旧章节字段构造统一规模契约。"""
    raw = state.get("scale_contract")
    outline = state.get("total_outline")
    if not isinstance(raw, dict) and isinstance(outline, dict):
        raw = outline.get("scale")
    if isinstance(raw, dict) and raw:
        return ScaleContract.from_dict(raw)
    chapters = _legacy_chapter_target(state, outline)
    words = int(state.get("target_total_words", 0) or chapters * 4200)
    return ScaleContract("custom", chapters, words)


def _legacy_chapter_target(state: dict[str, Any], outline: Any) -> int:
    value = state.get("target_total_chapters")
    if not value and isinstance(outline, dict):
        value = outline.get("total_chapters")
    chapters = int(value or 0)
    if chapters < 1:
        raise NovelPlanValidationError(["缺少有效的全书章节目标"])
    return chapters


def validate_blueprint(
    raw: Any, scale: ScaleContract
) -> tuple[dict[str, Any], list[str]]:
    """校验模型生成的结局、分卷和剧情弧蓝图。"""
    if not isinstance(raw, dict):
        return {}, ["规划蓝图必须是 JSON 对象"]
    blueprint = _normalized_blueprint(raw)
    errors = _blueprint_volume_errors(blueprint["volumes"], scale)
    errors.extend(_blueprint_arc_errors(blueprint["arcs"], scale))
    if not blueprint["ending_contract"]:
        errors.append("必须提供可验证的结局契约")
    return blueprint, list(dict.fromkeys(errors))


def _normalized_blueprint(raw: dict[str, Any]) -> dict[str, Any]:
    volumes = [
        VolumePlan.from_dict(item)
        for item in raw.get("volumes", [])
        if isinstance(item, dict)
    ]
    arcs = [
        StoryArc.from_dict(item)
        for item in raw.get("arcs", [])
        if isinstance(item, dict)
    ]
    return {
        "ending_contract": dict(raw.get("ending_contract") or {}),
        "volumes": volumes,
        "arcs": arcs,
    }


def _blueprint_volume_errors(
    volumes: list[VolumePlan], scale: ScaleContract
) -> list[str]:
    errors: list[str] = []
    if len(volumes) != scale.target_volumes:
        errors.append(f"分卷数量必须精确为 {scale.target_volumes}")
    expected = 1
    seen: set[str] = set()
    for volume in sorted(volumes, key=lambda item: item.start_chapter):
        if not volume.volume_id or volume.volume_id in seen:
            errors.append("分卷 ID 不能为空且不得重复")
        seen.add(volume.volume_id)
        if volume.start_chapter != expected:
            errors.append("分卷必须连续覆盖，不得重叠或留空")
        if not volume.start_chapter <= volume.end_chapter <= scale.target_chapters:
            errors.append(f"分卷 {volume.volume_id} 的章节边界无效")
        if volume.end_chapter - volume.start_chapter + 1 > 25:
            errors.append(f"分卷 {volume.volume_id} 不得超过 25 章")
        if not all((
            volume.opening_state,
            volume.midpoint_turn,
            volume.climax,
            volume.ending_state,
        )):
            errors.append(f"分卷 {volume.volume_id} 缺少开场、中点、高潮或退场状态")
        expected = volume.end_chapter + 1
    if expected != scale.target_chapters + 1:
        errors.append("分卷必须完整覆盖全书章节")
    return errors


def _blueprint_arc_errors(
    arcs: list[StoryArc], scale: ScaleContract
) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for arc in arcs:
        if not arc.arc_id or arc.arc_id in seen:
            errors.append("剧情弧 ID 不能为空且不得重复")
        seen.add(arc.arc_id)
        if not 1 <= arc.start_chapter <= arc.end_chapter <= scale.target_chapters:
            errors.append(f"剧情弧 {arc.arc_id} 的范围无效")
        if not arc.arc_type or not arc.goal or not arc.resolution_condition:
            errors.append(f"剧情弧 {arc.arc_id} 缺少类型、目标或解决条件")
        if not arc.escalation_points:
            errors.append(f"剧情弧 {arc.arc_id} 缺少升级节点")
    if not any(arc.is_core and arc.end_chapter == scale.target_chapters for arc in arcs):
        errors.append("至少一条核心剧情弧必须在最终章闭合")
    return errors


def validate_volume_slots(
    raw: Any,
    volume: VolumePlan,
    arcs: list[StoryArc],
    detail_level: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """校验单卷批次输出，保留模型强度权重供确定性分配。"""
    values = raw.get("chapter_slots") if isinstance(raw, dict) else None
    slots = [dict(item) for item in values or [] if isinstance(item, dict)]
    expected = list(range(volume.start_chapter, volume.end_chapter + 1))
    actual = sorted(int(item.get("chapter_number", 0) or 0) for item in slots)
    errors = [] if actual == expected else ["本卷章节槽位必须唯一且完整"]
    arc_map = {arc.arc_id: arc for arc in arcs}
    for item in slots:
        errors.extend(_raw_slot_errors(item, volume, arc_map))
        item["volume_id"] = volume.volume_id
        item["detail_level"] = detail_level
    return slots, list(dict.fromkeys(errors))


def _raw_slot_errors(
    item: dict[str, Any], volume: VolumePlan, arcs: dict[str, StoryArc]
) -> list[str]:
    chapter = int(item.get("chapter_number", 0) or 0)
    errors: list[str] = []
    if not volume.start_chapter <= chapter <= volume.end_chapter:
        errors.append(f"第 {chapter} 章超出当前分卷")
    arc_ids = item.get("arc_ids") or []
    if not isinstance(arc_ids, list) or set(map(str, arc_ids)) - arcs.keys():
        errors.append(f"第 {chapter} 章引用了不存在的剧情弧")
    if any(not arcs[str(key)].start_chapter <= chapter <= arcs[str(key)].end_chapter for key in arc_ids if str(key) in arcs):
        errors.append(f"第 {chapter} 章引用了范围外的剧情弧")
    if not str(item.get("story_function") or "").strip():
        errors.append(f"第 {chapter} 章缺少章节功能")
    if not item.get("must_happen") or not str(item.get("planned_state_delta") or "").strip():
        errors.append(f"第 {chapter} 章缺少必发事件或状态变化")
    try:
        if float(item.get("intensity_weight", 0) or 0) <= 0:
            errors.append(f"第 {chapter} 章强度权重必须为正数")
    except (TypeError, ValueError):
        errors.append(f"第 {chapter} 章强度权重无效")
    return errors


def build_plan(
    generation: dict[str, Any], completed_chapters: int
) -> NovelPlan:
    """把全部批次结果组装为可持久化计划并执行最终校验。"""
    scale = ScaleContract.from_dict(generation["scale"])
    blueprint = generation["blueprint"]
    blueprint_volumes = [
        item if isinstance(item, VolumePlan) else VolumePlan.from_dict(item)
        for item in blueprint["volumes"]
    ]
    blueprint_arcs = [
        item if isinstance(item, StoryArc) else StoryArc.from_dict(item)
        for item in blueprint["arcs"]
    ]
    raw_slots = sorted(generation["chapter_slots"], key=lambda item: item["chapter_number"])
    protected = _protected_targets(generation, completed_chapters)
    targets = _allocate_with_protected(scale.target_total_words, raw_slots, protected)
    slots = _materialize_slots(raw_slots, targets, generation, completed_chapters)
    volumes = _budgeted_volumes(blueprint_volumes, slots)
    plan = NovelPlan(
        scale=scale,
        ending_contract=dict(blueprint["ending_contract"]),
        volumes=volumes,
        arcs=blueprint_arcs,
        chapter_slots=slots,
        source=str(generation.get("source") or "initial"),
    )
    plan.assert_valid()
    _assert_transition(generation, plan, completed_chapters)
    return plan


def _protected_targets(
    generation: dict[str, Any], completed_chapters: int
) -> dict[int, int]:
    previous = generation.get("previous_plan")
    if not isinstance(previous, dict):
        return {}
    plan = NovelPlan.from_dict(previous)
    if generation.get("preserve_all_word_targets"):
        return {slot.chapter_number: slot.target_words for slot in plan.chapter_slots}
    locked = min(plan.scale.target_chapters, completed_chapters + plan.scale.lock_window)
    return {
        slot.chapter_number: slot.target_words
        for slot in plan.chapter_slots
        if slot.chapter_number <= locked
    }


def _allocate_with_protected(
    total_words: int,
    raw_slots: list[dict[str, Any]],
    protected: dict[int, int],
) -> list[int]:
    targets = [0] * len(raw_slots)
    free_indexes: list[int] = []
    for index, raw in enumerate(raw_slots):
        chapter = int(raw["chapter_number"])
        if chapter in protected:
            targets[index] = protected[chapter]
        else:
            free_indexes.append(index)
    free_total = total_words - sum(targets)
    weights = [float(raw_slots[index].get("intensity_weight", 1)) for index in free_indexes]
    try:
        allocated = allocate_word_targets(free_total, weights) if free_indexes else []
    except ValueError as exc:
        raise NovelPlanValidationError(
            ["锁定章节后剩余目标字数无法在单章上下限内分配"]
        ) from exc
    for index, target in zip(free_indexes, allocated, strict=True):
        targets[index] = target
    if sum(targets) != total_words:
        raise NovelPlanValidationError(["锁定章节后目标总字数无法闭合"])
    return targets


def _materialize_slots(
    raw_slots: list[dict[str, Any]],
    targets: list[int],
    generation: dict[str, Any],
    completed_chapters: int,
) -> list[ChapterSlot]:
    legacy = {int(item["chapter_number"]): item for item in generation.get("legacy_chapters", [])}
    previous = _previous_slot_map(generation)
    locked = _locked_through(generation, completed_chapters)
    slots: list[ChapterSlot] = []
    for raw, target in zip(raw_slots, targets, strict=True):
        payload = {**raw, "target_words": target}
        chapter = int(payload["chapter_number"])
        if chapter <= locked and chapter in previous:
            slots.append(previous[chapter])
            continue
        if chapter in legacy:
            payload = _legacy_slot_payload(payload, legacy[chapter])
        slots.append(ChapterSlot.from_dict(payload))
    return slots


def _previous_slot_map(generation: dict[str, Any]) -> dict[int, ChapterSlot]:
    previous = generation.get("previous_plan")
    if not isinstance(previous, dict):
        return {}
    return {slot.chapter_number: slot for slot in NovelPlan.from_dict(previous).chapter_slots}


def _locked_through(generation: dict[str, Any], completed: int) -> int:
    previous = generation.get("previous_plan")
    if not isinstance(previous, dict):
        return completed
    window = NovelPlan.from_dict(previous).scale.lock_window
    return completed + window


def _legacy_slot_payload(
    payload: dict[str, Any], legacy: dict[str, Any]
) -> dict[str, Any]:
    outline = legacy.get("outline") if isinstance(legacy.get("outline"), dict) else {}
    return {
        **payload,
        "story_function": outline.get("chapter_goal") or legacy.get("title") or payload["story_function"],
        "must_happen": outline.get("key_events") or payload["must_happen"],
        "planned_state_delta": outline.get("state_delta") or payload["planned_state_delta"],
        "detail_level": "detailed",
        "status": "completed",
    }


def _budgeted_volumes(
    volumes: list[VolumePlan], slots: list[ChapterSlot]
) -> list[VolumePlan]:
    totals = {volume.volume_id: 0 for volume in volumes}
    for slot in slots:
        totals[slot.volume_id] += slot.target_words
    return [VolumePlan(**{**asdict(volume), "target_words": totals[volume.volume_id]}) for volume in volumes]


def _assert_transition(
    generation: dict[str, Any], plan: NovelPlan, completed: int
) -> None:
    previous = generation.get("previous_plan")
    if not isinstance(previous, dict):
        return
    errors = validate_plan_transition(NovelPlan.from_dict(previous), plan, completed)
    if errors:
        raise NovelPlanValidationError(errors)


def generation_context(slots: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """为下一卷生成提取有限的相邻槽位与未回收伏笔。"""
    values = list(slots)
    setup: set[str] = set()
    paid: set[str] = set()
    for slot in values:
        setup.update(map(str, slot.get("setup_ids") or []))
        paid.update(map(str, slot.get("payoff_ids") or []))
    return {"recent_slots": values[-4:], "unresolved_setup_ids": sorted(setup - paid)}


def select_plan_context(plan: NovelPlan, chapter_number: int) -> dict[str, Any]:
    """只选择当前章、当前卷、活跃剧情弧、未来四章与未回收伏笔。"""
    slot_map = {slot.chapter_number: slot for slot in plan.chapter_slots}
    current = slot_map.get(chapter_number)
    if current is None:
        return {}
    volume = next(item for item in plan.volumes if item.volume_id == current.volume_id)
    arcs = [arc for arc in plan.arcs if arc.start_chapter <= chapter_number <= arc.end_chapter]
    future = [slot_map[number] for number in range(chapter_number + 1, min(chapter_number + 4, plan.scale.target_chapters) + 1)]
    context = {
        "plan_version": plan.version,
        "current_slot": asdict(current),
        "current_volume": asdict(volume),
        "active_arcs": [asdict(arc) for arc in arcs],
        "future_slots": [asdict(slot) for slot in future],
        "unresolved_setup_ids": _unresolved_before(plan, chapter_number),
    }
    if chapter_number == plan.scale.target_chapters:
        context["ending_contract"] = dict(plan.ending_contract)
    return context


def _unresolved_before(plan: NovelPlan, chapter_number: int) -> list[str]:
    setup: set[str] = set()
    paid: set[str] = set()
    for slot in plan.chapter_slots:
        if slot.chapter_number > chapter_number:
            break
        setup.update(slot.setup_ids)
        paid.update(slot.payoff_ids)
    return sorted(setup - paid)


def classify_drift(
    fulfillment: dict[str, Any], actual_words: int, target_words: int
) -> str:
    """按结构违约优先级确定 none/minor/major。"""
    major_flags = (
        "ending_contract_breached",
        "volume_boundary_breached",
        "core_arc_breached",
        "scale_change_required",
    )
    if any(fulfillment.get(key) is True for key in major_flags):
        return "major"
    deviation = abs(actual_words - target_words) / max(target_words, 1)
    delayed = fulfillment.get("deferred_items") or fulfillment.get("missing_required_events")
    tactical = fulfillment.get("tactical_fulfillment")
    tactical_drift = (
        tactical.get("deviations")
        if isinstance(tactical, dict)
        else None
    )
    return "minor" if deviation > 0.2 or delayed or tactical_drift else "none"


def plan_diff(previous: NovelPlan | None, candidate: NovelPlan) -> dict[str, Any]:
    """生成供审核 UI 使用的结构化计划差异。"""
    if previous is None:
        return {
            "kind": "initial",
            "scale": candidate.scale.to_dict(),
            "affected_chapters": [1, candidate.scale.target_chapters],
        }
    old_slots = {slot.chapter_number: asdict(slot) for slot in previous.chapter_slots}
    new_slots = {slot.chapter_number: asdict(slot) for slot in candidate.chapter_slots}
    affected = sorted(number for number in old_slots.keys() | new_slots.keys() if old_slots.get(number) != new_slots.get(number))
    return {
        "kind": "replan",
        "scale_changed": previous.scale.to_dict() != candidate.scale.to_dict(),
        "volume_boundaries_changed": _volume_boundaries(previous) != _volume_boundaries(candidate),
        "arc_ids_before": [arc.arc_id for arc in previous.arcs],
        "arc_ids_after": [arc.arc_id for arc in candidate.arcs],
        "affected_chapters": affected,
    }


def _volume_boundaries(plan: NovelPlan) -> list[tuple[int, int]]:
    return [(volume.start_chapter, volume.end_chapter) for volume in plan.volumes]


def reschedule_minor_drift(
    plan: NovelPlan, completed_chapter: int, fulfillment: dict[str, Any]
) -> NovelPlan | None:
    """把非结构性延后事件移到锁定窗口外首个可用槽位。"""
    deferred = [str(item) for item in fulfillment.get("deferred_items") or [] if str(item).strip()]
    if not deferred:
        return None
    payload = plan.to_dict()
    locked = completed_chapter + plan.scale.lock_window
    target = next((slot for slot in payload["chapter_slots"] if slot["chapter_number"] > locked), None)
    if target is None:
        return None
    target["must_happen"] = list(dict.fromkeys([*target["must_happen"], *deferred]))
    payload.update(version=0, source="automatic_drift", created_at=datetime.now(timezone.utc).isoformat())
    candidate = NovelPlan.from_dict(payload)
    candidate.assert_valid()
    errors = validate_plan_transition(plan, candidate, completed_chapter)
    if errors:
        raise NovelPlanValidationError(errors)
    return candidate
