"""整书规划领域模型的确定性测试。"""

from dataclasses import replace
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import configure_mappers

from infrastructure.database.models import (
    NovelPlanExecutionModel,
    NovelPlanVersionModel,
)
from service.value_objects.novel_plan import (
    ChapterSlot,
    NovelPlan,
    NovelPlanValidationError,
    PlanExecution,
    ScaleContract,
    StoryArc,
    VolumePlan,
    allocate_word_targets,
    planning_options,
    validate_novel_plan,
    validate_plan_transition,
)


def _plan(chapters: int = 12, words: int = 50_400) -> NovelPlan:
    scale = ScaleContract("short", chapters, words)
    targets = allocate_word_targets(words, [1] * chapters)
    slots = [
        ChapterSlot(
            chapter_number=number,
            volume_id="vol-1",
            arc_ids=["main"],
            story_function=f"推进第 {number} 章",
            must_happen=["关键事件"],
            planned_state_delta="局势发生变化",
            target_words=targets[number - 1],
            setup_ids=["F001"] if number == 1 else [],
            payoff_ids=["F001"] if number == chapters else [],
        )
        for number in range(1, chapters + 1)
    ]
    return NovelPlan(
        scale=scale,
        ending_contract={"final_state": "主线闭合"},
        volumes=[
            VolumePlan(
                "vol-1", "第一卷", 1, chapters, words,
                opening_state="危机出现", midpoint_turn="认知逆转",
                climax="正面对抗", ending_state="阶段结束",
            )
        ],
        arcs=[StoryArc(
            "main", "main", 1, chapters, "解决危机",
            [{"chapter_number": max(1, chapters // 2), "change": "冲突升级"}],
            "危机解除", True,
        )],
        chapter_slots=slots,
    )


def test_planning_options_are_authoritative() -> None:
    options = planning_options()
    presets = {item["preset"]: item for item in options["presets"]}

    assert options["constraints"]["max_chapters"] == 200
    assert presets["short"]["target_chapters"] == 12
    assert presets["medium"]["target_volumes"] == 2
    assert presets["long"]["target_total_words"] == 336_000
    assert presets["epic"]["target_chapters"] == 150


@pytest.mark.parametrize("chapters", [1, 12, 80, 200])
def test_scale_contract_derives_volume_and_average(chapters: int) -> None:
    scale = ScaleContract("custom", chapters, chapters * 4200)

    assert scale.average_chapter_words == 4200
    assert scale.target_volumes == (chapters + 24) // 25


def test_scale_contract_rejects_impossible_size() -> None:
    with pytest.raises(NovelPlanValidationError, match="目标总字数"):
        ScaleContract("custom", 12, 20_000)

    with pytest.raises(NovelPlanValidationError, match="规模预设"):
        ScaleContract("unknown", 12, 50_400)

    with pytest.raises(NovelPlanValidationError, match="锁定窗口固定为 5 章"):
        ScaleContract("custom", 12, 50_400, lock_window=4)


def test_word_allocation_is_exact_bounded_and_deterministic() -> None:
    first = allocate_word_targets(50_403, [1, 2, 3] * 4)
    second = allocate_word_targets(50_403, [1, 2, 3] * 4)

    assert first == second
    assert sum(first) == 50_403
    assert all(3000 <= target <= 7000 for target in first)
    assert first[2] >= first[1] >= first[0]


def test_word_allocation_handles_capacity_saturation() -> None:
    targets = allocate_word_targets(20_000, [100, 1, 1])

    assert targets[0] == 7000
    assert sum(targets) == 20_000
    assert all(3000 <= target <= 7000 for target in targets)


def test_complete_plan_round_trip_and_validation() -> None:
    plan = _plan()
    restored = NovelPlan.from_dict(plan.to_dict())

    assert validate_novel_plan(restored) == []
    assert restored.to_dict() == plan.to_dict()
    restored.assert_valid()


def test_plan_execution_round_trip_and_validation() -> None:
    execution = PlanExecution(
        1, 1, "reconciled", 4200, {"fulfilled": True}, tactical_version=2
    )

    assert PlanExecution.from_dict(execution.to_dict()).to_dict() == execution.to_dict()
    with pytest.raises(NovelPlanValidationError, match="漂移等级"):
        PlanExecution(1, 1, "reconciled", 4200, {}, "unknown")
    with pytest.raises(NovelPlanValidationError, match="战术版本"):
        PlanExecution(1, 1, "reconciled", 4200, {}, tactical_version=0)


def test_plan_validation_reports_coverage_references_and_foreshadowing() -> None:
    plan = _plan()
    plan.chapter_slots.pop()
    plan.chapter_slots[0].arc_ids = ["missing"]
    plan.chapter_slots[0].payoff_ids = ["UNKNOWN"]

    errors = validate_novel_plan(plan)

    assert any("完整覆盖" in error for error in errors)
    assert any("不存在的剧情弧" in error for error in errors)
    assert any("没有对应伏笔" in error for error in errors)


def test_plan_validation_requires_final_core_arc_and_later_payoff() -> None:
    plan = _plan()
    plan.arcs[0].end_chapter -= 1
    plan.chapter_slots[-1].arc_ids = []
    plan.chapter_slots[0].payoff_ids = ["F001"]

    errors = validate_novel_plan(plan)

    assert any("核心剧情弧必须在最终章闭合" in error for error in errors)
    assert any("回收早于埋设" in error for error in errors)


def test_transition_preserves_completed_and_lock_window() -> None:
    previous = _plan()
    candidate = NovelPlan.from_dict(previous.to_dict())
    candidate.chapter_slots[6] = replace(
        candidate.chapter_slots[6], story_function="不允许修改"
    )

    assert validate_plan_transition(previous, candidate, completed_chapters=2)
    assert validate_plan_transition(previous, candidate, completed_chapters=1) == []


def test_plan_tables_keep_tenant_version_and_execution_constraints() -> None:
    configure_mappers()
    version_table = NovelPlanVersionModel.__table__
    execution_table = NovelPlanExecutionModel.__table__
    version_uniques = {
        constraint.name
        for constraint in version_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    execution_constraints = {
        constraint.name
        for constraint in execution_table.constraints
        if isinstance(constraint, (CheckConstraint, ForeignKeyConstraint, UniqueConstraint))
    }

    assert "uq_plan_versions_version" in version_uniques
    assert "uq_plan_executions_chapter" in execution_constraints
    assert "fk_plan_executions_plan_version" in execution_constraints
    assert "ck_plan_execution_drift" in execution_constraints


class _MigrationRecorder:
    def __init__(self) -> None:
        self.tables: dict[str, tuple] = {}
        self.indexes: dict[str, tuple[str, tuple[str, ...]]] = {}

    def create_table(self, name: str, *items) -> None:
        self.tables[name] = items

    def create_index(self, name: str, table: str, columns: list[str]) -> None:
        self.indexes[name] = (table, tuple(columns))

    def drop_index(self, name: str, table_name: str) -> None:
        pass

    def drop_table(self, name: str) -> None:
        pass


def _migration_recorder() -> _MigrationRecorder:
    path = Path(__file__).parents[1] / "alembic/versions/0005_novel_planning.py"
    spec = spec_from_file_location("novel_planning_migration", path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    recorder = _MigrationRecorder()
    migration.op = recorder
    migration.upgrade()
    return recorder


def _named_schema_items(items: tuple) -> set[str]:
    schema_types = (CheckConstraint, ForeignKeyConstraint, UniqueConstraint)
    return {
        item.name
        for item in items
        if isinstance(item, schema_types) and item.name is not None
    }


def test_migration_matches_planning_orm_metadata() -> None:
    recorder = _migration_recorder()
    models = {
        "novel_plan_versions": NovelPlanVersionModel.__table__,
        "novel_plan_executions": NovelPlanExecutionModel.__table__,
    }

    for name, table in models.items():
        migration_items = recorder.tables[name]
        migration_columns = {
            item.name for item in migration_items if isinstance(item, Column)
        }
        model_columns = set(table.columns.keys())
        model_constraints = _named_schema_items(tuple(table.constraints))
        if name == "novel_plan_versions":
            model_columns.remove("idempotency_key")
            model_constraints -= {
                "ck_plan_versions_idempotency_key",
                "uq_plan_versions_idempotency",
            }
        if name == "novel_plan_executions":
            model_columns.remove("tactical_version")
            model_constraints -= {
                "ck_plan_execution_tactical_version",
                "fk_plan_executions_tactical_version",
            }
        assert migration_columns == model_columns
        migration_defaults = {
            item.name: str(item.server_default.arg)
            for item in migration_items
            if isinstance(item, Column) and item.server_default is not None
        }
        model_defaults = {
            column.name: str(column.server_default.arg)
            for column in table.columns
            if column.server_default is not None
        }
        assert migration_defaults == model_defaults
        assert _named_schema_items(migration_items) == model_constraints
        model_indexes = {index.name for index in table.indexes if isinstance(index, Index)}
        migration_indexes = {
            key for key, value in recorder.indexes.items() if value[0] == name
        }
        assert migration_indexes == model_indexes
