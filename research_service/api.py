"""研究采集和类型知识检索 API。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from sqlalchemy import text

from .batch_runner import ResearchBatchRunner
from .config import Settings, settings
from .contracts import (
    BatchAccepted, BatchRequest, GenreKnowledgePackage, JobStatus,
    KnowledgeQuery, ResearchSample, ReviewRequest,
    PROJECT_GENRE_LABELS, SOURCE_TO_PROJECT_GENRES,
)
from .database import ResearchDatabase
from .repository import InMemoryResearchRepository, ResearchRepository, SqlAlchemyResearchRepository
from .service import ResearchKnowledgeService
from .summarizer import create_summarizer


def _authorized(config: Settings, token: str | None) -> None:
    if config.internal_token and token != config.internal_token:
        raise HTTPException(status_code=401, detail="研究服务令牌无效")
    if config.environment == "production" and not config.internal_token:
        raise HTTPException(status_code=503, detail="研究服务未配置内部令牌")


def create_app(
    repository: ResearchRepository | None = None,
    config: Settings | None = None,
) -> FastAPI:
    config = config or settings
    selected_repository = repository
    database: ResearchDatabase | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        nonlocal selected_repository, database
        if selected_repository is None and config.database_url:
            database = ResearchDatabase(config.database_url)
            await database.init()
            selected_repository = SqlAlchemyResearchRepository(database.sessions)
        selected_repository = selected_repository or InMemoryResearchRepository()
        app.state.repository = selected_repository
        app.state.knowledge = ResearchKnowledgeService(selected_repository)
        app.state.runner = ResearchBatchRunner(
            selected_repository,
            app.state.knowledge,
            allow_opening=config.opening_authorized,
            summarizer=create_summarizer(
                config.llm_base_url, config.llm_api_key, config.summary_model
            ),
        )
        yield
        if database:
            await database.close()

    app = FastAPI(
        title=config.service_name,
        version="0.1.0",
        root_path=config.root_path,
        lifespan=lifespan,
    )

    async def auth(x_research_token: str | None = Header(default=None)) -> None:
        _authorized(config, x_research_token)

    @app.get("/health/live", tags=["Health"])
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["Health"])
    async def ready(request: Request) -> dict[str, str]:
        repository = request.app.state.repository
        if hasattr(repository, "sessions"):
            async with repository.sessions() as session:
                await session.execute(text("SELECT 1"))
        return {"status": "ready"}

    @app.get("/internal/v1/research/capabilities", dependencies=[Depends(auth)])
    async def capabilities() -> dict[str, object]:
        return {
            "retrieval_backend": "keyword", "vector_enabled": False,
            "raw_text_persistence": False,
            "genre_labels": PROJECT_GENRE_LABELS,
            "source_to_project_genres": SOURCE_TO_PROJECT_GENRES,
        }

    @app.post("/internal/v1/research/samples", dependencies=[Depends(auth)])
    async def ingest_sample(sample: ResearchSample, request: Request) -> dict[str, object]:
        package = await request.app.state.knowledge.ingest_sample(sample)
        return {"inserted": package is not None, "knowledge": package.model_dump(mode="json") if package else None}

    @app.post("/internal/v1/research/batches", response_model=BatchAccepted, dependencies=[Depends(auth)])
    async def create_batch(
        body: BatchRequest, request: Request
    ) -> BatchAccepted:
        job_id = f"job-{uuid4().hex}"
        await request.app.state.repository.add_batch(body.batch_id, body.model_dump(mode="json"))
        await request.app.state.repository.add_job(job_id, body.batch_id)
        return BatchAccepted(batch_id=body.batch_id, job_id=job_id)

    @app.get("/internal/v1/research/jobs/{job_id}", response_model=JobStatus, dependencies=[Depends(auth)])
    async def get_job(job_id: str, request: Request) -> JobStatus:
        result = await request.app.state.repository.get_job(job_id)
        if result is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return JobStatus.model_validate(result)

    @app.get("/internal/v1/research/knowledge/search", dependencies=[Depends(auth)])
    async def search_knowledge(
        request: Request,
        project_genre: str = Query(...),
        q: str = Query(default=""),
        opening_pattern: str | None = Query(default=None),
        mechanism: str | None = Query(default=None),
        limit: int = Query(default=8, ge=1, le=50),
        approved_only: bool = Query(default=True),
    ) -> dict[str, object]:
        query = KnowledgeQuery(
            project_genre=project_genre, query=q,
            opening_pattern=opening_pattern, mechanism=mechanism, limit=limit,
            approved_only=approved_only,
        )
        hits = await request.app.state.knowledge.search(query)
        return {"items": [hit.model_dump(mode="json") for hit in hits], "backend": "keyword"}

    @app.get("/internal/v1/research/knowledge/{project_genre}", dependencies=[Depends(auth)])
    async def current_knowledge(project_genre: str, request: Request) -> dict[str, object]:
        packages = await request.app.state.repository.list_packages(project_genre, approved_only=True)
        if not packages:
            raise HTTPException(status_code=404, detail="该题材暂无已审核知识包")
        return packages[0].model_dump(mode="json")

    @app.post("/internal/v1/research/knowledge/{version_id}/review", dependencies=[Depends(auth)])
    async def review_knowledge(
        version_id: str, body: ReviewRequest, request: Request
    ) -> GenreKnowledgePackage:
        package = await request.app.state.knowledge.review(version_id, body.decision)
        if package is None:
            raise HTTPException(status_code=404, detail="知识版本不存在")
        return package

    return app


app = create_app()
