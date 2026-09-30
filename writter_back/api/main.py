"""FastAPI application and process-scoped dependency lifecycle."""
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from api.routers import novel_router, workflow_router
from api.routers import workflow_replay_router
from api.routers import harness_metrics_router
from api.routers import admin_router, auth_router, tenant_router, story_fact_router
from api.routers import research_router
from application.auth_service import AuthService
from application.orchestrator import NovelOrchestrator
from application.quota_service import QuotaService
from config import settings
from infrastructure.command_store.postgres_command_store import PostgresWorkflowCommandStore
from infrastructure.database.repository import PostgresNovelRepository
from infrastructure.database.identity_repository import IdentityRepository
from infrastructure.memory.postgres_memory import PostgresMemoryAdapter
from infrastructure.research.library_client import ResearchLibraryClient

if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _build_research_library() -> ResearchLibraryClient | None:
    if not settings.RESEARCH_LIBRARY_ENABLED:
        return None
    return ResearchLibraryClient(
        settings.RESEARCH_LIBRARY_BASE_URL or "",
        settings.RESEARCH_LIBRARY_TOKEN,
        settings.RESEARCH_LIBRARY_TIMEOUT_SECONDS,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    repository = PostgresNovelRepository(
        settings.DATABASE_URL,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
    )
    await repository.init_db()
    identity_repository = IdentityRepository(repository.async_session)
    auth_service = AuthService(identity_repository, settings)
    quota_service = QuotaService(identity_repository)
    memory_service = PostgresMemoryAdapter(settings.DATABASE_URL, repository.async_session)
    research_library = _build_research_library()
    workflow_command_store = PostgresWorkflowCommandStore(repository.async_session)
    await workflow_command_store.recover_expired()
    orchestrator = NovelOrchestrator(
        repository=repository,
        memory_service=memory_service,
        llm_config={
            "provider": settings.DEFAULT_LLM_PROVIDER,
            "model": settings.DEFAULT_MODEL_NAME,
            "deepseek_api_key": settings.DEEPSEEK_API_KEY,
            "openai_api_key": settings.OPENAI_API_KEY,
            "openai_base_url": settings.OPENAI_BASE_URL,
            "anthropic_api_key": settings.ANTHROPIC_API_KEY,
            "timeout": settings.LLM_TIMEOUT_SECONDS,
            "max_retries": settings.LLM_MAX_RETRIES,
        },
        quota_service=quota_service,
        tenant_planning_loader=identity_repository.tenant_novel_planning_enabled,
        research_library=research_library,
    )
    app.state.repository = repository
    app.state.identity_repository = identity_repository
    app.state.auth_service = auth_service
    app.state.quota_service = quota_service
    app.state.memory_service = memory_service
    app.state.research_library = research_library
    app.state.orchestrator = orchestrator
    app.state.workflow_command_store = workflow_command_store
    try:
        yield
    finally:
        await orchestrator.aclose()
        await workflow_command_store.aclose()
        if research_library:
            await research_library.close()
        await repository.aclose()


app = FastAPI(
    title=settings.APP_NAME,
    description="AI 小说创作工作台 API",
    version="0.2.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Idempotency-Key",
        "Last-Event-ID",
        "X-Tenant-ID",
    ],
)
from api.routers import creative_router

app.include_router(creative_router.router, prefix="/api/v1/novels", tags=["Creative"])
app.include_router(creative_router.author_router, prefix="/api/v1/author", tags=["Author Profiles"])
app.include_router(story_fact_router.router, prefix="/api/v1/novels", tags=["Story Facts"])
app.include_router(novel_router.router, prefix="/api/v1/novels", tags=["Novels"])
app.include_router(workflow_router.router, prefix="/api/v1/workflows", tags=["Workflows"])
app.include_router(workflow_replay_router.router, prefix="/api/v1/workflows", tags=["Workflow Recovery"])
app.include_router(harness_metrics_router.router, prefix="/api/v1/workflows", tags=["Harness Metrics"])
app.include_router(auth_router.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(tenant_router.router, prefix="/api/v1/tenants", tags=["Tenants"])
app.include_router(admin_router.router, prefix="/api/v1/admin", tags=["Admin"])
app.include_router(research_router.router, prefix="/api/v1/research", tags=["Research"])


@app.get("/health/live", tags=["Health"])
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["Health"])
async def readiness(request: Request) -> dict[str, str]:
    try:
        await request.app.state.repository.ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    try:
        await request.app.state.workflow_command_store.ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="workflow store unavailable") from exc
    return {"status": "ready"}


@app.get("/", tags=["Health"])
async def root() -> dict[str, str]:
    return {"message": "Novel Writer API is running"}
