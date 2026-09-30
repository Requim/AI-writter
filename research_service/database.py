"""研究服务数据库生命周期。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import ResearchBase


class ResearchDatabase:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("RESEARCH_DATABASE_URL 未配置")
        self.engine = create_async_engine(database_url, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

    async def init(self) -> None:
        async with self.engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                from sqlalchemy import text
                await connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            await connection.run_sync(ResearchBase.metadata.create_all)

    async def ping(self) -> None:
        from sqlalchemy import text
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def close(self) -> None:
        await self.engine.dispose()
