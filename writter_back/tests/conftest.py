"""集成测试配置 - 测试数据库隔离"""
import os
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text

# 设置测试环境变量（必须在导入 config 模块之前设置）
os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:mima12138@localhost:5432/novel_writer_test"
os.environ["ENVIRONMENT"] = "test"

from config import settings
from infrastructure.database.models import Base
from infrastructure.database.repository import PostgresNovelRepository
from service.entities.novel import Novel
from service.value_objects.novel_type import NovelType
from service.value_objects.outline import Outline
from service.value_objects.progress import Progress
from uuid import uuid4
from datetime import datetime


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_database():
    """会话级 fixture：创建测试数据库表结构"""
    test_engine = create_async_engine(settings.DATABASE_URL)
    
    # 先强制删除所有表（CASCADE 清理残留的旧表结构和依赖）
    async with test_engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS chapters CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS novel_memories CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS timeline_events CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS novels CASCADE"))
    
    # 再创建所有表
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield
    
    # 测试结束后清理表
    async with test_engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS chapters CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS novel_memories CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS timeline_events CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS novels CASCADE"))
    await test_engine.dispose()


@pytest_asyncio.fixture
async def repository():
    """每个测试独立的仓库实例"""
    repo = PostgresNovelRepository(settings.DATABASE_URL)
    yield repo
    # 清理：删除所有测试数据
    async with repo.async_session() as session:
        await session.execute(text("DELETE FROM chapters"))
        await session.execute(text("DELETE FROM novel_memories"))
        await session.execute(text("DELETE FROM novels"))
        await session.commit()
    await repo.engine.dispose()


@pytest.fixture
def sample_novel():
    """创建一个示例小说实体（不持久化）"""
    return Novel(
        id=uuid4(),
        user_id=None,
        novel_type=NovelType.SUSPENSE.value,
        title="测试悬疑小说",
        summary="这是一个用于测试的悬疑小说",
        total_outline=None,
        progress=Progress(),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


@pytest.fixture
def sample_novel_with_outline():
    """创建一个带大纲的示例小说实体"""
    outline = Outline(
        story_background="一个发生在封闭别墅的谋杀案",
        main_characters=[{"name": "侦探", "role": "主角"}, {"name": "嫌疑人", "role": "反派"}],
        main_plot={"beginning": "案件发生", "middle": "调查过程", "end": "真相大白"},
        chapters=[{"chapter": 1, "event": "案件发生", "summary": "第一章内容"}],
        writing_style="悬疑紧张",
        total_chapters=10,
    )
    return Novel(
        id=uuid4(),
        user_id=None,
        novel_type=NovelType.SUSPENSE.value,
        title="测试悬疑小说",
        summary="这是一个用于测试的悬疑小说",
        total_outline=outline,
        progress=Progress(current_chapter=0, total_chapters=10),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
