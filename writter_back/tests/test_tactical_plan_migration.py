"""0006 战术规划、整书计划幂等迁移与 ORM 元数据契约。"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

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
    NovelTacticalPlanVersionModel,
    TenantModel,
)


class _MigrationRecorder:
    def __init__(self) -> None:
        self.tables: dict[str, tuple] = {}
        self.indexes: set[tuple[str, str]] = set()
        self.added: list[tuple[str, object]] = []
        self.foreign_keys: set[str] = set()
        self.uniques: set[str] = set()
        self.checks: set[str] = set()
        self.dropped: list[tuple[str, str]] = []

    def create_table(self, name: str, *items) -> None:
        self.tables[name] = items

    def create_index(self, name: str, table: str, _columns: list[str]) -> None:
        self.indexes.add((name, table))

    def add_column(self, table: str, column) -> None:
        self.added.append((table, column))

    def create_foreign_key(self, name: str, *_args, **_kwargs) -> None:
        self.foreign_keys.add(name)

    def create_unique_constraint(self, name: str, *_args) -> None:
        self.uniques.add(name)

    def create_check_constraint(self, name: str, *_args) -> None:
        self.checks.add(name)

    def drop_constraint(self, name: str, table: str, **_kwargs) -> None:
        self.dropped.append(("constraint", f"{table}:{name}"))

    def drop_column(self, table: str, name: str) -> None:
        self.dropped.append(("column", f"{table}:{name}"))

    def drop_index(self, name: str, **_kwargs) -> None:
        self.dropped.append(("index", name))

    def drop_table(self, name: str) -> None:
        self.dropped.append(("table", name))


def _migration():
    path = Path(__file__).parents[1] / "alembic/versions/0006_tactical_planning.py"
    spec = spec_from_file_location("tactical_planning_migration", path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _constraint_names(table) -> set[str]:
    supported = (CheckConstraint, ForeignKeyConstraint, UniqueConstraint)
    return {
        item.name for item in table.constraints
        if isinstance(item, supported) and item.name
    }


def test_tactical_orm_keeps_tenant_and_composite_constraints() -> None:
    configure_mappers()
    tactical = NovelTacticalPlanVersionModel.__table__
    execution = NovelPlanExecutionModel.__table__
    plan = NovelPlanVersionModel.__table__

    assert "novel_planning_v1_enabled" in TenantModel.__table__.columns
    assert str(TenantModel.novel_planning_v1_enabled.server_default.arg) == "false"
    assert {
        "uq_tactical_versions_version",
        "uq_tactical_versions_idempotency",
        "fk_tactical_versions_plan_version",
        "ck_tactical_versions_window",
        "ck_tactical_versions_idempotency_key",
    } <= _constraint_names(tactical)
    assert "idempotency_key" in tactical.columns
    assert "tactical_version" in execution.columns
    assert "fk_plan_executions_tactical_version" in _constraint_names(execution)
    assert "ck_plan_execution_tactical_version" in _constraint_names(execution)
    assert "idempotency_key" in plan.columns
    assert plan.c.idempotency_key.nullable is True
    assert {
        "uq_plan_versions_idempotency",
        "ck_plan_versions_idempotency_key",
    } <= _constraint_names(plan)


def test_0006_upgrade_and_downgrade_cover_every_schema_change() -> None:
    migration = _migration()
    recorder = _MigrationRecorder()
    migration.op = recorder

    migration.upgrade()
    migration.downgrade()

    assert migration.revision == "0006_tactical_planning"
    assert migration.down_revision == "0005_novel_planning"
    assert "novel_tactical_plan_versions" in recorder.tables
    added = {(table, column.name) for table, column in recorder.added}
    assert ("tenants", "novel_planning_v1_enabled") in added
    assert ("novel_plan_versions", "idempotency_key") in added
    assert ("novel_plan_executions", "tactical_version") in added
    assert "uq_plan_versions_idempotency" in recorder.uniques
    assert "ck_plan_versions_idempotency_key" in recorder.checks
    assert "fk_plan_executions_tactical_version" in recorder.foreign_keys
    assert "ck_plan_execution_tactical_version" in recorder.checks
    assert ("table", "novel_tactical_plan_versions") in recorder.dropped
    assert (
        "constraint",
        "novel_plan_versions:uq_plan_versions_idempotency",
    ) in recorder.dropped
    assert (
        "constraint",
        "novel_plan_versions:ck_plan_versions_idempotency_key",
    ) in recorder.dropped
    assert ("column", "novel_plan_versions:idempotency_key") in recorder.dropped
    assert ("column", "tenants:novel_planning_v1_enabled") in recorder.dropped


def test_0006_tactical_table_matches_orm_metadata() -> None:
    migration = _migration()
    recorder = _MigrationRecorder()
    migration.op = recorder
    migration.upgrade()
    items = recorder.tables["novel_tactical_plan_versions"]
    table = NovelTacticalPlanVersionModel.__table__
    migration_columns = {
        item.name for item in items if isinstance(item, Column)
    }
    migration_defaults = {
        item.name: str(item.server_default.arg)
        for item in items
        if isinstance(item, Column) and item.server_default is not None
    }
    model_defaults = {
        column.name: str(column.server_default.arg)
        for column in table.columns if column.server_default is not None
    }
    migration_constraints = {
        item.name for item in items
        if isinstance(item, (CheckConstraint, ForeignKeyConstraint, UniqueConstraint))
        and item.name
    }
    model_indexes = {
        index.name for index in table.indexes if isinstance(index, Index)
    }

    assert migration_columns == set(table.columns.keys())
    assert migration_defaults == model_defaults
    assert migration_constraints == _constraint_names(table)
    assert model_indexes == {
        name for name, owner in recorder.indexes
        if owner == "novel_tactical_plan_versions"
    }


def test_0006_plan_idempotency_column_matches_orm_metadata() -> None:
    migration = _migration()
    recorder = _MigrationRecorder()
    migration.op = recorder
    migration.upgrade()
    columns = [
        column for table, column in recorder.added
        if table == "novel_plan_versions" and column.name == "idempotency_key"
    ]
    model_column = NovelPlanVersionModel.__table__.c.idempotency_key

    assert len(columns) == 1
    assert columns[0].nullable is model_column.nullable is True
    assert columns[0].type.length == model_column.type.length == 128
