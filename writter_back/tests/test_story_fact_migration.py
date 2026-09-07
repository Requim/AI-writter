"""0006 到 0007 的真实迁移升降级；在独立测试库的事务临时 schema 内运行。"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa

from infrastructure.database.models import Base, NovelModel, TenantModel
from tests.database_safety import isolated_database_url
from tests.test_tactical_plan_migration import _MigrationRecorder, _constraint_names

FACT_TABLES = {"story_entities", "story_fact_versions", "story_fact_assertions"}


def _migration():
    path = Path(__file__).parents[1] / "alembic/versions/0007_story_facts.py"
    spec = spec_from_file_location("story_fact_migration", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_story_migration_matches_orm_contract():
    migration = _migration()
    recorder = _MigrationRecorder()
    migration.op = recorder
    migration.upgrade()
    assert migration.down_revision == "0006_tactical_planning"
    assert set(recorder.tables) == FACT_TABLES
    for name, items in recorder.tables.items():
        columns = {item.name: item for item in items if isinstance(item, sa.Column)}
        table = Base.metadata.tables[name]
        assert set(columns) == set(table.c.keys())
        assert {item.name for item in items if isinstance(item, (sa.UniqueConstraint, sa.CheckConstraint))} <= _constraint_names(table)
        assert {key: value.nullable for key, value in columns.items()} == {c.name: c.nullable for c in table.c}
    migration.downgrade()
    assert {name for kind, name in recorder.dropped if kind == "table"} == FACT_TABLES


def _seed_existing_novel(connection):
    tenant, novel = uuid4(), uuid4()
    connection.execute(TenantModel.__table__.insert().values(id=tenant, name="迁移验收", slug=str(tenant)))
    connection.execute(NovelModel.__table__.insert().values(id=novel, tenant_id=tenant, novel_type="suspense", title="保留原稿"))
    return novel


def test_upgrade_downgrade_preserves_existing_novels(repository):
    engine = sa.create_engine(isolated_database_url().replace("+asyncpg", "+psycopg2"))
    schema = "facts_migration_" + uuid4().hex
    try:
        with engine.connect() as connection, connection.begin() as transaction:
            connection.execute(sa.text('CREATE SCHEMA "' + schema + '"'))
            connection.execute(sa.text('SET LOCAL search_path TO "' + schema + '"'))
            existing = [table for table in Base.metadata.sorted_tables if table.name not in FACT_TABLES]
            Base.metadata.create_all(connection, tables=existing)
            novel = _seed_existing_novel(connection)
            migration = _migration()
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            assert FACT_TABLES <= set(sa.inspect(connection).get_table_names(schema=schema))
            migration.downgrade()
            assert not FACT_TABLES.intersection(sa.inspect(connection).get_table_names(schema=schema))
            assert connection.scalar(sa.select(NovelModel.title).where(NovelModel.id == novel)) == "保留原稿"
            migration.upgrade()
            assert FACT_TABLES <= set(sa.inspect(connection).get_table_names(schema=schema))
            transaction.rollback()
    finally:
        engine.dispose()
