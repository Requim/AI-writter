"""研究批次执行入口；API 进程可将同一执行器交给后台任务。"""

from __future__ import annotations

import asyncio

from .batch_runner import ResearchBatchRunner
from .config import settings
from .database import ResearchDatabase
from .repository import SqlAlchemyResearchRepository
from .service import ResearchKnowledgeService
from .summarizer import create_summarizer

__all__ = ["ResearchBatchRunner"]


async def run_worker(poll_seconds: float = 1.0) -> None:
    database = ResearchDatabase(settings.database_url)
    await database.init()
    repository = SqlAlchemyResearchRepository(database.sessions)
    knowledge = ResearchKnowledgeService(repository)
    runner = ResearchBatchRunner(
        repository,
        knowledge,
        allow_opening=settings.opening_authorized,
        summarizer=create_summarizer(
            settings.llm_base_url, settings.llm_api_key, settings.summary_model
        ),
    )
    try:
        while True:
            claimed = await repository.claim_next_job()
            if claimed:
                job_id, request = claimed
                await runner.run(request, job_id)
            else:
                await asyncio.sleep(poll_seconds)
    finally:
        await database.close()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
