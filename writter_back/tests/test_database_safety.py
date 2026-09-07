import pytest

from tests.database_safety import database_required, isolated_database_url


def test_app_database_is_never_used_for_destructive_fixtures(monkeypatch):
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost/production")
    assert isolated_database_url().endswith("/novel_writer_test")


@pytest.mark.parametrize("url", ["postgresql+asyncpg://localhost/production", "sqlite:///writer_test"])
def test_non_test_database_is_rejected(monkeypatch, url):
    monkeypatch.setenv("TEST_DATABASE_URL", url)
    with pytest.raises(ValueError, match="独立"):
        isolated_database_url()


@pytest.mark.parametrize("key", ["TEST_DATABASE_URL", "CI", "REQUIRE_DATABASE_TESTS"])
def test_explicit_database_or_ci_requires_integration_tests(monkeypatch, key):
    monkeypatch.setenv(key, "true")
    assert database_required() is True
