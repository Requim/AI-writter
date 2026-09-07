import os

from sqlalchemy.engine import make_url


def isolated_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://localhost:5432/novel_writer_test")
    parsed = make_url(url)
    if parsed.drivername != "postgresql+asyncpg" or not (parsed.database or "").endswith("_test"):
        raise ValueError("TEST_DATABASE_URL 必须指向以 _test 结尾的独立 PostgreSQL 测试库")
    return url


def database_required() -> bool:
    return bool(os.environ.get("TEST_DATABASE_URL")) or any(
        os.environ.get(key, "").lower() in {"1", "true", "yes"}
        for key in ("CI", "REQUIRE_DATABASE_TESTS")
    )
