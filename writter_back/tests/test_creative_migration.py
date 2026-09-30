"""迁移DDL及ORM一致性；不将离线编译称为真实数据库验收。"""

from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa

from infrastructure.database.creative_models import CreativeRecordModel
from infrastructure.database.models import Base
from tests.test_tactical_plan_migration import _MigrationRecorder

TABLES = {"creative_sessions", "creative_records", "creative_requests", "author_records"}


def migration():
    spec = spec_from_file_location("creative_migration", Path(__file__).parents[1] / "alembic/versions/0009_autonomous_author.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_autonomous_migration_matches_orm():
    module = migration()
    recorder = _MigrationRecorder()
    module.op = recorder
    module.upgrade()
    assert set(recorder.tables) == TABLES
    assert module.down_revision == "0008_workflow_runtime"
    for name, items in recorder.tables.items():
        columns = {c.name: c.nullable for c in items if isinstance(c, sa.Column)}
        assert columns == {c.name: c.nullable for c in Base.metadata.tables[name].c}
    module.downgrade()
    assert {name for kind, name in recorder.dropped if kind == "table"} == TABLES


def test_autonomous_migration_compiles_postgresql_offline():
    output = StringIO()
    module = migration()
    module.op = Operations(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}))
    module.upgrade()
    sql = output.getvalue()
    assert "DEFAULT false" in sql
    assert "FOREIGN KEY(tenant_id, novel_id) REFERENCES novels (tenant_id, id)" in sql
    assert "uq_creative_record_command" in sql
    assert CreativeRecordModel.__table__.c.digest.type.length == 64
