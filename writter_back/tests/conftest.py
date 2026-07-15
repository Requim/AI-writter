"""Shared fixtures for optional PostgreSQL tenant-isolation integration tests."""

from datetime import datetime
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://localhost:5432/novel_writer_test",
    ),
)
os.environ["ENVIRONMENT"] = "test"
os.environ.setdefault("JWT_SECRET", "test-secret-that-is-longer-than-thirty-two-characters")

from api.dependencies import get_tenant_context
from config import settings
from infrastructure.database.models import (
    Base,
    TenantMembershipModel,
    TenantModel,
    UserModel,
)
from infrastructure.database.repository import PostgresNovelRepository
from service.entities.identity import TenantContext
from service.entities.novel import Novel
from service.value_objects.novel_type import NovelType
from service.value_objects.outline import Outline
from service.value_objects.progress import Progress


@pytest_asyncio.fixture(scope="session")
async def setup_test_database():
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
    except (OSError, ConnectionRefusedError):
        await engine.dispose()
        pytest.skip("PostgreSQL test database is not available")
    yield
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def repository(setup_test_database):
    repo = PostgresNovelRepository(settings.DATABASE_URL)
    yield repo
    async with repo.async_session() as session, session.begin():
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(table.delete())
    await repo.aclose()


async def _create_context(repository, name: str, email: str) -> TenantContext:
    user = UserModel(email=email, password_hash="not-used")
    tenant = TenantModel(name=name, slug=f"tenant-{uuid4().hex[:8]}")
    async with repository.async_session() as session, session.begin():
        session.add_all([user, tenant])
        await session.flush()
        session.add(
            TenantMembershipModel(tenant_id=tenant.id, user_id=user.id, role="owner")
        )
    return TenantContext(
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        user_id=user.id,
        role="owner",
        is_platform_admin=False,
        ai_enabled=True,
        monthly_generation_limit=30,
    )


@pytest_asyncio.fixture
async def tenant_context(repository):
    return await _create_context(repository, "甲方编辑部", "owner-a@example.com")


@pytest_asyncio.fixture
async def other_tenant_context(repository):
    return await _create_context(repository, "乙方编辑部", "owner-b@example.com")


@pytest.fixture
def sample_novel(tenant_context):
    return Novel(
        id=uuid4(),
        tenant_id=tenant_context.tenant_id,
        user_id=tenant_context.user_id,
        novel_type=NovelType.SUSPENSE.value,
        title="测试悬疑小说",
        summary="这是一个用于测试的悬疑小说",
        progress=Progress(),
        thread_id=None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


@pytest.fixture
def sample_novel_with_outline(tenant_context):
    outline = Outline(
        story_background="一个发生在封闭别墅的谋杀案",
        main_characters=[{"name": "侦探", "role": "主角"}],
        main_plot={"beginning": "案件发生", "middle": "调查", "end": "真相"},
        chapters=[{"chapter": 1, "event": "案件发生", "summary": "第一章"}],
        writing_style="悬疑紧张",
        total_chapters=10,
    )
    novel = Novel(
        id=uuid4(),
        tenant_id=tenant_context.tenant_id,
        user_id=tenant_context.user_id,
        novel_type=NovelType.SUSPENSE.value,
        title="测试悬疑小说",
        summary="这是一个用于测试的悬疑小说",
        total_outline=outline,
        progress=Progress(current_chapter=0, total_chapters=10),
    )
    return novel


@pytest_asyncio.fixture
async def async_client(repository, tenant_context):
    from httpx import ASGITransport, AsyncClient
    from api.main import app

    app.state.repository = repository
    app.dependency_overrides[get_tenant_context] = lambda: tenant_context
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
