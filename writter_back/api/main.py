"""FastAPI application and process-scoped dependency lifecycle."""
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from api.routers import novel_router, workflow_router
from api.routers import admin_router, auth_router, tenant_router
from application.auth_service import AuthService
from application.orchestrator import NovelOrchestrator
from application.quota_service import QuotaService
from config import settings
from infrastructure.database.repository import PostgresNovelRepository
from infrastructure.database.identity_repository import IdentityRepository
from infrastructure.memory.postgres_memory import PostgresMemoryAdapter

if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


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
    )
    app.state.repository = repository
    app.state.identity_repository = identity_repository
    app.state.auth_service = auth_service
    app.state.quota_service = quota_service
    app.state.memory_service = memory_service
    app.state.orchestrator = orchestrator
    try:
        yield
    finally:
        await orchestrator.aclose()
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
    allow_headers=["Authorization", "Content-Type", "Last-Event-ID", "X-Tenant-ID"],
)
app.include_router(novel_router.router, prefix="/api/v1/novels", tags=["Novels"])
app.include_router(workflow_router.router, prefix="/api/v1/workflows", tags=["Workflows"])
app.include_router(auth_router.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(tenant_router.router, prefix="/api/v1/tenants", tags=["Tenants"])
app.include_router(admin_router.router, prefix="/api/v1/admin", tags=["Admin"])


@app.get("/health/live", tags=["Health"])
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["Health"])
async def readiness(request: Request) -> dict[str, str]:
    try:
        await request.app.state.repository.ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ready"}


@app.get("/", tags=["Health"])
async def root() -> dict[str, str]:
    return {"message": "Novel Writer API is running"}
