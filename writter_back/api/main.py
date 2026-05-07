"""FastAPI主应用 - 带依赖注入装配"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from api.routers import novel_router, workflow_router
from infrastructure.database.repository import PostgresNovelRepository
from config import settings

from typing import AsyncGenerator


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期管理 - 初始化数据库表"""
    repo = PostgresNovelRepository(settings.DATABASE_URL)
    await repo.init_db()
    yield
    # 关闭工作流编排器的连接池
    from api.routers.workflow_router import shutdown_orchestrator
    await shutdown_orchestrator()


app = FastAPI(
    title=settings.APP_NAME,
    description="AI自动创作小说系统API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(novel_router.router, prefix="/api/v1/novels", tags=["Novels"])
app.include_router(workflow_router.router, prefix="/api/v1/workflows", tags=["Workflows"])


@app.get("/")
async def root():
    return {"message": "Novel Writer API is running"}
