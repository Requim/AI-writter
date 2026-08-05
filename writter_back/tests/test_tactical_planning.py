"""滚动战术计划的领域规则与确定性应用服务。"""

from dataclasses import replace

import pytest

from application.tactical_planning import (
    execution_contract_requirements,
    hydrate_tactical_window,
    select_tactical_window_range,
    tactical_window_status,
    validate_chapter_execution_contract,
    validate_tactical_window,
)
from service.value_objects.novel_plan import (
    ChapterSlot,
    NovelPlan,
    ScaleContract,
    StoryArc,
    VolumePlan,
)
from service.value_objects.tactical_plan import (
    ChapterExecutionContract,
    TacticalBeat,
    TacticalPlanValidationError,
    TacticalWindow,
    obligation_id,
)


def _volumes(chapters: int) -> list[VolumePlan]:
    volumes: list[VolumePlan] = []
    for index, start in enumerate(range(1, chapters + 1, 25), start=1):
        end = min(start + 24, chapters)
        volumes.append(VolumePlan(
            f"vol-{index}", f"第 {index} 卷", start, end,
            (end - start + 1) * 4200, "开场", "中点", "高潮", "退场",
        ))
    return volumes


def _plan(
    chapters: int = 12, escalations: list[int] | None = None,
    payoffs: set[int] | None = None,
) -> NovelPlan:
    payoff_chapters = payoffs or set()
    slots = [
        ChapterSlot(
            number, f"vol-{(number - 1) // 25 + 1}", ["main"],
            f"推进 {number}", ["事件甲", "事件乙"], "局势变化", 4200,
            setup_ids=["F1"] if number == 1 else [],
            payoff_ids=[f"F{number}"] if number in payoff_chapters else [],
        )
        for number in range(1, chapters + 1)
    ]
    arc = StoryArc(
        "main", "main", 1, chapters, "完成目标",
        [{"chapter_number": item, "change": "升级"}
         for item in (escalations or [chapters])],
        "目标完成", True,
    )
    return NovelPlan(
        ScaleContract("custom", chapters, chapters * 4200),
        {"final_state": "闭合"}, _volumes(chapters), [arc], slots,
        version=1,
    )


def _beat(chapter_number: int) -> TacticalBeat:
    return TacticalBeat(
        chapter_number, f"ch{chapter_number}", f"目标 {chapter_number}",
        "推进方法", "承接前章", "压力升级", "退出钩子", "张弛有度",
    )


def _window(
    plan: NovelPlan, current: int = 1, *, version: int = 1,
    end_chapter: int | None = None,
) -> TacticalWindow:
    start, selected_end = select_tactical_window_range(plan, current)
    end = end_chapter if end_chapter is not None else selected_end
    volume_id = plan.chapter_slots[start - 1].volume_id
    return TacticalWindow(
        plan.version, current - 1, start, end, volume_id, "推进近期冲突",
        [_beat(number) for number in range(start, end + 1)], version=version,
    )


def test_obligation_ids_and_value_objects_round_trip() -> None:
    plan = _plan()
    window = _window(plan)
    contract = ChapterExecutionContract(
        1, 1, 1, {obligation_id(1, 1): 1}, {"ch1:state_delta": 2}, {},
    )

    assert obligation_id(3, 2) == "ch3:must:2"
    assert TacticalWindow.from_dict(window.to_dict()).to_dict() == window.to_dict()
    assert ChapterExecutionContract.from_dict(
        contract.to_dict()
    ).to_dict() == contract.to_dict()


def test_tactical_beat_rejects_upper_contract_overwrite() -> None:
    payload = _beat(1).to_dict()
    payload["must_happen"] = ["模型试图改写"]

    with pytest.raises(TacticalPlanValidationError, match="不得改写"):
        TacticalBeat.from_dict(payload)


def test_tactical_shape_reports_invalid_beat_without_raising() -> None:
    plan = _plan()
    window = replace(_window(plan), beats=[replace(_beat(1), chapter_number=0)])

    errors = validate_tactical_window(window, plan, 1, 0)

    assert any("章节号" in error for error in errors)


def test_range_defaults_to_five_and_uses_nearest_milestone() -> None:
    assert select_tactical_window_range(_plan(escalations=[10]), 1) == (1, 5)
    plan = _plan(escalations=[6, 4], payoffs={3})

    assert select_tactical_window_range(plan, 1) == (1, 3)


def test_range_can_expand_to_seven_and_never_crosses_volume() -> None:
    assert select_tactical_window_range(_plan(escalations=[7]), 1) == (1, 7)
    plan = _plan(chapters=30, escalations=[30])

    assert select_tactical_window_range(plan, 24) == (24, 25)
    assert select_tactical_window_range(plan, 25) == (25, 25)
    assert select_tactical_window_range(plan, 26) == (26, 30)


def test_window_validation_and_status_follow_all_revision_inputs() -> None:
    plan = _plan(escalations=[10])
    window = _window(plan)

    assert validate_tactical_window(window, plan, 1, 0) == []
    assert tactical_window_status(window, plan, 1, 0) == "active"
    assert tactical_window_status(window, plan, 2, 1) == "stale"
    assert tactical_window_status(None, plan, 1, 0) == "missing"
    assert tactical_window_status(window, replace(plan, version=2), 1, 0) == "stale"


def test_window_validation_rejects_non_deterministic_range() -> None:
    plan = _plan(escalations=[10])
    window = _window(plan, end_chapter=6)

    errors = validate_tactical_window(window, plan, 1, 0)

    assert any("里程碑规则" in error for error in errors)


def test_hydration_restores_all_immutable_slot_contracts() -> None:
    plan = _plan(escalations=[10])
    payload = hydrate_tactical_window(_window(plan), plan)
    contract = payload["beats"][0]["slot_contract"]

    assert contract["target_words"] == 4200
    assert contract["obligations"] == [
        {"id": "ch1:must:1", "event": "事件甲"},
        {"id": "ch1:must:2", "event": "事件乙"},
    ]
    assert contract["planned_state_delta"]["id"] == "ch1:state_delta"
    assert contract["setup_requirements"][0]["id"] == "ch1:setup:F1"


def _valid_execution(plan: NovelPlan, window: TacticalWindow):
    required = execution_contract_requirements(plan.chapter_slots[0])
    return ChapterExecutionContract(
        plan.version,
        window.version,
        1,
        {key: index for index, key in enumerate(
            sorted(required["obligation_coverage"]), start=1
        )},
        {key: 2 for key in required["state_delta_coverage"]},
        {key: 3 for key in required["setup_payoff_coverage"]},
    )


def test_execution_contract_requires_every_obligation_and_real_scene() -> None:
    plan = _plan(escalations=[10])
    window = _window(plan)
    contract = _valid_execution(plan, window)

    assert validate_chapter_execution_contract(
        contract, plan, window, [1, 2, 3]
    ) == []
    missing = dict(contract.obligation_coverage)
    missing.pop("ch1:must:2")
    invalid = replace(contract, obligation_coverage=missing,
                      state_delta_coverage={"ch1:state_delta": 9})
    errors = validate_chapter_execution_contract(
        invalid, plan, window, [1, 2, 3]
    )

    assert any("缺少" in error for error in errors)
    assert any("不存在的场景" in error for error in errors)
