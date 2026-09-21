"""登录用户访问独立研究服务的代理路由。"""

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from api.dependencies import get_tenant_context
from infrastructure.research.library_client import (
    ResearchLibraryClient,
    ResearchLibraryUnavailable,
)
from service.entities.identity import TenantContext

router = APIRouter()


def require_research_access(
    context: TenantContext = Depends(get_tenant_context),
) -> TenantContext:
    """限制研究资料操作只对租户所有者和管理员开放。"""
    if context.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="研究资料仅限租户所有者或管理员访问")
    return context


def _client(request: Request) -> ResearchLibraryClient:
    client = getattr(request.app.state, "research_library", None)
    if client is None:
        raise HTTPException(status_code=503, detail="研究库未启用或未配置")
    return client


async def _invoke(
    request: Request,
    operation: Callable[[ResearchLibraryClient], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    try:
        return await operation(_client(request))
    except ResearchLibraryUnavailable as exc:
        if exc.status_code in {401, 403}:
            raise HTTPException(status_code=502, detail="研究库内部鉴权失败") from exc
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/capabilities", dependencies=[Depends(require_research_access)])
async def capabilities(request: Request) -> dict[str, Any]:
    """返回研究服务能力；内部令牌只由后端注入。"""
    return await _invoke(request, lambda client: client.capabilities())


@router.post("/batches", dependencies=[Depends(require_research_access)])
async def create_batch(
    request: Request,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """创建研究采集批次。"""
    return await _invoke(request, lambda client: client.create_batch(payload))


@router.get("/jobs/{job_id}", dependencies=[Depends(require_research_access)])
async def get_job(request: Request, job_id: str) -> dict[str, Any]:
    """查询研究采集任务。"""
    return await _invoke(request, lambda client: client.job(job_id))


@router.get("/knowledge/search", dependencies=[Depends(require_research_access)])
async def search_knowledge(
    request: Request,
    project_genre: str = Query(...),
    q: str = Query(default=""),
    opening_pattern: str | None = Query(default=None),
    mechanism: str | None = Query(default=None),
    limit: int = Query(default=8, ge=1, le=50),
) -> dict[str, Any]:
    """检索当前已审核的类型知识包。"""
    return await _invoke(
        request,
        lambda client: client.search(
            project_genre=project_genre,
            query=q,
            opening_pattern=opening_pattern,
            mechanism=mechanism,
            limit=limit,
        ),
    )


@router.get("/knowledge/{project_genre}", dependencies=[Depends(require_research_access)])
async def current_knowledge(request: Request, project_genre: str) -> dict[str, Any]:
    """读取指定题材当前知识包。"""
    return await _invoke(request, lambda client: client.current(project_genre))


@router.post(
    "/knowledge/{version_id}/review",
    dependencies=[Depends(require_research_access)],
)
async def review_knowledge(
    request: Request,
    version_id: str,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """审核研究知识版本。"""
    return await _invoke(request, lambda client: client.review(version_id, payload))
