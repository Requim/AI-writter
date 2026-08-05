"""Regression coverage for the explicit unlimited-quota migration."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text


def load_migration_module():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "0004_unlimited_generation_quota.py"
    spec = spec_from_file_location("unlimited_generation_quota_migration", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unlimited_quota_migration_backfills_legacy_sentinel_limits():
    engine = create_engine("sqlite://")
    migration = load_migration_module()

    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE tenants (monthly_generation_limit INTEGER NOT NULL)"))
        connection.execute(text("INSERT INTO tenants VALUES (30), (2000000000), (2147483647)"))
        context = MigrationContext.configure(connection)
        migration.op = Operations(context)

        migration.upgrade()

        rows = connection.execute(text(
            "SELECT monthly_generation_unlimited FROM tenants ORDER BY monthly_generation_limit",
        )).scalars().all()

    assert rows == [0, 1, 1]
