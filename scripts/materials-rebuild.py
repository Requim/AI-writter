"""使用已有样本重建主副题材草稿，不自动审核，不改原始采集记录。"""

import asyncio

from research_service.config import settings
from research_service.contracts import PROJECT_GENRES
from research_service.database import ResearchDatabase
from research_service.repository import SqlAlchemyResearchRepository
from research_service.service import ResearchKnowledgeService


async def main():
    """补齐历史数据的副题材汇总，并保留旧版本供回溯。"""
    database = ResearchDatabase(settings.database_url)
    await database.init()
    repository = SqlAlchemyResearchRepository(database.sessions)
    service = ResearchKnowledgeService(repository)
    try:
        for genre in PROJECT_GENRES:
            samples = await repository.list_samples(genre)
            if not samples:
                continue
            package = await service.refresh_genre(genre)
            print(genre, package.version, package.sample_count, package.status)
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
